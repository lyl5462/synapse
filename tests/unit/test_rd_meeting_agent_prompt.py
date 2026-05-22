"""会议室 Agent 提示词绑定（跳过 AGENTS.md）。"""

from __future__ import annotations

from unittest.mock import MagicMock

from synapse.rd_meeting.agent_prompt import (
    MEETING_PROMPT_MARKER,
    is_meeting_agent_configured,
    is_meeting_room_system_prompt,
    resolve_rd_meeting_pool_session_id,
)


def test_is_meeting_room_system_prompt():
    assert is_meeting_room_system_prompt(f"{MEETING_PROMPT_MARKER}\n\n- **当前角色**")
    assert not is_meeting_room_system_prompt("## Project Guidelines (AGENTS.md)")


def test_is_meeting_agent_configured():
    agent = MagicMock()
    agent._org_context = True
    agent._context.system = f"{MEETING_PROMPT_MARKER}\n"
    assert is_meeting_agent_configured(agent)

    agent._org_context = False
    assert not is_meeting_agent_configured(agent)


def test_resolve_rd_meeting_pool_session_id_for_worker_delegation():
    host_sid = "rd_meeting:room-abc:host"
    assert resolve_rd_meeting_pool_session_id(host_sid, "whalecloud-design-expert", depth=1) == (
        "rd_meeting:room-abc:whalecloud-design-expert"
    )
    assert resolve_rd_meeting_pool_session_id(host_sid, "default", depth=0) == host_sid
    assert resolve_rd_meeting_pool_session_id("desktop:abc", "default", depth=1) == "desktop:abc"
