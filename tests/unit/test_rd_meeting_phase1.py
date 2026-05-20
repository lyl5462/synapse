"""Phase 1：room_state、room_history、intervene、meeting-summary。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.dev_status import default_dev_status
from synapse.rd_meeting.room_runtime import load_room_state, read_history
from synapse.rd_meeting.service import MeetingRoomService


@pytest.fixture
def synapse_work_home(monkeypatch: pytest.MonkeyPatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()

    def _work_root():
        return work

    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", _work_root)
    return work


def test_open_meeting_creates_room_state_and_history(synapse_work_home):
    scope_id = "21883170"
    svc = MeetingRoomService()
    detail = svc.open_meeting("demand", scope_id, sync_userwork=False)

    assert detail["scope_id"] == scope_id
    assert detail["room_id"]
    rs = load_room_state(scope_id)
    assert rs is not None
    assert rs["room_id"] == detail["room_id"]
    assert rs["current_node_id"] == detail["current_node_id"]

    hist = read_history(scope_id)
    assert any(h.get("event") == "room_opened" for h in hist)


def test_intervene_appends_history(synapse_work_home):
    scope_id = "21883171"
    svc = MeetingRoomService()
    detail = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = detail["room_id"]

    out = svc.intervene(room_id, text="请继续排查沙箱", message_type="instruction")
    assert out["room_id"] == room_id
    hist = read_history(scope_id)
    assert any(h.get("event") == "human_intervene" for h in hist)


def test_meeting_summary_nodes_and_archive(synapse_work_home):
    scope_id = "11879580"
    d = synapse_work_home / scope_id
    d.mkdir()
    dev = default_dev_status(
        scope_type="task",
        scope_id=scope_id,
        local_process_state="处理中",
        stage_id=4,
        current_node_id="diff_analysis",
        pipeline_enabled=True,
    )
    dev["meeting_room"] = {"active": True, "room_id": "mr_t_11879580_s4"}
    (d / "dev.status").write_text(json.dumps(dev, ensure_ascii=False), encoding="utf-8")

    svc = MeetingRoomService()
    svc.open_meeting("task", scope_id, sync_userwork=False)

    arch = d / "archive" / "4" / "diff_analysis"
    arch.mkdir(parents=True)
    (arch / "report.md").write_text("# diff", encoding="utf-8")

    summary = svc.meeting_summary("task", scope_id)
    assert summary["scope_id"] == scope_id
    assert len(summary["nodes"]) > 0
    node_ids = [n["node_id"] for n in summary["nodes"]]
    assert "diff_analysis" in node_ids
    assert summary["archive_index"]
    assert summary["archive_index"][0]["files"][0]["name"] == "report.md"


def test_get_room_detail(synapse_work_home):
    scope_id = "21883172"
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    detail = svc.get_room_detail(opened["room_id"])
    assert detail is not None
    assert detail["history"]
    assert "room_state" in detail
