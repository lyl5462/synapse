"""Pipeline 步骤 chat_text 与会议流展示。"""

from __future__ import annotations

from synapse.rd_meeting.flow_log import CHAT_VISIBLE_EVENTS
from synapse.rd_meeting.pipeline_chat import (
    PHASE_WAITING_SUMMARY,
    STEP_OPEN_SUMMARY,
    format_event_chat_display,
    format_host_prompt_step_chat,
    format_phase_change_chat,
    format_room_opened_chat,
)
from synapse.rd_meeting.room_runtime import history_to_chat_logs


def test_pipeline_transition_not_in_chat_visible():
    assert "pipeline_transition" not in CHAT_VISIBLE_EVENTS


def test_step_summaries_exclude_instance_data():
    opened = format_room_opened_chat()
    assert "【步骤 1/3】" in opened
    assert "room_id" not in opened.lower()
    assert "userwork" not in opened

    host = format_host_prompt_step_chat()
    assert "【步骤 3/3】" in host
    assert "## 一、" not in host
    assert "四段式" in host

    waiting = format_phase_change_chat(to_phase="waiting")
    assert waiting == PHASE_WAITING_SUMMARY
    assert format_phase_change_chat(to_phase="running") is None


def test_chat_logs_skip_pipeline_transition():
    ev = {
        "event": "pipeline_transition",
        "from_step": "node_init",
        "to_step": "assemble_host_prompt",
        "text": '{"from_step":"node_init","to_step":"assemble_host_prompt"}',
        "agent_id": "system",
        "ts": "2026-05-21T10:00:00",
    }
    assert history_to_chat_logs([ev]) == []


def test_phase_change_not_in_chat_visible():
    """phase_change 不再写入 history；旧数据仍可按 chat_text 解析展示。"""
    assert "phase_change" not in CHAT_VISIBLE_EVENTS
    ev = {
        "event": "phase_change",
        "to_phase": "waiting",
        "chat_text": PHASE_WAITING_SUMMARY,
        "agent_id": "default",
        "ts": "2026-05-21T10:00:01",
    }
    assert history_to_chat_logs([ev]) == []


def test_room_opened_prefers_process_chat_text():
    ev = {
        "event": "room_opened",
        "room_id": "room-1",
        "scope_id": "D1",
        "agent_id": "default",
        "ts": "2026-05-21T10:00:00",
    }
    assert format_event_chat_display(ev) == STEP_OPEN_SUMMARY
    logs = history_to_chat_logs([{**ev, "chat_text": STEP_OPEN_SUMMARY}])
    assert logs[0]["agentId"] == "default"
    assert logs[0].get("rich") is not True
