"""前序 SOP 环节产出提示词段落。"""

from __future__ import annotations

from pathlib import Path

import pytest

from synapse.rd_meeting.prior_outputs import (
    collect_prior_artifact_rows,
    format_prior_sop_outputs_section,
    prior_node_ids,
)
from synapse.rd_meeting.room_skill import build_meeting_runtime_header, make_context
from synapse.rd_sop.manifest import prior_output_use_mode_for


@pytest.fixture
def isolated_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "rd_meeting"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "synapse.rd_meeting.config_store.rd_meeting_config_dir",
        lambda: cfg_dir,
    )
    return cfg_dir


def test_prior_node_ids_order():
    assert prior_node_ids("module_func") == [
        "pending",
        "req_clarify",
        "boundary",
    ]
    assert prior_node_ids("req_clarify") == ["pending"]
    assert prior_node_ids("pending") == []


def test_prior_output_use_mode_for_module_func():
    mode, note = prior_output_use_mode_for(
        "module_func",
        source_node_id="req_clarify",
        artifact="需求澄清.md",
    )
    assert mode == "skill_required"
    assert "module-function" in note


def test_collect_prior_rows_respects_enabled_and_archive(
    isolated_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from synapse.rd_meeting.config_store import save_meeting_room_config

    scope_id = "D-prior"
    save_meeting_room_config({"node_overrides": {"boundary": {"enabled": False}}})

    work = tmp_path / scope_id
    archive = work / "archive" / "需求分析" / "req_clarify"
    archive.mkdir(parents=True)
    (archive / "需求澄清.md").write_text("# 需求澄清\n\n已澄清内容。" * 10, encoding="utf-8")

    monkeypatch.setattr("synapse.rd_meeting.paths.scope_dir", lambda sid: work)
    monkeypatch.setattr(
        "synapse.rd_meeting.prior_outputs.archive_node_dir",
        lambda sid, stg, nid: work / "archive" / stg / nid,
    )

    rows = collect_prior_artifact_rows(scope_id, "module_func")
    clarify = next(r for r in rows if r.source_node_id == "req_clarify")
    boundary = next(r for r in rows if r.source_node_id == "boundary")

    assert clarify.file_exists is True
    assert clarify.use_mode == "skill_required"
    assert boundary.node_enabled is False
    assert boundary.use_mode is None


def test_format_prior_section_in_runtime_header(
    isolated_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    scope_id = "D-header"
    work = tmp_path / scope_id
    archive = work / "archive" / "需求分析" / "req_clarify"
    archive.mkdir(parents=True)
    (archive / "需求澄清.md").write_text("# 需求澄清\n\n正文。" * 20, encoding="utf-8")

    monkeypatch.setattr("synapse.rd_meeting.paths.scope_dir", lambda sid: work)
    monkeypatch.setattr(
        "synapse.rd_meeting.prior_outputs.archive_node_dir",
        lambda sid, stg, nid: work / "archive" / stg / nid,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.prior_outputs.load_skipped_node_ids",
        lambda _sid: set(),
    )

    binding = {
        "node_id": "module_func",
        "node_name": "模块功能",
        "stage_id": 1,
        "stage_name": "需求分析",
        "node_intent": "功能模块拆分。",
        "host_profile_id": "default",
        "worker_profile_ids": ["whalecloud-requirement-expert"],
        "human_confirm": False,
        "node_outputs": ["模块功能.md"],
    }
    ctx = make_context(
        role="host",
        binding=binding,
        scope_type="demand",
        scope_id=scope_id,
        ticket_title="测试工单",
        archive_dir=str(work / "archive" / "需求分析" / "module_func"),
    )
    header = build_meeting_runtime_header(ctx, binding=binding)

    assert "## 前序 SOP 环节产出（本节点可用输入）" in header
    assert "技能强制要求" in header
    assert "流程强制转换" in header
    assert "大模型自主判断" in header
    assert "`需求澄清.md`" in header
    assert "whalecloud-dev-tool-module-function" in header


def test_format_prior_section_empty_for_first_node():
    section = format_prior_sop_outputs_section("x", "pending")
    assert section == ""


def test_format_prior_section_omits_disabled_and_skipped_nodes(
    isolated_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from synapse.rd_meeting.config_store import save_meeting_room_config

    scope_id = "D-omit"
    save_meeting_room_config({"node_overrides": {"boundary": {"enabled": False}}})

    work = tmp_path / scope_id
    archive = work / "archive" / "需求分析" / "req_clarify"
    archive.mkdir(parents=True)
    (archive / "需求澄清.md").write_text("# 需求澄清\n\n正文。" * 20, encoding="utf-8")

    monkeypatch.setattr("synapse.rd_meeting.paths.scope_dir", lambda sid: work)
    monkeypatch.setattr(
        "synapse.rd_meeting.prior_outputs.archive_node_dir",
        lambda sid, stg, nid: work / "archive" / stg / nid,
    )

    section = format_prior_sop_outputs_section(
        scope_id,
        "module_func",
        skipped_node_ids={"pending"},
    )

    assert "`需求澄清.md`" in section
    assert "boundary" not in section
    assert "pending" not in section
    assert "不可用" not in section
    assert "环节已关闭" not in section
    assert "环节已跳过" not in section
