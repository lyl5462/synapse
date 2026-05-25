"""会议室 Agent 提示词绑定：确保池化实例使用 meeting prompt，不回落到通用 build_system_prompt（含 AGENTS.md）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.live import parse_rd_meeting_session, scope_id_for_room_id
from synapse.rd_meeting.paths import scope_dir

logger = logging.getLogger(__name__)

MEETING_PROMPT_MARKER = "# 你是 Synapse 研发会议室参会智能体"


def _refresh_meeting_activity_binding(
    agent: Any,
    *,
    scope_id: str,
    node_id: str,
    room_id: str,
    agent_profile_id: str,
    depth: int,
    binding: dict[str, Any],
) -> None:
    try:
        from synapse.rd_meeting.agent_activity import set_agent_activity_binding

        host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
        role: Literal["host", "worker"] = "worker" if depth > 0 else "host"
        pid = agent_profile_id if depth > 0 else host_id
        set_agent_activity_binding(
            agent,
            scope_id=scope_id,
            node_id=node_id,
            profile_id=pid,
            host_profile_id=host_id,
            role=role,
            room_id=room_id,
        )
    except Exception as exc:
        logger.debug("refresh meeting activity binding failed: %s", exc)


def is_meeting_room_system_prompt(text: str) -> bool:
    return MEETING_PROMPT_MARKER in (text or "")


def is_meeting_agent_configured(agent: Any) -> bool:
    """Agent 是否已绑定会议室专用 system prompt（且已开启短路标记）。"""
    if not getattr(agent, "_org_context", None):
        return False
    ctx = getattr(agent, "_context", None)
    system = str(getattr(ctx, "system", "") or "")
    return is_meeting_room_system_prompt(system)


def resolve_rd_meeting_pool_session_id(
    session_id: str,
    agent_profile_id: str,
    *,
    depth: int = 0,
) -> str:
    """研发会议室委派时，Worker 应使用 ``rd_meeting:{room}:{profile}`` 池化键（与 prewarm 一致）。"""
    parsed = parse_rd_meeting_session(session_id)
    if not parsed or parsed.get("role") != "host" or depth <= 0:
        return session_id
    room_id = str(parsed.get("room_id") or "").strip()
    pid = (agent_profile_id or "").strip()
    if not room_id or not pid:
        return session_id
    return f"rd_meeting:{room_id}:{pid}"


def ensure_meeting_agent_configured(
    agent: Any,
    *,
    session_id: str,
    agent_profile_id: str,
    depth: int = 0,
) -> bool:
    """若池化 Agent 尚未注入会议室 prompt，则按当前节点 binding 补配。

    Returns:
        是否属于研发会议室上下文（无论是否本次新配置）。
    """
    parsed = parse_rd_meeting_session(session_id)
    if not parsed:
        return False

    room_id = str(parsed.get("room_id") or "").strip()
    scope_id = scope_id_for_room_id(room_id) if room_id else None
    if not scope_id:
        return True

    dev = load_dev_status(scope_id) or {}
    node_id = str(dev.get("current_node_id") or "").strip()
    if not node_id:
        logger.debug("ensure_meeting_agent_configured: no current_node_id for %s", scope_id)
        return True

    scope_type = str(dev.get("scope_type") or "demand")
    ticket_title = str(dev.get("ticket_title") or dev.get("demand_title") or "")

    binding = resolve_node_binding(
        node_id,
        scope_type=scope_type,  # type: ignore[arg-type]
        scope_id=scope_id,
        ticket_title=ticket_title,
    )
    binding["node_id"] = node_id

    if is_meeting_agent_configured(agent):
        _refresh_meeting_activity_binding(
            agent,
            scope_id=scope_id,
            node_id=node_id,
            room_id=room_id,
            agent_profile_id=agent_profile_id,
            depth=depth,
            binding=binding,
        )
        return True

    if depth > 0:
        role: Literal["host", "worker"] = "worker"
        self_profile_id = agent_profile_id
    else:
        role = "host"
        self_profile_id = ""

    from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator

    MeetingRoomOrchestrator._configure_meeting_agent(
        agent,
        role=role,
        binding=binding,
        scope_type=scope_type,
        scope_id=scope_id,
        ticket_title=ticket_title,
        scope_path=str(scope_dir(scope_id)),
        self_profile_id=self_profile_id,
    )
    _refresh_meeting_activity_binding(
        agent,
        scope_id=scope_id,
        node_id=node_id,
        room_id=room_id,
        agent_profile_id=agent_profile_id,
        depth=depth,
        binding=binding,
    )
    logger.info(
        "Configured meeting prompt for %s role=%s profile=%s scope=%s node=%s",
        session_id,
        role,
        agent_profile_id,
        scope_id,
        node_id,
    )
    return True
