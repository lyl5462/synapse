"""会议室节点启动：初始化上下文写入协作会议流（JSON 流程日志）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.host_prompt import (
    assemble_host_prompt_bundle,
    format_host_prompt_chat_display,
    format_host_prompt_snapshot,
)
from synapse.rd_meeting.host_prompt_cache import clear_host_prompt_cache
from synapse.rd_meeting.init_context import format_node_init_log
from synapse.rd_meeting.participants import build_meeting_participants, build_system_participants
from synapse.rd_meeting.pipeline_chat import format_node_init_chat, format_system_node_init_chat
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
    clear_host_prompt_cache(scope_id)
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
            "chat_text": format_node_init_chat(),
            "agent_id": host_id,
            "log_type": "info",
            "binding": {
                "host_profile_id": host_id,
                "worker_profile_ids": list(binding.get("worker_profile_ids") or []),
            },
            "participants": participants,
            "flow_stage": "节点初始化",
        },
    )
    return text


def append_system_node_init_chat(
    scope_id: str,
    *,
    room_id: str,
    node_id: str,
    binding: dict[str, Any],
    scope_type: ScopeType = "demand",
) -> str:
    """系统节点初始化：写入协作流（无 Host/Worker 阵容）。"""
    clear_host_prompt_cache(scope_id)
    text = format_node_init_log(scope_type, scope_id, node_id=node_id)
    participants = build_system_participants()
    append_history_event(
        scope_id,
        {
            "event": "node_init",
            "room_id": room_id,
            "node_id": node_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "text": text,
            "chat_text": format_system_node_init_chat(node_id),
            "agent_id": "system",
            "log_type": "info",
            "binding": {
                "type": "system",
                "host_profile_id": "",
                "worker_profile_ids": [],
            },
            "participants": participants,
            "system_node": True,
            "flow_stage": "系统节点初始化",
        },
    )
    return text


def append_host_prompt_chat(
    scope_id: str,
    *,
    room_id: str,
    scope_type: ScopeType = "demand",
    node_id: str,
    binding: dict[str, Any],
    ticket_title: str = "",
    bundle: dict[str, Any] | None = None,
) -> str:
    """第三步：主控提示词组装结果写入协作会议流。"""
    bundle = bundle or assemble_host_prompt_bundle(
        scope_type=scope_type,
        scope_id=scope_id,
        node_id=node_id,
        binding=binding,
        ticket_title=ticket_title,
    )
    chat_text = format_host_prompt_chat_display(bundle)
    host_id = str(binding.get("host_profile_id") or "default")
    append_history_event(
        scope_id,
        {
            "event": "host_prompt_assembled",
            "room_id": room_id,
            "node_id": node_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            # text：完整组装结果（归档/排查）；chat_text：会议流流程说明（仅展示）
            "text": format_host_prompt_snapshot(bundle),
            "chat_text": chat_text,
            "agent_id": host_id,
            "log_type": "info",
            "flow_stage": "主控提示词组装",
        },
    )
    return chat_text
