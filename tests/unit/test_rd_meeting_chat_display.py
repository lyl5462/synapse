"""协作会议流结构化展示."""

from __future__ import annotations

from synapse.rd_meeting.chat_display import expand_history_event_to_chat
from synapse.rd_meeting.room_runtime import history_to_chat_logs


def test_node_init_context_pipeline_then_participants() -> None:
    ev = {
        "event": "node_init",
        "room_id": "mr_d_1",
        "node_id": "req_clarify",
        "agent_id": "default",
        "text": '{"order":{"id":"1","title":"T"},"product":{"prod":"P"},"system":{}}',
        "chat_text": "节点初始化\n\n已加载上下文。",
        "binding": {"host_profile_id": "default", "worker_profile_ids": ["w1"]},
        "participants": [
            {"profile_id": "default", "role": "host", "display_name": "小鲸"},
            {"profile_id": "w1", "role": "worker", "display_name": "专家A"},
        ],
        "ts": "2026-05-21T10:00:00",
    }
    rows = expand_history_event_to_chat(ev, 0)
    kinds = [r["displayKind"] for r in rows]
    assert kinds == ["node_context", "pipeline", "participants"]
    assert rows[-1]["text"] == "参会人员名单"
    assert rows[-1]["speakerRole"] == "system"


def test_node_started_emits_no_chat_rows() -> None:
    ev = {
        "event": "node_started",
        "room_id": "mr_d_1",
        "node_id": "req_clarify",
        "agent_id": "default",
        "text": '{"order":{"id":"1","title":"T"},"product":{"prod":"P"},"system":{}}',
        "binding": {"host_profile_id": "default", "worker_profile_ids": ["w1"]},
        "participants": [
            {"profile_id": "default", "role": "host", "display_name": "小鲸"},
            {"profile_id": "w1", "role": "worker", "display_name": "专家A"},
        ],
        "ts": "2026-05-21T10:00:01",
    }
    assert expand_history_event_to_chat(ev, 1) == []


def test_prewarm_workers_skipped() -> None:
    assert history_to_chat_logs(
        [
            {
                "event": "prewarm_workers",
                "room_id": "mr_d_1",
                "node_id": "req_clarify",
                "worker_profile_ids": ["w1"],
                "agent_id": "default",
                "ts": "2026-05-21T10:00:02",
            }
        ]
    ) == []


def test_work_plan_host_and_unwrap_json_message() -> None:
    rows = expand_history_event_to_chat(
        {
            "event": "work_plan_submitted",
            "text": '{"message":"# 工作安排计划\\n\\n**目标**：澄清"}',
            "agent_id": "default",
            "ts": "2026-05-21T10:01:00",
        },
        2,
    )
    assert len(rows) == 1
    assert rows[0]["speakerRole"] == "host"
    assert rows[0]["displayKind"] == "work_plan"
    assert rows[0]["text"].startswith("# 工作安排计划")


def test_host_llm_begin_is_host() -> None:
    rows = expand_history_event_to_chat(
        {
            "event": "host_llm_begin",
            "agent_id": "default",
            "reused_host_prompt_cache": False,
            "ts": "2026-05-21T10:02:00",
        },
        3,
    )
    assert rows[0]["speakerRole"] == "host"
    assert rows[0]["agentId"] == "default"


def test_hitl_dynamic_is_host() -> None:
    rows = expand_history_event_to_chat(
        {
            "event": "hitl_dynamic",
            "detail": "主控通过工具提交问卷 kind=interactive questions=22",
            "agent_id": "default",
            "source": "tool",
            "ts": "2026-05-21T11:00:00",
        },
        4,
    )
    assert rows[0]["speakerRole"] == "host"


def test_node_pending_confirm_waiting_feedback() -> None:
    rows = expand_history_event_to_chat(
        {
            "event": "node_pending_confirm",
            "duration_seconds": 964,
            "dynamic_form": True,
            "agent_id": "default",
            "ts": "2026-05-21T11:01:00",
        },
        5,
    )
    assert rows[0]["speakerRole"] == "host"
    assert "等待问卷反馈" in rows[0]["text"]


def test_delegation_roles() -> None:
    start = expand_history_event_to_chat(
        {
            "event": "delegation_started",
            "text": "小鲸 → 专家：已委派协作（原因）\n任务：做某事\n计划项：t1",
            "agent_id": "default",
            "to_agent": "w1",
            "plan_item_id": "t1",
            "ts": "2026-05-21T10:02:00",
        },
        6,
    )[0]
    assert start["speakerRole"] == "host"

    done = expand_history_event_to_chat(
        {
            "event": "delegation_finished",
            "text": "专家 completed · 120s：摘要",
            "to_agent": "w1",
            "ok": True,
            "ts": "2026-05-21T10:10:00",
        },
        7,
    )[0]
    assert done["speakerRole"] == "worker"
