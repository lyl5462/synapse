"""后台 run_node 未捕获异常时应更新 room_state，而非仅写 node_failed 日志。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synapse.rd_meeting.orchestrator import (
    MeetingRoomOrchestrator,
    _mark_room_after_run_node_exception,
)
from synapse.rd_meeting.paths import room_state_path
from synapse.rd_meeting.room_runtime import load_room_state


def test_mark_room_after_run_node_exception_sets_human_intervention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    scope = "DEMO-EXC"
    scope_dir = work / scope
    scope_dir.mkdir(parents=True)
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: work)
    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.resolve_node_binding",
        lambda node_id, **_k: {"node_id": node_id, "type": "ai", "human_confirm": True},
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.resolve_hitl_schema_for_gate",
        lambda *_a, **_k: {"questions": []},
    )
    monkeypatch.setattr("synapse.rd_meeting.orchestrator.set_phase", lambda *_a, **_k: None)

    def _fake_mark_human_gate(self, **kwargs):  # noqa: ANN001
        sid = str(kwargs["scope_id"]).strip()
        rs = dict(load_room_state(sid) or {})
        rs["status"] = "human_intervention"
        rs["intervention_kind"] = kwargs.get("intervention_kind", "exception")
        from synapse.rd_meeting.room_runtime import save_room_state

        save_room_state(sid, rs)

    monkeypatch.setattr(MeetingRoomOrchestrator, "mark_human_gate", _fake_mark_human_gate)

    room_state_path(scope).write_text(
        json.dumps(
            {
                "room_id": "room-exc",
                "current_node_id": "boundary",
                "status": "processing",
            }
        ),
        encoding="utf-8",
    )

    orch = MeetingRoomOrchestrator()
    _mark_room_after_run_node_exception(
        orch,
        scope_type="demand",
        scope_id=scope,
        room_id="room-exc",
        fail_node="boundary",
        ticket_title="测试工单",
        error="unexpected keyword argument 'usage_scene'",
    )

    rs = load_room_state(scope)
    assert rs is not None
    assert rs["status"] == "human_intervention"
    assert rs.get("intervention_kind") == "exception"
