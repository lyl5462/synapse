"""主控提示词组装与协作会议流展示。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.host_prompt import assemble_host_prompt_bundle, format_host_prompt_markdown
from synapse.rd_meeting.pipeline_chat import format_event_chat_display, format_room_opened_chat
from synapse.rd_meeting.room_runtime import history_to_chat_logs


@pytest.fixture
def host_binding() -> dict:
    return {
        "node_id": "req_clarify",
        "node_name": "需求澄清",
        "stage_id": 1,
        "stage_name": "需求分析",
        "type": "ai_human",
        "enabled": True,
        "human_confirm": True,
        "node_intent": "澄清需求边界与验收标准。",
        "host_profile_id": "default",
        "worker_profile_ids": ["whalecloud-requirement-expert"],
        "host_llm_endpoint_key": "reasoning-heavy",
        "worker_llm_endpoint_key": "worker-default",
        "meeting_skill_id": "whalecloud-dev-tool-meeting-room",
        "prompt_supplement": "",
    }


def test_assemble_host_prompt_bundle_has_system_and_user(host_binding, monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_code": "ok", "prod": "myprod", "repos": [], "docs": []},
            {"synapse_url": "http://127.0.0.1:10001", "gitnexus_url": "http://127.0.0.1:11011"},
        ),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync._scope_row",
        lambda *_a, **_k: {
            "demand_no": "D1",
            "demand_title": "标题",
            "demand_desc": "说明",
            "prod": "myprod",
        },
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync.load_scope_work_order_context",
        lambda *_a, **_k: {"demand_no": "D1", "demand_title": "标题", "prod": "myprod"},
    )

    bundle = assemble_host_prompt_bundle(
        scope_type="demand",
        scope_id="D1",
        node_id="req_clarify",
        binding=host_binding,
        ticket_title="标题",
    )
    assert len(bundle["dynamic_context"]) > 100
    assert "## 一、本 SOP 环节工作信息" in bundle["dynamic_context"]
    assert "## 二、工单信息" in bundle["dynamic_context"]
    assert "(4) **协作智能体**" in bundle["dynamic_context"]
    assert len(bundle["meeting_prompt"]) > 200
    assert "submit_meeting_work_plan" in bundle["user_prompt"]
    md = format_host_prompt_markdown(bundle)
    assert "【步骤 3/3】" in md
    assert "DYNAMIC_MEETING_CONTEXT" in md or "## 一、本 SOP 环节工作信息" in md


def test_chat_display_three_pipeline_steps():
    opened = format_room_opened_chat(
        room_id="room-1",
        scope_id="D1",
        userwork_updates={"sop_node": "需求澄清", "local_process_state": "处理中", "prod": "myprod"},
        current_node_id="req_clarify",
        sop_display="需求澄清",
    )
    assert "【步骤 1/3】" in opened

    ev_open = {
        "event": "room_opened",
        "room_id": "room-1",
        "scope_id": "D1",
        "text": json.dumps(
            {"sop_node": "需求澄清", "local_process_state": "处理中", "prod": "myprod"},
            ensure_ascii=False,
        ),
        "chat_text": opened,
        "agent_id": "system",
        "ts": "2026-05-21T10:00:00",
    }
    logs = history_to_chat_logs([ev_open])
    assert len(logs) == 1
    assert "【步骤 1/3】" in logs[0]["text"]
    assert logs[0].get("rich") is True

    host_md = "【步骤 3/3】主控智能体（小鲸）提示词已组装\n\n## 一、会议节点"
    ev_host = {
        "event": "host_prompt_assembled",
        "text": host_md,
        "chat_text": host_md,
        "agent_id": "default",
        "ts": "2026-05-21T10:00:02",
    }
    assert "【步骤 3/3】" in format_event_chat_display(ev_host)
    logs2 = history_to_chat_logs([ev_open, ev_host])
    assert len(logs2) == 2
    assert logs2[1]["agentId"] == "default"
