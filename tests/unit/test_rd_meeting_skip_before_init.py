"""disabled 节点应在 node_init 之前跳过，不写初始化 history。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from synapse.rd_meeting.config_store import save_meeting_room_config
from synapse.rd_meeting.dev_status import default_dev_status, load_dev_status, save_dev_status
from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator
from synapse.rd_meeting.pipeline import (
    MeetingPipeline,
    PipelineRunContext,
    STEP_NODE_FINISH,
    STEP_NODE_INIT,
    STEP_WAITING,
    _step_node_init,
    run_pipeline_until_waiting,
)
from synapse.rd_meeting.room_runtime import read_history
from synapse.rd_sop.manifest import next_node_id


@pytest.fixture
def isolated_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    cfg_dir = tmp_path / "rd_meeting"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "synapse.rd_meeting.config_store.rd_meeting_config_dir",
        lambda: cfg_dir,
    )
    return cfg_dir


@pytest.fixture
def meeting_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    isolated_config_dir: Path,
):
    work = tmp_path / "21881499"
    work.mkdir(parents=True)
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path)
    monkeypatch.setattr(
        "synapse.rd_meeting.paths.scope_dir",
        lambda sid: work if sid == "21881499" else tmp_path / sid,
    )

    save_meeting_room_config({"node_overrides": {"boundary": {"enabled": False}}})

    dev = default_dev_status(
        scope_type="demand",
        scope_id="21881499",
        local_process_state="处理中",
        stage_id=1,
        current_node_id="boundary",
        pipeline_enabled=True,
    )
    dev["meeting_room"] = {"active": True, "room_id": "mr_test_skip"}
    save_dev_status("21881499", dev)
    return "21881499"


def test_advance_past_disabled_nodes_skips_without_init_history(meeting_scope: str) -> None:
    scope_id = meeting_scope
    orch = MeetingRoomOrchestrator()
    out = orch.advance_past_disabled_nodes(
        scope_type="demand",
        scope_id=scope_id,
        room_id="mr_test_skip",
        sync_userwork=False,
        schedule_pipeline_advance=False,
    )
    assert out["skipped_nodes"] == ["boundary"]
    assert out["current_node_id"] == next_node_id("boundary")

    boundary_hist = read_history(scope_id, node_id="boundary")
    events = [str(ev.get("event") or "") for ev in boundary_hist]
    assert "node_skipped" in events
    assert "node_init" not in events
    assert "host_prompt_assembled" not in events


def test_pipeline_node_init_skips_redirects_to_node_finish(meeting_scope: str) -> None:
    scope_id = meeting_scope
    pipe = MeetingPipeline.create(scope_id, scope_type="demand", flow_step=STEP_NODE_INIT)
    pipe._data["room_id"] = "mr_test_skip"
    pipe.save()
    ctx = PipelineRunContext(
        scope_type="demand",
        scope_id=scope_id,
        dev_status=load_dev_status(scope_id),
        detail={"ticket_title": "t", "scope_id": scope_id},
    )
    _step_node_init(pipe, ctx)

    assert pipe.flow_step == STEP_NODE_FINISH
    pctx = pipe._data.get("context") or {}
    assert pctx.get("last_finished_node_id") == "boundary"

    boundary_hist = read_history(scope_id, node_id="boundary")
    events = [str(ev.get("event") or "") for ev in boundary_hist]
    assert "node_skipped" in events
    assert "node_init" not in events

    next_id = next_node_id("boundary")
    next_hist = read_history(scope_id, node_id=next_id)
    next_events = [str(ev.get("event") or "") for ev in next_hist]
    assert "node_init" not in next_events


def test_skip_disabled_single_pipeline_init_once(meeting_scope: str) -> None:
    """boundary disabled：同一次 run_pipeline 内 node_finish(boundary) → node_init(next) 只 init 一次。"""
    scope_id = meeting_scope
    next_id = next_node_id("boundary")

    pipe = MeetingPipeline.create(scope_id, scope_type="demand", flow_step=STEP_NODE_FINISH)
    pipe._data["room_id"] = "mr_test_skip"
    pctx = pipe._data.get("context")
    if not isinstance(pctx, dict):
        pctx = {}
    pctx["last_finished_node_id"] = "req_clarify"
    pipe._data["context"] = pctx
    pipe.set_flow_step(STEP_NODE_FINISH, reason="test")
    pipe.save()

    ctx = PipelineRunContext(
        scope_type="demand",
        scope_id=scope_id,
        dev_status=load_dev_status(scope_id),
        detail={"ticket_title": "t", "scope_id": scope_id},
    )

    with patch("synapse.rd_meeting.pipeline._schedule_current_node") as mock_schedule:
        result_pipe = run_pipeline_until_waiting(ctx, initial_flow_step=STEP_NODE_FINISH)

    assert mock_schedule.call_count == 1
    assert result_pipe.flow_step == STEP_WAITING

    next_events = [str(ev.get("event") or "") for ev in read_history(scope_id, node_id=next_id)]
    assert next_events.count("node_init") == 1
    assert next_events.count("host_prompt_assembled") == 1

    boundary_events = [str(ev.get("event") or "") for ev in read_history(scope_id, node_id="boundary")]
    assert "node_skipped" in boundary_events
    assert boundary_events.count("node_finished") == 1
