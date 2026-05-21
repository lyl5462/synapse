"""会议室节点启动：初始化上下文写入协作会议流（JSON 流程日志）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.init_context import format_node_init_log
from synapse.rd_meeting.participants import build_meeting_participants
from synapse.rd_meeting.room_runtime import append_history_event

ScopeType = Literal["demand", "task"]


def build_node_init_message(
    binding: dict[str, Any],
    *,
    node_id: str,
    scope_type: ScopeType = "demand",
    scope_id: str = "",
) -> str:
    """节点初始化 JSON 日志（写入 history ``text``）。"""
    sid = (scope_id or str(binding.get("scope_id") or "")).strip()
    st = scope_type or str(binding.get("scope_type") or "demand")
    return format_node_init_log(st, sid, node_id=node_id)


def append_node_init_chat(
    scope_id: str,
    *,
    room_id: str,
    node_id: str,
    binding: dict[str, Any],
    scope_type: ScopeType = "demand",
) -> str:
    """将节点初始化上下文追加到 room_history。"""
    text = format_node_init_log(scope_type, scope_id, node_id=node_id)
    host_id = str(binding.get("host_profile_id") or "default")
    participants = build_meeting_participants(binding)
    append_history_event(
        scope_id,
        {
            "event": "node_init",
            "room_id": room_id,
            "node_id": node_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "text": text,
            "agent_id": host_id,
            "log_type": "info",
            "participants": participants,
            "flow_stage": "节点初始化",
        },
    )
    return text
