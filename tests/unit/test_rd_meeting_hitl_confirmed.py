"""人机交互清单.md 人类台账：写入（不注入 prompt）。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.hitl_confirmed import (
    HITL_CONFIRMED_FILENAME,
    append_hitl_confirmed,
    hitl_confirmed_path,
    read_hitl_confirmed,
    split_hitl_confirmed_rounds,
)
from synapse.rd_meeting.hitl_feedback import format_hitl_current_round_prompt
from synapse.rd_meeting.user_context import (
    append_user_context_pending,
    drain_user_context_for_prompt,
)


@pytest.fixture
def synapse_work_home(monkeypatch: pytest.MonkeyPatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: work)
    return work


def test_append_hitl_confirmed_creates_and_appends_rounds(synapse_work_home):
    scope_id = "21883520"
    node_id = "req_clarify"
    body1 = "[人工确认表单]\n\n## 用户问卷反馈\n\n**反馈模式**：仅选项"
    body2 = "[人工确认表单]\n\n## 用户问卷反馈\n\n**反馈模式**：含自由输入"

    p1 = append_hitl_confirmed(scope_id, node_id, body1, intervention_kind="interactive")
    assert p1 is not None
    assert p1.name == HITL_CONFIRMED_FILENAME
    assert "第 1 轮" in p1.read_text(encoding="utf-8")

    p2 = append_hitl_confirmed(scope_id, node_id, body2, intervention_kind="interactive")
    assert p2 == p1
    text = p2.read_text(encoding="utf-8")
    assert "第 1 轮" in text
    assert "第 2 轮" in text
    assert "人机交互清单" in text


def test_split_hitl_confirmed_rounds():
    single = "# 标题\n\n## 第 1 轮 · interactive · t\n\nround1"
    prior, latest = split_hitl_confirmed_rounds(single)
    assert prior == ""
    assert "第 1 轮" in latest

    multi = (
        "# 标题\n\n## 第 1 轮 · interactive · t1\n\nround1\n\n"
        "## 第 2 轮 · interactive · t2\n\nround2"
    )
    prior2, latest2 = split_hitl_confirmed_rounds(multi)
    assert "第 1 轮" in prior2
    assert "第 2 轮" not in prior2
    assert "第 2 轮" in latest2


def test_pending_injects_current_round_json_only(synapse_work_home):
    """与 orchestrator 一致：仅 pending 注入本轮 JSON，不读累积 md。"""
    scope_id = "21883522"
    pending_block = format_hitl_current_round_prompt(
        {
            "intervention_kind": "interactive",
            "feedback_mode": "options_only",
            "questions": [{"id": "q1", "title": "Q", "user_input": "x"}],
        }
    )
    append_user_context_pending(scope_id, pending_block)
    drained = drain_user_context_for_prompt(scope_id)
    assert "本轮人工确认反馈（结构化）" in drained
    assert '"current_round"' in drained
    assert "hitl_context.json" in drained


def test_hitl_confirmed_path_uses_stage_name(synapse_work_home):
    scope_id = "21883523"
    node_id = "req_clarify"
    path = hitl_confirmed_path(scope_id, "需求分析", node_id)
    assert path.as_posix().endswith("archive/需求分析/req_clarify/人机交互清单.md")
    append_hitl_confirmed(scope_id, node_id, "x", stage_name="需求分析")
    assert read_hitl_confirmed(scope_id, node_id, stage_name="需求分析") != ""
