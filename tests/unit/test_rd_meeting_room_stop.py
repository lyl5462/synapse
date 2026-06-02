"""会议室 stopped：服务重启扫描（failed 不改）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synapse.rd_meeting.paths import room_state_path
from synapse.rd_meeting.room_runtime import load_room_state
from synapse.rd_meeting.room_stop import mark_active_rooms_stopped_on_server_restart


@pytest.mark.parametrize(
    "status,expect_stopped",
    [
        ("processing", True),
        ("human_intervention", True),
        ("failed", False),
        ("completed", False),
        ("stopped", False),
    ],
)
def test_mark_stopped_on_restart_respects_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expect_stopped: bool,
) -> None:
    work = tmp_path / "work"
    scope = "DEMO-001"
    scope_dir = work / scope
    scope_dir.mkdir(parents=True)
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: work)
    monkeypatch.setattr(
        "synapse.rd_meeting.room_stop.iter_work_order_directories",
        lambda: [scope_dir],
    )

    payload = {
        "room_id": "room-1",
        "current_node_id": "n1",
        "status": status,
    }
    room_state_path(scope).write_text(json.dumps(payload), encoding="utf-8")

    mark_active_rooms_stopped_on_server_restart()

    rs = load_room_state(scope)
    assert rs is not None
    if expect_stopped:
        assert rs["status"] == "stopped"
        assert rs.get("stopped_reason") == "server_restart"
    else:
        assert rs["status"] == status
