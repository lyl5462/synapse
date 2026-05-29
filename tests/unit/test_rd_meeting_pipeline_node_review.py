"""pipeline.run_node_review_step：flow_step 切换 + 落盘。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.paths import meeting_pipeline_path, scope_dir
from synapse.rd_meeting.pipeline import (
    STEP_NODE_REVIEW,
    STEP_WAITING,
    MeetingPipeline,
    run_node_review_step,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    monkeypatch.setattr("synapse.rd_meeting.room_skill.resolve_agent_profile", lambda pid: None)
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda sid, node_id="pending": scope_dir(sid) / "room_history.jsonl",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_run_node_review_step_writes_payload_and_marks_waiting(tmp_path):
    scope = "scope-R"
    node_id = "req_clarify"
    # 预创建 pipeline.json
    MeetingPipeline.create(scope, scope_type="demand")

    payload = await run_node_review_step(
        scope_type="demand",
        scope_id=scope,
        room_id="room-R",
        node_id=node_id,
        binding={
            "host_profile_id": "default",
            "worker_profile_ids": [],
            "node_name": "需求澄清",
            "node_intent": "把需求拆清楚",
        },
        report_body="# 交付结论\nDone",
        tokens_used=100,
        duration_seconds=10,
        stage_id=2,
        agent_pool=None,
        orchestrator=None,
        use_llm_summary=False,
    )

    assert payload["node_id"] == node_id
    # pipeline.json 已落 node_review[node_id]
    raw = json.loads(meeting_pipeline_path(scope).read_text("utf-8"))
    assert raw["context"]["node_review"][node_id]["node_id"] == node_id
    # flow_step 推回 waiting
    assert raw["flow_step"] == STEP_WAITING
    # NODE_REVIEW 已写入 steps_completed
    assert STEP_NODE_REVIEW in raw["steps_completed"]
