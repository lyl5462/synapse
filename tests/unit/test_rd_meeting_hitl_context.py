"""hitl_context.json 机器台账：写入与合并。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.hitl_context import (
    HITL_CONTEXT_FILENAME,
    append_hitl_context_round,
    hitl_context_path,
    read_hitl_context,
)
from synapse.rd_meeting.hitl_feedback import build_hitl_round_record


@pytest.fixture
def synapse_work_home(monkeypatch: pytest.MonkeyPatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: work)
    return work


def _round(values: dict, *, kind: str = "interactive") -> dict:
    return build_hitl_round_record(
        values,
        {"questions": [{"id": "q1", "type": "text", "title": "问题1"}]},
        intervention_kind=kind,
        feedback_mode="options_only",
    )


def test_append_hitl_context_only_interactive(synapse_work_home):
    scope_id = "21884001"
    node_id = "req_clarify"
    r1 = _round({"q1": "答案A"})
    p1 = append_hitl_context_round(scope_id, node_id, r1, stage_name="需求分析")
    assert p1 is not None
    assert p1.name == HITL_CONTEXT_FILENAME

    r2 = _round({"q1": "答案B"}, kind="exception")
    p2 = append_hitl_context_round(scope_id, node_id, r2, stage_name="需求分析")
    assert p2 is None

    doc = read_hitl_context(scope_id, node_id, stage_name="需求分析")
    assert len(doc["rounds"]) == 1
    assert doc["confirmed_by_id"]["q1"]["user_input"] == "答案A"


def test_append_hitl_context_merges_rounds(synapse_work_home):
    scope_id = "21884002"
    node_id = "req_clarify"
    append_hitl_context_round(
        scope_id,
        node_id,
        _round({"q1": "第一轮"}),
        stage_name="需求分析",
    )
    append_hitl_context_round(
        scope_id,
        node_id,
        _round({"q1": "第二轮"}),
        stage_name="需求分析",
    )
    doc = read_hitl_context(scope_id, node_id, stage_name="需求分析")
    assert len(doc["rounds"]) == 2
    assert doc["rounds"][0]["round"] == 1
    assert doc["rounds"][1]["round"] == 2
    assert doc["confirmed_by_id"]["q1"]["user_input"] == "第二轮"

    path = hitl_context_path(scope_id, "需求分析", node_id)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["scope_id"] == scope_id
