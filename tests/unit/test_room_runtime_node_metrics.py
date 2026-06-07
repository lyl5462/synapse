"""room_state.node_metrics 归档逻辑。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.agent_activity import aggregate_node_activity_tokens, aggregate_room_activity_tokens
from synapse.rd_meeting.dev_status import load_dev_status, save_dev_status
from synapse.rd_meeting.paths import agent_node_dir
from synapse.rd_meeting.room_runtime import (
    DEFAULT_NODE_TOKEN_BUDGET,
    DEFAULT_TOKEN_BUDGET,
    compute_node_metrics_seconds,
    compute_stage_elapsed_seconds,
    build_meeting_summary_nodes,
    default_room_state,
    finalize_node_metrics,
    load_room_state,
    refresh_node_metrics,
    resolve_node_seconds,
    save_room_state,
)


def _write_activity(scope: str, node_id: str, profile_id: str, rows: list[dict]) -> None:
    path = agent_node_dir(scope, profile_id, node_id) / "activity.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _isolate_work(monkeypatch, tmp_path):
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")


def test_compute_stage_elapsed_seconds_wall_clock() -> None:
    assert (
        compute_stage_elapsed_seconds("2026-06-05T10:00:00", end_at="2026-06-05T10:05:30") == 330
    )


def test_compute_node_metrics_seconds_wall_clock() -> None:
    assert (
        compute_node_metrics_seconds("2026-06-05T10:00:00", "2026-06-05T10:05:30") == 330
    )


def test_resolve_node_seconds_from_timestamps_not_stored_seconds() -> None:
    """展示耗时只认 completed_at − started_at，忽略 node_metrics.seconds 占位。"""
    nm_completed = {
        "started_at": "2026-06-05T10:00:00",
        "completed_at": "2026-06-05T10:02:00",
        "seconds": 9999,
    }
    assert resolve_node_seconds(nm_completed) == 120

    nm_processing = {
        "started_at": "2026-06-05T10:00:00",
        "seconds": 9999,
    }
    assert resolve_node_seconds(nm_processing, node_status="processing") == compute_stage_elapsed_seconds(
        "2026-06-05T10:00:00"
    )


def test_build_meeting_summary_nodes_deal_seconds_from_timestamps() -> None:
    scope_id = "nm_summary_seconds"
    node_id = "boundary"
    rs = default_room_state(
        room_id="room-sec",
        scope_type="demand",
        scope_id=scope_id,
        stage_id=1,
        current_node_id=node_id,
    )
    rs["node_metrics"] = {
        node_id: {
            "started_at": "2026-06-05T10:00:00",
            "completed_at": "2026-06-05T10:03:30",
            "seconds": 60,
            "tokens": 100,
        }
    }
    nodes = build_meeting_summary_nodes(None, rs, scope_id=scope_id)
    boundary = next(n for n in nodes if n["node_id"] == node_id)
    assert boundary["metrics"]["deal_seconds"] == 210


def test_finalize_node_metrics_activity_tokens_and_completed_at() -> None:
    scope_id = "nm_archive_01"
    node_id = "boundary"

    _write_activity(
        scope_id,
        node_id,
        "default",
        [{"seq": 1, "ts": "2026-06-05T10:01:00", "category": "llm_usage", "total_tokens": 1200}],
    )
    _write_activity(
        scope_id,
        node_id,
        "worker-a",
        [{"seq": 1, "ts": "2026-06-05T10:01:30", "category": "llm_usage", "total_tokens": 800}],
    )

    assert aggregate_node_activity_tokens(scope_id, node_id) == 2000

    room_state = default_room_state(
        room_id="room-nm",
        scope_type="demand",
        scope_id=scope_id,
        stage_id=1,
        current_node_id=node_id,
    )
    room_state["node_metrics"] = {
        node_id: {"started_at": "2026-06-05T10:00:00", "seconds": 0, "tokens": 0},
    }

    entry = finalize_node_metrics(
        room_state,
        scope_id=scope_id,
        node_id=node_id,
        completed_at="2026-06-05T10:02:00",
    )
    assert entry["completed_at"] == "2026-06-05T10:02:00"
    assert entry["seconds"] == 120
    assert entry["tokens"] == 2000
    assert room_state["node_metrics"][node_id]["tokens"] == 2000


def test_aggregate_room_activity_tokens_sums_all_nodes() -> None:
    scope_id = "nm_room_total"
    _write_activity(
        scope_id,
        "boundary",
        "default",
        [{"seq": 1, "ts": "2026-06-05T10:01:00", "category": "llm_usage", "total_tokens": 1200}],
    )
    _write_activity(
        scope_id,
        "req_clarify",
        "default",
        [{"seq": 1, "ts": "2026-06-05T10:02:00", "category": "llm_usage", "total_tokens": 800}],
    )
    assert aggregate_room_activity_tokens(scope_id) == 2000


def test_refresh_node_metrics_writes_node_tokens() -> None:
    scope_id = "nm_refresh_01"
    node_id = "boundary"
    _write_activity(
        scope_id,
        node_id,
        "default",
        [{"seq": 1, "ts": "2026-06-05T10:01:00", "category": "llm_usage", "total_tokens": 3000}],
    )
    rs = default_room_state(
        room_id="room-refresh",
        scope_type="demand",
        scope_id=scope_id,
        stage_id=1,
        current_node_id=node_id,
    )
    save_room_state(scope_id, rs)

    tokens = refresh_node_metrics(scope_id, node_id)
    assert tokens == 3000
    after = load_room_state(scope_id)
    assert after is not None
    assert int(after["node_metrics"][node_id]["tokens"]) == 3000
    assert DEFAULT_TOKEN_BUDGET == 20_000_000
    assert DEFAULT_NODE_TOKEN_BUDGET == 3_000_000


def test_build_meeting_summary_nodes_prefers_activity_over_legacy_256() -> None:
    scope_id = "nm_summary_legacy"
    node_id = "boundary"

    _write_activity(
        scope_id,
        node_id,
        "default",
        [{"seq": 1, "ts": "2026-06-05T10:01:00", "category": "llm_usage", "total_tokens": 4200}],
    )

    rs = default_room_state(
        room_id="room-legacy",
        scope_type="demand",
        scope_id=scope_id,
        stage_id=1,
        current_node_id=node_id,
    )
    rs["node_metrics"] = {
        node_id: {
            "started_at": "2026-06-05T10:00:00",
            "completed_at": "2026-06-05T10:02:00",
            "seconds": 120,
            "tokens": 256,
        }
    }
    save_room_state(scope_id, rs)

    nodes = build_meeting_summary_nodes(None, rs, scope_id=scope_id)
    boundary = next(n for n in nodes if n["node_id"] == node_id)
    assert boundary["metrics"]["tokens"] == 4200


def test_build_meeting_summary_nodes_drops_legacy_256_without_activity() -> None:
    scope_id = "nm_summary_zero"
    node_id = "boundary"

    rs = default_room_state(
        room_id="room-zero",
        scope_type="demand",
        scope_id=scope_id,
        stage_id=1,
        current_node_id=node_id,
    )
    rs["node_metrics"] = {
        node_id: {
            "started_at": "2026-06-05T10:00:00",
            "completed_at": "2026-06-05T10:02:00",
            "seconds": 120,
            "tokens": 256,
        }
    }
    save_room_state(scope_id, rs)

    nodes = build_meeting_summary_nodes(None, rs, scope_id=scope_id)
    boundary = next(n for n in nodes if n["node_id"] == node_id)
    assert boundary["metrics"]["tokens"] == 0


def test_mark_human_gate_exception_finalizes_node_metrics() -> None:
    from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator

    scope_id = "nm_exc_01"
    node_id = "boundary"

    dev = load_dev_status(scope_id) or {
        "scope_type": "demand",
        "scope_id": scope_id,
        "stage_id": 1,
        "current_node_id": node_id,
        "local_process_state": "处理中",
    }
    dev["current_node_id"] = node_id
    save_dev_status(scope_id, dev)

    rs = default_room_state(
        room_id="room-exc",
        scope_type="demand",
        scope_id=scope_id,
        stage_id=1,
        current_node_id=node_id,
        status="processing",
    )
    rs["node_metrics"] = {node_id: {"started_at": "2026-06-05T11:00:00", "seconds": 0, "tokens": 0}}
    save_room_state(scope_id, rs)

    _write_activity(
        scope_id,
        node_id,
        "default",
        [{"seq": 1, "ts": "2026-06-05T11:01:00", "category": "llm_usage", "total_tokens": 500}],
    )

    orch = MeetingRoomOrchestrator()
    orch.mark_human_gate(
        scope_type="demand",
        scope_id=scope_id,
        room_id="room-exc",
        node_id=node_id,
        intervention_kind="exception",
    )

    after = load_room_state(scope_id)
    assert after is not None
    nm = after["node_metrics"][node_id]
    assert nm.get("completed_at")
    assert int(nm.get("tokens") or 0) == 500
    assert int(nm.get("seconds") or 0) >= 1
