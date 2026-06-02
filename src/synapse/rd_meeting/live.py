"""会议室 live 事件：委派/工具进度写入 room_history，供 UI 轮询。"""

from __future__ import annotations

import logging
import re
from typing import Any

from synapse.rd_meeting.dev_status import read_dev_status_file
from synapse.rd_meeting.participants import resolve_profile_display_name
from synapse.rd_meeting.paths import iter_work_order_directories
from synapse.rd_meeting.room_runtime import (
    append_history_event,
    load_room_state,
    resolve_history_node_id,
    save_room_state,
)

logger = logging.getLogger(__name__)

_RD_MEETING_SESSION_RE = re.compile(
    r"^rd_meeting:(?P<room>[^:]+):(?P<role>host|[^:]+)$",
    re.IGNORECASE,
)


def parse_rd_meeting_session(session_id: str) -> dict[str, str] | None:
    m = _RD_MEETING_SESSION_RE.match((session_id or "").strip())
    if not m:
        return None
    return {
        "room_id": m.group("room"),
        "role": m.group("role"),
        "profile_id": m.group("role") if m.group("role") != "host" else "",
    }


def scope_id_for_room_id(room_id: str) -> str | None:
    rid = (room_id or "").strip()
    if not rid:
        return None
    for order_dir in iter_work_order_directories():
        data = read_dev_status_file(order_dir / "dev.status")
        if not data:
            continue
        mr = data.get("meeting_room")
        if isinstance(mr, dict) and str(mr.get("room_id") or "").strip() == rid:
            return order_dir.name
    return None


def append_meeting_live_event(
    scope_id: str,
    *,
    room_id: str,
    event: str,
    text: str,
    agent_id: str = "system",
    log_type: str = "info",
    extra: dict[str, Any] | None = None,
) -> None:
    row: dict[str, Any] = {
        "event": event,
        "room_id": room_id,
        "text": text,
        "agent_id": agent_id,
        "log_type": log_type,
    }
    if extra:
        row.update(extra)
    rs = load_room_state(scope_id) or {}
    if isinstance(rs, dict):
        cur = str(rs.get("current_node_id") or "").strip()
        if cur and "node_id" not in row:
            row["node_id"] = cur
    if "node_id" not in row:
        row["node_id"] = resolve_history_node_id(scope_id, row)
    append_history_event(scope_id, row)


def _meeting_agent_label(agent_id: str) -> str:
    aid = (agent_id or "").strip()
    if not aid or aid.lower() == "host":
        return "小鲸"
    return resolve_profile_display_name(aid)


def record_delegation_started(
    session_id: str,
    *,
    from_agent: str,
    to_agent: str,
    reason: str = "",
    task_preview: str = "",
    plan_item_id: str = "",
) -> None:
    parsed = parse_rd_meeting_session(session_id)
    if not parsed:
        return
    scope_id = scope_id_for_room_id(parsed["room_id"])
    if not scope_id:
        return
    to_label = _meeting_agent_label(to_agent)
    reason_txt = f"（{reason}）" if reason.strip() else ""
    preview = (task_preview or "").strip().replace("\n", " ")
    preview_txt = f"\n任务：{preview[:280]}" if preview else ""
    plan_txt = f"\n计划项：{plan_item_id}" if (plan_item_id or "").strip() else ""
    body = f"小鲸 → {to_label}：已委派协作{reason_txt}{preview_txt}{plan_txt}"
    append_meeting_live_event(
        scope_id,
        room_id=parsed["room_id"],
        event="delegation_started",
        text=body,
        agent_id=from_agent or "host",
        log_type="info",
        extra={
            "to_agent": to_agent,
            "from_agent": from_agent,
            "reason": reason,
            "task_preview": preview[:2000],
            "plan_item_id": (plan_item_id or "").strip(),
            "chat_text": body,
        },
    )
    if parsed.get("role") == "host":
        from synapse.rd_meeting.hitl_lifecycle import clear_ready_for_node_review

        clear_ready_for_node_review(scope_id)
    _touch_agents_active(scope_id, parsed["room_id"], to_agent, "worker", "delegating")


def record_delegation_finished(
    session_id: str,
    *,
    from_agent: str,
    to_agent: str,
    ok: bool,
    summary: str = "",
    elapsed_s: float | None = None,
) -> None:
    parsed = parse_rd_meeting_session(session_id)
    if not parsed:
        return
    scope_id = scope_id_for_room_id(parsed["room_id"])
    if not scope_id:
        return
    status = "completed" if ok else "failed"
    preview = (summary or "")[:240].replace("\n", " ")
    elapsed = f" · {elapsed_s:.0f}s" if elapsed_s is not None else ""
    to_label = _meeting_agent_label(to_agent)
    body = f"{to_label} {status}{elapsed}" + (f"：{preview}" if preview else "")
    append_meeting_live_event(
        scope_id,
        room_id=parsed["room_id"],
        event="delegation_finished",
        text=body,
        agent_id=to_agent,
        log_type="info" if ok else "warning",
        extra={
            "to_agent": to_agent,
            "from_agent": from_agent,
            "ok": ok,
            "status": status,
            "result_summary": (summary or "")[:2000],
            "elapsed_s": elapsed_s,
            "chat_text": body,
        },
    )
    _touch_agents_active(scope_id, parsed["room_id"], to_agent, "worker", status)


def _touch_agents_active(
    scope_id: str,
    room_id: str,
    profile_id: str,
    role: str,
    status: str,
) -> None:
    rs = dict(load_room_state(scope_id) or {})
    active = rs.get("agents_active")
    if not isinstance(active, list):
        active = []
    found = False
    for item in active:
        if isinstance(item, dict) and str(item.get("profile_id")) == profile_id:
            item["status"] = status
            item["role"] = role
            found = True
            break
    if not found:
        active.append({"profile_id": profile_id, "role": role, "status": status})
    rs["agents_active"] = active
    rs["room_id"] = room_id
    save_room_state(scope_id, rs)


def collect_live_sub_agents(orchestrator: Any, host_session_id: str) -> list[dict[str, Any]]:
    """从 AgentOrchestrator 子任务状态聚合 live 条目。"""
    out: list[dict[str, Any]] = []
    if orchestrator is None:
        return out
    states = getattr(orchestrator, "_sub_agent_states", None) or {}
    for _key, st in states.items():
        if not isinstance(st, dict):
            continue
        sid = str(st.get("session_id") or "")
        if sid != host_session_id and host_session_id not in str(_key):
            continue
        out.append(
            {
                "agent_id": st.get("agent_id") or st.get("profile_id"),
                "name": st.get("name"),
                "status": st.get("status"),
                "iteration": st.get("iteration"),
                "tools_executed": st.get("tools_executed"),
                "tools_total": st.get("tools_total"),
                "skills_executed": st.get("skills_executed"),
                "skills_total": st.get("skills_total"),
                "elapsed_s": st.get("elapsed_s"),
                "tokens_used": st.get("tokens_used"),
                "current_tool_summary": st.get("current_tool_summary"),
            }
        )
    return out
