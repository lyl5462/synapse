"""研发会议室：从 Agent 池探测各参会智能体的运行时上下文（调试用）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from synapse.rd_meeting.agent_session import host_session_id
from synapse.rd_meeting.live import scope_id_for_room_id
from synapse.rd_meeting.paths import scope_dir

logger = logging.getLogger(__name__)

_DEFAULT_MESSAGE_CHAR_LIMIT = 12_000


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit] + f"\n\n…（已截断，原文 {len(text)} 字符）", True


def _serialize_messages(messages: list[Any], *, char_limit: int) -> tuple[list[dict[str, Any]], bool]:
    out: list[dict[str, Any]] = []
    truncated = False
    for msg in messages:
        if isinstance(msg, dict):
            row = dict(msg)
        elif hasattr(msg, "to_dict"):
            row = msg.to_dict()
        else:
            row = {"role": "unknown", "content": str(msg)}
        content = row.get("content")
        if isinstance(content, str):
            row["content"], cut = _truncate_text(content, char_limit)
            truncated = truncated or cut
        out.append(row)
    return out, truncated


def _task_snapshot(agent: Any, session_id: str) -> dict[str, Any] | None:
    state = getattr(agent, "agent_state", None)
    if state is None:
        return None
    task = state.get_task_for_session(session_id) if session_id else None
    if task is None:
        task = state.current_task
    if task is None:
        return None
    status = task.status.value if hasattr(task.status, "value") else str(task.status)
    return {
        "task_id": str(getattr(task, "task_id", "") or "")[:8],
        "status": status,
        "iteration": int(getattr(task, "iteration", 0) or 0),
        "tools_executed": list(getattr(task, "tools_executed", None) or []),
        "description_preview": str(getattr(task, "description", "") or "")[:500],
        "usage_scene": str(getattr(task, "usage_scene", "") or ""),
    }


def _resolve_system_prompt(agent: Any) -> str:
    ctx = getattr(agent, "_context", None)
    system = str(getattr(ctx, "system", "") or "").strip()
    if system:
        return system
    builder = getattr(agent, "_build_system_prompt", None)
    if callable(builder):
        try:
            return str(builder() or "")
        except Exception as exc:
            logger.debug("probe _build_system_prompt failed: %s", exc)
    return ""


def probe_pooled_agent(
    agent: Any,
    *,
    session_id: str,
    profile_id: str,
    message_char_limit: int = _DEFAULT_MESSAGE_CHAR_LIMIT,
) -> dict[str, Any]:
    """从 Agent 池实例提取可读的上下文快照。"""
    role = "host" if session_id.endswith(":host") else "worker"
    ctx = getattr(agent, "_context", None)
    raw_messages = list(getattr(ctx, "messages", None) or [])
    messages, messages_truncated = _serialize_messages(raw_messages, char_limit=message_char_limit)

    system_prompt = _resolve_system_prompt(agent)
    system_prompt, system_truncated = _truncate_text(system_prompt, message_char_limit * 2)

    suffix = str(getattr(agent, "_custom_prompt_suffix", "") or "")
    suffix, suffix_truncated = _truncate_text(suffix, message_char_limit)

    return {
        "session_id": session_id,
        "profile_id": profile_id,
        "role": role,
        "preferred_endpoint": str(getattr(agent, "_preferred_endpoint", "") or ""),
        "default_cwd": str(getattr(agent, "default_cwd", "") or ""),
        "system_prompt": system_prompt,
        "system_prompt_truncated": system_truncated,
        "custom_prompt_suffix": suffix,
        "custom_prompt_suffix_truncated": suffix_truncated,
        "messages": messages,
        "messages_count": len(raw_messages),
        "messages_truncated": messages_truncated,
        "task": _task_snapshot(agent, session_id),
        "last_usage": getattr(agent, "last_usage", None),
    }


def collect_meeting_agent_contexts(
    room_id: str,
    agent_pool: Any | None,
    *,
    orchestrator: Any | None = None,
    message_char_limit: int = _DEFAULT_MESSAGE_CHAR_LIMIT,
) -> dict[str, Any]:
    """汇总会议室下 host / worker 池化 Agent 的上下文。"""
    rid = (room_id or "").strip()
    scope_id = scope_id_for_room_id(rid)
    prefix = f"rd_meeting:{rid}:"
    agents: list[dict[str, Any]] = []

    if agent_pool is not None:
        stats = agent_pool.get_stats() if hasattr(agent_pool, "get_stats") else {}
        seen: set[tuple[str, str]] = set()
        for sess in stats.get("sessions", []):
            sid = str(sess.get("session_id") or "")
            if not sid.startswith(prefix):
                continue
            for info in sess.get("agents", []) or []:
                pid = str(info.get("profile_id") or "")
                key = (sid, pid)
                if key in seen:
                    continue
                seen.add(key)
                getter = getattr(agent_pool, "get_existing", None)
                if not callable(getter):
                    continue
                pooled = getter(sid, pid)
                if pooled is None:
                    continue
                agents.append(
                    probe_pooled_agent(
                        pooled,
                        session_id=sid,
                        profile_id=pid,
                        message_char_limit=message_char_limit,
                    )
                )

    sub_agents: list[dict[str, Any]] = []
    host_sid = host_session_id(rid)
    if orchestrator is not None:
        getter = getattr(orchestrator, "get_sub_agent_states", None)
        if callable(getter):
            sub_agents = list(getter(host_sid) or [])

    return {
        "room_id": rid,
        "scope_id": scope_id,
        "host_session_id": host_sid,
        "agents": agents,
        "sub_agents": sub_agents,
        "probed_at": datetime.now().isoformat(timespec="seconds"),
    }


def dump_meeting_agent_contexts(
    payload: dict[str, Any],
    *,
    scope_id: str,
) -> str:
    """将探测结果写入工单目录 debug/agent_contexts/，并打 INFO 摘要日志。"""
    sid = (scope_id or "").strip()
    if not sid:
        raise ValueError("scope_id_required")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = scope_dir(sid) / "debug" / "agent_contexts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for agent in payload.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        task = agent.get("task") if isinstance(agent.get("task"), dict) else {}
        logger.info(
            "[rd_meeting context] room=%s profile=%s role=%s "
            "msgs=%s task=%s iter=%s tools=%s → %s",
            payload.get("room_id"),
            agent.get("profile_id"),
            agent.get("role"),
            agent.get("messages_count"),
            task.get("status"),
            task.get("iteration"),
            len(task.get("tools_executed") or []),
            path,
        )

    if not payload.get("agents"):
        logger.info(
            "[rd_meeting context] room=%s scope=%s no pooled agents (file=%s)",
            payload.get("room_id"),
            sid,
            path,
        )

    return str(path)
