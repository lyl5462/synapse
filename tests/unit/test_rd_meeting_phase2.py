"""Phase 2：meeting_room_config、binding、run-node（dry-run）。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.config_store import meeting_room_config_path
from synapse.rd_meeting.dev_status import load_dev_status, save_dev_status
from synapse.rd_meeting.room_runtime import list_archive_index, load_room_state
from synapse.rd_meeting.service import MeetingRoomService
from synapse.rd_sop.manifest import next_node_id


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


def test_meeting_room_config_put_and_binding(synapse_work_home):
    svc = MeetingRoomService()
    out = svc.put_meeting_room_config(
        {
            "node_overrides": {
                "boundary": {
                    "prompt_supplement": "账务中心专用",
                    "worker_profile_ids": ["default"],
                }
            }
        }
    )
    assert out["node_overrides"]["boundary"]["prompt_supplement"] == "账务中心专用"
    binding = svc.resolve_binding("boundary")
    assert binding["prompt_supplement"] == "账务中心专用"
    assert meeting_room_config_path().is_file()


@pytest.mark.asyncio
async def test_run_node_dry_run_advances_and_archives(synapse_work_home):
    scope_id = "21883200"
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = opened["room_id"]

    dev = load_dev_status(scope_id)
    assert dev is not None
    dev["current_node_id"] = "boundary"
    dev["stage_id"] = 1
    save_dev_status(scope_id, dev)

    result = await svc.run_current_node_sync(room_id, agent_pool=None, dry_run=True)
    assert result["result"]["next_node_id"] == next_node_id("boundary")

    arch = list_archive_index(scope_id)
    assert any(a["node_id"] == "boundary" for a in arch)

    rs = load_room_state(scope_id)
    assert rs is not None
    assert rs["current_node_id"] == next_node_id("boundary")

    nm = rs.get("node_metrics", {}).get("boundary", {})
    assert int(nm.get("tokens") or 0) > 0


@pytest.mark.asyncio
async def test_human_gate_skips_llm(synapse_work_home):
    scope_id = "21883201"
    svc = MeetingRoomService()
    opened = svc.open_meeting("demand", scope_id, sync_userwork=False)
    room_id = opened["room_id"]

    dev = load_dev_status(scope_id)
    assert dev is not None
    dev["current_node_id"] = "req_clarify"
    dev["stage_id"] = 1
    save_dev_status(scope_id, dev)

    out = await svc.run_current_node_sync(room_id, dry_run=True)
    assert out["result"]["status"] == "human_intervention"
    rs = load_room_state(scope_id)
    assert rs is not None
    assert rs["status"] == "human_intervention"
