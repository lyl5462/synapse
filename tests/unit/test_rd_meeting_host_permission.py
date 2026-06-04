"""会议室 Host 委派工具权限自动放行。"""

from __future__ import annotations

from unittest.mock import MagicMock

from synapse.core.tool_executor import ToolExecutor
from synapse.rd_meeting.agent_session import ensure_host_session
from synapse.tools.handlers import SystemHandlerRegistry


def test_rd_meeting_host_bypasses_delegate_confirm() -> None:
    reg = SystemHandlerRegistry()
    executor = ToolExecutor(reg)
    agent = MagicMock()
    agent._org_context = True
    session = ensure_host_session("room-perm", "default")
    agent._current_session = session
    agent._current_session_id = session.id
    executor._agent_ref = agent

    decision = executor.check_permission(
        "delegate_to_agent",
        {"agent_id": "worker-a", "message": "task"},
    )
    assert decision.behavior == "allow"
    assert decision.policy_name == "rd_meeting"


def test_rd_meeting_bypasses_run_shell() -> None:
    reg = SystemHandlerRegistry()
    executor = ToolExecutor(reg)
    agent = MagicMock()
    agent._org_context = True
    session = ensure_host_session("room-shell", "default")
    agent._current_session = session
    agent._current_session_id = session.id
    executor._agent_ref = agent

    decision = executor.check_permission(
        "run_shell",
        {"command": "mkdir foo", "description": "test"},
    )
    assert decision.behavior == "allow"
    assert decision.policy_name == "rd_meeting"


def test_non_meeting_session_still_uses_policy() -> None:
    reg = SystemHandlerRegistry()
    executor = ToolExecutor(reg)
    agent = MagicMock()
    agent._org_context = True
    agent._current_session = None
    agent._current_session_id = "desktop:abc"
    executor._agent_ref = agent

    decision = executor.check_permission(
        "delegate_to_agent",
        {"agent_id": "worker-a", "message": "task"},
    )
    assert decision.behavior != "allow" or decision.policy_name != "rd_meeting"
