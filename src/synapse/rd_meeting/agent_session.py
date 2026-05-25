"""研发会议室 host Agent 会话绑定（委派工具需要 Session 对象）。"""

from __future__ import annotations

from typing import Any

from synapse.sessions.session import Session, SessionContext, SessionState


def host_session_id(room_id: str) -> str:
    return f"rd_meeting:{(room_id or '').strip()}:host"


def resolve_meeting_orchestrator(agent_pool: Any | None = None) -> Any | None:
    """解析全局 AgentOrchestrator（委派子任务状态 / metrics 聚合用）。

    ``AgentInstancePool`` 本身不带 ``orchestrator`` 属性；实际实例在 ``synapse.main._orchestrator``。
    """
    try:
        from synapse.main import _orchestrator

        if _orchestrator is not None:
            return _orchestrator
    except (ImportError, AttributeError):
        pass
    if agent_pool is not None:
        return getattr(agent_pool, "orchestrator", None)
    return None


def ensure_host_session(room_id: str, host_profile_id: str) -> Session:
    """构造与 agent pool key 一致的 host Session（内存对象，供委派链路使用）。"""
    sid = host_session_id(room_id)
    ctx = SessionContext(agent_profile_id=(host_profile_id or "default").strip() or "default")
    return Session(
        id=sid,
        channel="rd_meeting",
        chat_id=(room_id or "").strip(),
        user_id="meeting_room",
        state=SessionState.ACTIVE,
        context=ctx,
        metadata={"room_id": room_id, "role": "host"},
    )


def bind_meeting_agent_session(agent: Any, session: Session) -> None:
    """在执行 host 任务前绑定会话，使 delegate_* / submit_meeting_work_plan 可用。"""
    agent._current_session = session
    agent._current_session_id = session.id
    if getattr(agent, "agent_state", None) is not None:
        agent.agent_state.current_session = session
    try:
        from synapse.logging import get_session_log_buffer

        get_session_log_buffer().set_current_session(session.id)
    except Exception:
        pass


def clear_meeting_agent_session(agent: Any) -> None:
    """任务结束后清理，避免池化 Agent 残留会话指针 / 会议室提示词短路标记。"""
    agent._current_session = None
    if getattr(agent, "agent_state", None) is not None:
        agent.agent_state.current_session = None
    try:
        agent._org_context = False  # 复位会议室短路开关，允许复用时回到通用编译管线
    except Exception:
        pass
