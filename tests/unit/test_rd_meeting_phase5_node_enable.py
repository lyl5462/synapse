"""Phase 5：节点 enabled / 会议目标 / 人工确认 + HITL 表单 schema。"""

from __future__ import annotations

from pathlib import Path

import pytest

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.config_store import save_meeting_room_config
from synapse.rd_meeting.hitl_form import default_hitl_form_schema, format_hitl_schema_for_prompt
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


def test_room_intent_equals_node_intent(isolated_config_dir: Path):
    binding = resolve_node_binding("boundary")
    assert binding["room_intent"] == binding["node_intent"]


def test_human_confirm_override(isolated_config_dir: Path):
    save_meeting_room_config({"node_overrides": {"boundary": {"human_confirm": False}}})
    binding = resolve_node_binding("boundary")
    assert binding["human_confirm"] is False
    assert binding["hitl_form_schema"] is None


def test_human_confirm_provides_hitl_schema(isolated_config_dir: Path):
    binding = resolve_node_binding("req_risk")
    assert binding["human_confirm"] is True
    assert binding["hitl_form_schema"] is not None
    assert binding["hitl_form_schema"].get("fields")


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


def test_hitl_schema_prompt_text():
    schema = default_hitl_form_schema("boundary")
    text = format_hitl_schema_for_prompt(schema)
    assert "确认结论" in text


def test_skip_report_body_has_completion_markers():
    body = _skip_node_report_body("boundary")
    assert "结论" in body
    assert node_display_name("boundary") in body


def test_default_human_confirm_for_human_node():
    assert default_human_confirm("req_clarify") is True
    assert default_human_confirm("boundary") is False
