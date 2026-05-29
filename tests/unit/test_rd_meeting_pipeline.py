"""研发会议室 meeting_pipeline.json 主流程。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.paths import meeting_pipeline_path
from synapse.rd_meeting.pipeline import (
    STEP_ASSEMBLE_HOST_PROMPT,
    STEP_NODE_INIT,
    STEP_OPEN_MEETING,
    STEP_WAITING,
    MeetingPipeline,
    PipelineRunContext,
    run_pipeline_until_waiting,
)


def test_pipeline_file_created_on_open_flow(monkeypatch, tmp_path):
    from synapse.rd_meeting.service import MeetingRoomService

    scope_id = "pipe-demand-1"
    uw_path = tmp_path / "userwork.json"
    uw_path.write_text(
        json.dumps(
            {
                "list": [
                    {
                        "demand_no": scope_id,
                        "demand_title": "T",
                        "demand_desc": "D",
                        "product_version_code": "P",
                        "sop_node": "等待调度",
                        "local_process_state": "待处理",
                        "owned_work_items": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work" / scope_id
    work.mkdir(parents=True)

    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync._owner_order_file_name",
        lambda: uw_path,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync._owner_order_file_lock_path",
        lambda: tmp_path / "userwork.lock",
    )
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda sid, node_id="pending": work / "room_history.jsonl",
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.product_context.ensure_prod_in_catalog",
        lambda p: ([{"prod": p, "version": "v", "repo_info": [], "doc_process": []}], ""),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets.bootstrap_product_assets",
        lambda *_a, **_k: {
            "status": "ok",
            "repos": [],
            "docs": [],
            "code_root": str(work / "code"),
            "doc_root": str(work / "doc"),
            "work_order_dir": str(work),
        },
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_code": "ok", "prod": "myprod", "repos": [], "docs": []},
            {"synapse_url": "http://h:10001"},
        ),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.schedule_run_node",
        lambda **_k: "room-key",
    )

    svc = MeetingRoomService()
    detail = svc.open_meeting("demand", scope_id, prod="myprod")

    ppath = meeting_pipeline_path(scope_id)
    assert ppath.is_file()
    pipe = MeetingPipeline.load(scope_id)
    assert pipe.flow_step == STEP_WAITING
    assert STEP_OPEN_MEETING in (pipe.data.get("steps_completed") or [])
    assert STEP_NODE_INIT in (pipe.data.get("steps_completed") or [])
    assert STEP_ASSEMBLE_HOST_PROMPT in (pipe.data.get("steps_completed") or [])
    ctx_host = pipe.data.get("context", {}).get("host_prompt")
    assert isinstance(ctx_host, dict)
    assert ctx_host.get("dynamic_chars", 0) > 0
    assert ctx_host.get("meeting_prompt_chars", 0) > 0
    assert detail.get("pipeline", {}).get("flow_step") == STEP_WAITING


def test_pipeline_load_missing_raises(monkeypatch, tmp_path):
    scope_id = "pipe-missing"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    with pytest.raises(ValueError, match="meeting_pipeline_not_found"):
        MeetingPipeline.load(scope_id)


def test_pipeline_create_duplicate_raises(monkeypatch, tmp_path):
    scope_id = "pipe-dup"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    MeetingPipeline.create(scope_id, scope_type="demand")
    with pytest.raises(ValueError, match="meeting_pipeline_already_exists"):
        MeetingPipeline.create(scope_id, scope_type="demand")


def test_open_meeting_twice_raises_when_active(monkeypatch, tmp_path):
    from synapse.rd_meeting.service import MeetingRoomService

    scope_id = "pipe-twice"
    work = tmp_path / "work" / scope_id
    work.mkdir(parents=True)
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    monkeypatch.setattr(
        "synapse.rd_meeting.product_context.ensure_prod_in_catalog",
        lambda p: ([{"prod": p}], ""),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets.bootstrap_product_assets",
        lambda *_a, **_k: {"status": "ok", "repos": [], "docs": []},
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: ({"locator_code": "ok", "prod": "p"}, {}),
    )
    monkeypatch.setattr("synapse.rd_meeting.orchestrator.schedule_run_node", lambda **_k: "k")

    svc = MeetingRoomService()
    svc.open_meeting("demand", scope_id, prod="p", sync_userwork=False)
    with pytest.raises(ValueError, match="meeting_room_already_active"):
        svc.open_meeting("demand", scope_id, prod="p", sync_userwork=False)
