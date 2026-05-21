"""研发会议室工作安排计划单测。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.room_runtime import history_to_chat_logs
from synapse.rd_meeting.work_plan import (
    check_delegation_allowed,
    clear_work_plan,
    mark_delegation_started,
    submit_work_plan,
)


@pytest.fixture
def meeting_scope(tmp_path, monkeypatch):
    scope_id = "plan-scope"
    work = tmp_path / scope_id
    work.mkdir(parents=True)
    dev_path = work / "dev.status"
    dev_path.write_text(
        json.dumps(
            {
                "meeting_room": {"room_id": "room-plan", "active": True},
                "current_node_id": "req_clarify",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state_path = work / "room_state.json"
    state_path.write_text("{}", encoding="utf-8")
    history_path = work / "room_history.jsonl"
    history_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "synapse.rd_meeting.live.scope_id_for_room_id",
        lambda rid: scope_id if rid == "room-plan" else None,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.paths.scope_dir",
        lambda s: work if s == scope_id else tmp_path / s,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_state_path",
        lambda s: work / "room_state.json",
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda s: work / "room_history.jsonl",
    )

    binding = {
        "host_profile_id": "default",
        "worker_profile_ids": ["worker-a", "worker-b"],
        "node_id": "req_clarify",
    }
    monkeypatch.setattr(
        "synapse.rd_meeting.work_plan.scope_id_for_room_id",
        lambda rid: scope_id if rid == "room-plan" else None,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.work_plan.resolve_node_binding",
        lambda *a, **k: binding,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.work_plan.load_dev_status",
        lambda sid: {"current_node_id": "req_clarify"},
    )
    return scope_id


def test_check_delegation_blocked_without_plan(meeting_scope: str) -> None:
    err = check_delegation_allowed("rd_meeting:room-plan:host", agent_id="worker-a")
    assert err is not None
    assert "submit_meeting_work_plan" in err


def test_check_delegation_ignored_outside_meeting() -> None:
    assert check_delegation_allowed("desktop:abc", agent_id="worker-a") is None


def test_submit_and_delegate_gate(meeting_scope: str) -> None:
    session = "rd_meeting:room-plan:host"
    assert check_delegation_allowed(session, agent_id="worker-a") is not None

    plan = submit_work_plan(
        session_id=session,
        goal_summary="澄清需求边界",
        items=[
            {
                "id": "t1",
                "agent_id": "worker-a",
                "task": "列出澄清问题",
                "reason": "需求专家",
            }
        ],
    )
    assert plan["type"] == "meeting_work_plan"
    assert len(plan["items"]) == 1

    assert check_delegation_allowed(session, agent_id="worker-a", plan_item_id="t1") is None
    assert check_delegation_allowed(session, agent_id="worker-c") is not None

    mark_delegation_started(session, agent_id="worker-a", plan_item_id="t1")
    with pytest.raises(ValueError, match="已开始委派"):
        submit_work_plan(
            session_id=session,
            goal_summary="改计划",
            items=[
                {
                    "agent_id": "worker-a",
                    "task": "x",
                    "reason": "y",
                }
            ],
        )


def test_history_includes_work_plan_event() -> None:
    logs = history_to_chat_logs(
        [
            {
                "event": "work_plan_submitted",
                "text": "# 工作安排计划\n\n**任务分配**：",
                "agent_id": "default",
                "ts": "2026-05-21T10:00:00",
            }
        ]
    )
    assert len(logs) == 1
    assert "工作安排" in logs[0]["text"]


def test_clear_work_plan(meeting_scope: str, monkeypatch: pytest.MonkeyPatch) -> None:
    session = "rd_meeting:room-plan:host"
    submit_work_plan(
        session_id=session,
        goal_summary="g",
        items=[{"agent_id": "worker-a", "task": "t", "reason": "r"}],
    )
    clear_work_plan(meeting_scope)
    assert check_delegation_allowed(session, agent_id="worker-a") is not None
