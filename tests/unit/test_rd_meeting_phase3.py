"""Phase 3：开会推进、人工通知列表、产物校验。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.dev_status import load_dev_status, save_dev_status
from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator
from synapse.rd_meeting.room_runtime import load_room_state
from synapse.rd_meeting.service import MeetingRoomService
from synapse.rd_meeting.validation import (
    normalize_node_output_body,
    resolve_delivery_body_for_archive,
    validate_node_archive_artifacts,
    validate_node_output,
)


@pytest.fixture
def synapse_work_home(monkeypatch: pytest.MonkeyPatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    cfg_dir = work / "_rd_meeting_cfg"
    cfg_dir.mkdir(parents=True)

    def _work_root():
        return work

    def _rd_cfg_dir():
        return cfg_dir

    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", _work_root)
    monkeypatch.setattr("synapse.rd_meeting.config_store.rd_meeting_config_dir", _rd_cfg_dir)
    return work


def test_open_meeting_promote_to_processing(synapse_work_home):
    from synapse.rd_meeting.dev_status import load_or_create_dev_status

    scope_id = "21883300"
    svc = MeetingRoomService()
    dev_before = load_or_create_dev_status(
        scope_id,
        scope_type="demand",
        local_process_state="待处理",
        stage_id=0,
        current_node_id="pending",
    )
    dev_before["local_process_state"] = "待处理"
    dev_before["current_node_id"] = "pending"
    dev_before["stage_id"] = 0
    save_dev_status(scope_id, dev_before)

    detail = svc.open_meeting(
        "demand",
        scope_id,
        sync_userwork=False,
        promote_to_processing=True,
    )
    assert detail["local_process_state"] == "处理中"
    dev = load_dev_status(scope_id)
    assert dev is not None
    assert dev["local_process_state"] == "处理中"
    assert dev["current_node_id"] not in ("pending", "")


def test_list_pending_human_intervention(synapse_work_home):
    scope_id = "21883301"
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = opened["room_id"]

    dev = load_dev_status(scope_id)
    assert dev is not None
    dev["current_node_id"] = "req_clarify"
    dev["stage_id"] = 1
    save_dev_status(scope_id, dev)

    orch = MeetingRoomOrchestrator()
    orch.mark_human_gate(
        scope_type="demand",
        scope_id=scope_id,
        room_id=room_id,
        node_id="req_clarify",
    )

    pending = svc.list_pending_human_intervention()
    assert any(p["scope_id"] == scope_id for p in pending)


def test_validate_node_archive_artifacts_checks_file_existence_only(tmp_path, monkeypatch):
    from synapse.rd_meeting.paths import scope_dir

    scope_id = "21883304"
    node_id = "boundary"
    stage_name = "需求分析"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    dest = scope_dir(scope_id) / "archive" / stage_name / node_id
    dest.mkdir(parents=True)

    missing = validate_node_archive_artifacts(scope_id, stage_name, node_id)
    assert not missing.ok
    assert any("边界确认说明.md" in e for e in missing.errors)

    (dest / "边界确认说明.md").write_text("too short", encoding="utf-8")
    present = validate_node_archive_artifacts(scope_id, stage_name, node_id)
    assert present.ok
    assert len(present.artifacts) == 1


def test_validate_node_output_rejects_short_body():
    bad = validate_node_output("boundary", "too short")
    assert not bad.ok

    good = validate_node_output(
        "boundary",
        "# 边界确认结论\n\n"
        "本节点已完成交付，结论如下：模块边界清晰，无跨产品影响。\n" * 3,
    )
    assert good.ok


def test_normalize_node_output_body_adds_h1():
    body = normalize_node_output_body(
        "req_clarify",
        "本节点已完成需求澄清，结论如下：" + "详细说明。" * 20,
    )
    assert body.startswith("# ")
    assert validate_node_output("req_clarify", body).ok


def test_resolve_delivery_body_prefers_archive_md(tmp_path, monkeypatch):
    from synapse.rd_meeting.paths import scope_dir

    scope_id = "21883303"
    node_id = "req_clarify"
    stage_name = "需求分析"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    dest = scope_dir(scope_id) / "archive" / stage_name / node_id
    dest.mkdir(parents=True)
    archive_text = (
        "# 需求澄清\n\n"
        "本节点已完成交付，结论如下：协作智能体已产出澄清文档，待人工确认归档。\n" * 3
    )
    (dest / "需求澄清.md").write_text(archive_text, encoding="utf-8")

    resolved = resolve_delivery_body_for_archive(
        scope_id,
        node_id,
        "这是没有一级标题的 pending 摘要，" + "内容较短。" * 5,
    )
    assert resolved.startswith("# 需求澄清")
    assert validate_node_archive_artifacts(scope_id, stage_name, node_id).ok


@pytest.mark.asyncio
async def test_dry_run_passes_validation(synapse_work_home):
    scope_id = "21883302"
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = opened["room_id"]

    dev = load_dev_status(scope_id)
    assert dev is not None
    dev["current_node_id"] = "boundary"
    dev["stage_id"] = 1
    save_dev_status(scope_id, dev)

    orch = MeetingRoomOrchestrator()
    result = await orch.run_current_node(
        scope_type="demand",
        scope_id=scope_id,
        room_id=room_id,
        dry_run=True,
    )
    assert result.get("next_node_id")
    rs = load_room_state(scope_id)
    assert rs is not None
