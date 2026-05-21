"""P1/P2/P3：live、phase、产物、门控 schema 单测。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from synapse.rd_meeting.artifacts import validate_archive_outputs, write_node_deliverables
from synapse.rd_meeting.hitl_form import fallback_exception_hitl_schema, normalize_hitl_schema
from synapse.rd_meeting.live import parse_rd_meeting_session, record_delegation_started
from synapse.rd_meeting.phase import get_phase, set_phase
from synapse.rd_meeting.room_runtime import history_to_chat_logs


def test_parse_rd_meeting_session() -> None:
    assert parse_rd_meeting_session("rd_meeting:room-1:host") == {
        "room_id": "room-1",
        "role": "host",
        "profile_id": "",
    }
    assert parse_rd_meeting_session("rd_meeting:room-1:req-analyst") == {
        "room_id": "room-1",
        "role": "req-analyst",
        "profile_id": "req-analyst",
    }
    assert parse_rd_meeting_session("desktop:abc") is None


def test_phase_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, dict] = {}

    monkeypatch.setattr(
        "synapse.rd_meeting.phase.load_room_state",
        lambda sid: store.get(sid),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.phase.save_room_state",
        lambda sid, payload: store.__setitem__(sid, payload) or payload,
    )
    sid = "scope-a"
    set_phase(sid, "clarify_gate")
    assert get_phase(sid) == "clarify_gate"


def test_history_includes_delegation_events() -> None:
    logs = history_to_chat_logs(
        [
            {
                "event": "delegation_started",
                "text": "小鲸 → worker-a：已委派",
                "agent_id": "host",
                "ts": "2026-05-21T10:00:00",
            }
        ]
    )
    assert len(logs) == 1
    assert "委派" in logs[0]["text"]


def test_fallback_exception_schema() -> None:
    schema = normalize_hitl_schema(
        fallback_exception_hitl_schema("req_clarify", reason="超时")
    )
    assert schema.get("questions")
    blob = json.dumps(schema, ensure_ascii=False)
    assert "超时" in blob


def test_write_node_deliverables_and_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = "test-scope-deliverables"
    monkeypatch.setattr("synapse.rd_meeting.paths.scope_dir", lambda s: tmp_path / s)
    monkeypatch.setattr(
        "synapse.rd_meeting.artifacts.scope_dir",
        lambda s: tmp_path / s,
    )
    body = "# 需求澄清\n\n## 结论\n交付完成，结论已确认。\n" + ("x" * 80)
    artifacts = write_node_deliverables(sid, 1, "req_clarify", body)
    assert artifacts
    ok, errors = validate_archive_outputs(sid, 1, "req_clarify")
    assert ok, errors


def test_record_delegation_started_appends_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope_id = "deleg-scope"
    work = tmp_path / scope_id
    work.mkdir(parents=True)
    dev_path = work / "dev.status"
    dev_path.write_text(
        json.dumps(
            {
                "meeting_room": {"room_id": "room-deleg", "active": True},
                "current_node_id": "req_clarify",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.live.iter_work_order_directories",
        lambda: [work],
    )
    monkeypatch.setattr("synapse.rd_meeting.live.scope_id_for_room_id", lambda rid: scope_id)
    monkeypatch.setattr(
        "synapse.rd_meeting.live.append_history_event",
        lambda sid, row: None,
    )
    with patch("synapse.rd_meeting.live.append_meeting_live_event") as mock_append:
        record_delegation_started(
            "rd_meeting:room-deleg:host",
            from_agent="host",
            to_agent="worker-a",
            reason="澄清需求",
        )
        mock_append.assert_called_once()


def test_get_room_live_not_found() -> None:
    from synapse.rd_meeting.service import MeetingRoomService

    svc = MeetingRoomService()
    assert svc.get_room_live("nonexistent-room-xyz") is None
