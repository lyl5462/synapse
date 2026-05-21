"""Phase 5：节点 enabled / 会议目标 / 人工确认 + HITL 表单 schema。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.config_store import save_meeting_room_config
from synapse.rd_meeting.hitl_form import (
    default_hitl_form_schema,
    extract_hitl_from_agent_output,
    format_hitl_schema_for_prompt,
)
from synapse.rd_meeting.intents import default_node_intent, resolve_node_intent
from synapse.rd_meeting.orchestrator import _skip_node_report_body
from synapse.rd_meeting.service import MeetingRoomService
from synapse.rd_sop.manifest import default_human_confirm, node_output_artifacts
from synapse.rd_sop.nodes import node_display_name


@pytest.fixture
def isolated_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    cfg_dir = tmp_path / "rd_meeting"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "synapse.rd_meeting.config_store.rd_meeting_config_dir",
        lambda: cfg_dir,
    )
    return cfg_dir


def test_resolve_binding_enabled_defaults_true(isolated_config_dir: Path):
    binding = resolve_node_binding("boundary")
    assert binding["enabled"] is True


def test_resolve_binding_enabled_false_from_override(isolated_config_dir: Path):
    save_meeting_room_config({"node_overrides": {"boundary": {"enabled": False}}})
    binding = resolve_node_binding("boundary")
    assert binding["enabled"] is False


def test_resolve_node_intent_uses_override(isolated_config_dir: Path):
    save_meeting_room_config(
        {"node_overrides": {"boundary": {"node_intent": "自定义会议目标"}}}
    )
    from synapse.rd_meeting.config_store import load_meeting_room_config

    loaded = load_meeting_room_config()
    ov = loaded["node_overrides"]["boundary"]
    intent, def_intent = resolve_node_intent("boundary", node_override=ov)
    assert intent == "自定义会议目标"
    assert def_intent == default_node_intent("boundary")


def test_human_confirm_override(isolated_config_dir: Path):
    save_meeting_room_config({"node_overrides": {"boundary": {"human_confirm": False}}})
    binding = resolve_node_binding("boundary")
    assert binding["human_confirm"] is False
    assert binding["hitl_form_schema"] is None


def test_human_confirm_provides_hitl_schema(isolated_config_dir: Path):
    binding = resolve_node_binding("req_risk")
    assert binding["human_confirm"] is True
    schema = binding["hitl_form_schema"]
    assert schema is not None
    assert schema.get("type") == "questionnaire"
    assert schema.get("questions")
    assert any(q.get("id") == "decision" for q in schema["questions"])


def test_node_outputs_list(isolated_config_dir: Path):
    binding = resolve_node_binding("boundary")
    assert binding["node_outputs"] == node_output_artifacts("boundary")


def test_service_put_persists_human_confirm_and_intent(isolated_config_dir: Path):
    svc = MeetingRoomService()
    saved = svc.put_meeting_room_config(
        {
            "node_overrides": {
                "boundary": {
                    "enabled": False,
                    "node_intent": "边界会议目标",
                    "human_confirm": True,
                }
            },
        }
    )
    ov = saved["node_overrides"]["boundary"]
    assert ov["enabled"] is False
    assert ov["node_intent"] == "边界会议目标"
    assert ov["human_confirm"] is True


def test_extract_hitl_from_agent_output_fence():
    schema = {"type": "questionnaire", "version": "1.0", "questions": [{"id": "q1", "type": "text", "title": "t"}]}
    body = (
        "# 进展\n请确认。\n\n"
        "```hitl-questionnaire\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n```"
    )
    gate = extract_hitl_from_agent_output(body)
    assert gate.explicit is True
    assert gate.clean_body.startswith("# 进展")
    assert gate.schema is not None
    assert gate.schema.get("questions")


def test_extract_hitl_from_agent_output_html_kind():
    schema = {
        "type": "questionnaire",
        "version": "1.0",
        "questions": [{"id": "decision", "type": "single", "title": "结论", "options": []}],
    }
    raw = json.dumps(schema, ensure_ascii=False)
    body = (
        "说明\n\n"
        f"<!-- hitl-questionnaire kind=result_confirm await_confirm=true -->\n"
        f"{raw}\n"
        "<!-- /hitl-questionnaire -->"
    )
    gate = extract_hitl_from_agent_output(body)
    assert gate.explicit is True
    assert gate.intervention_kind == "result_confirm"
    assert gate.await_confirm is True


def test_hitl_schema_prompt_text():
    schema = default_hitl_form_schema("boundary")
    text = format_hitl_schema_for_prompt(schema)
    assert "确认结论" in text
    assert "共 4 题" in text
    assert "decision" in text or "approve" in text


def test_skip_report_body_has_completion_markers():
    body = _skip_node_report_body("boundary")
    assert "结论" in body
    assert node_display_name("boundary") in body


def test_default_human_confirm_for_human_node():
    assert default_human_confirm("req_clarify") is True
    assert default_human_confirm("boundary") is False


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


@pytest.mark.asyncio
async def test_human_confirm_defers_archive_until_approved(synapse_work_home):
    from synapse.rd_meeting.dev_status import load_dev_status, save_dev_status
    from synapse.rd_meeting.room_runtime import list_archive_index, load_room_state
    from synapse.rd_sop.manifest import next_node_id

    scope_id = "21883500"
    save_meeting_room_config({"node_overrides": {"boundary": {"human_confirm": True}}})
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = opened["room_id"]

    dev = load_dev_status(scope_id)
    assert dev is not None
    dev["current_node_id"] = "boundary"
    dev["stage_id"] = 1
    save_dev_status(scope_id, dev)

    result = await svc.run_current_node_sync(room_id, dry_run=True)
    assert result["result"]["status"] == "human_intervention"
    assert result["result"].get("pending_confirm") is True

    arch = list_archive_index(scope_id)
    assert not any(a["node_id"] == "boundary" for a in arch)

    rs = load_room_state(scope_id)
    assert rs is not None
    assert isinstance(rs.get("pending_delivery"), dict)
    assert rs["pending_delivery"].get("report_body")

    detail = svc.intervene(
        room_id,
        text="[人工确认表单]\ndecision: approve\ncomment: 确认无误",
    )
    assert detail is not None

    arch2 = list_archive_index(scope_id)
    assert any(a["node_id"] == "boundary" for a in arch2)

    rs2 = load_room_state(scope_id)
    assert rs2 is not None
    assert rs2.get("pending_delivery") is None
    assert rs2["current_node_id"] == next_node_id("boundary")


@pytest.mark.asyncio
async def test_human_confirm_reject_triggers_rework(synapse_work_home, monkeypatch):
    from synapse.rd_meeting.dev_status import load_dev_status, save_dev_status
    from synapse.rd_meeting.room_runtime import load_room_state

    scheduled: list[str] = []

    def _fake_schedule(**kwargs):
        scheduled.append(kwargs.get("scope_id", ""))
        return kwargs.get("room_id", "")

    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.schedule_run_node",
        _fake_schedule,
    )

    scope_id = "21883501"
    save_meeting_room_config({"node_overrides": {"boundary": {"human_confirm": True}}})
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = opened["room_id"]

    dev = load_dev_status(scope_id)
    assert dev is not None
    dev["current_node_id"] = "boundary"
    dev["stage_id"] = 1
    save_dev_status(scope_id, dev)

    await svc.run_current_node_sync(room_id, dry_run=True)

    svc.intervene(
        room_id,
        text="[人工确认表单]\ndecision: reject\ncomment: 边界描述不完整",
    )

    rs = load_room_state(scope_id)
    assert rs is not None
    assert rs.get("pending_delivery") is None
    assert rs.get("rework_instruction") == "边界描述不完整"
    assert scheduled == [scope_id]
