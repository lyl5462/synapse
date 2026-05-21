"""研发会议室工作安排计划：提交、校验、委派门禁。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.live import parse_rd_meeting_session, scope_id_for_room_id
from synapse.rd_meeting.participants import resolve_profile_display_name
from synapse.rd_meeting.room_runtime import append_history_event, load_room_state, save_room_state

logger = logging.getLogger(__name__)

PLAN_TYPE = "meeting_work_plan"
PLAN_VERSION = "1"
ROOM_STATE_KEY = "current_work_plan"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_rd_meeting_host_session(session_id: str) -> bool:
    parsed = parse_rd_meeting_session(session_id or "")
    return parsed is not None and parsed.get("role") == "host"


def meeting_context_from_session(session_id: str) -> dict[str, str] | None:
    """解析 rd_meeting host 会话 → scope_id / room_id / node_id。"""
    parsed = parse_rd_meeting_session(session_id or "")
    if not parsed or parsed.get("role") != "host":
        return None
    room_id = str(parsed.get("room_id") or "").strip()
    scope_id = scope_id_for_room_id(room_id)
    if not scope_id:
        return None
    dev = load_dev_status(scope_id)
    node_id = str(dev.get("current_node_id") or "pending") if dev else "pending"
    return {"scope_id": scope_id, "room_id": room_id, "node_id": node_id}


def _normalize_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("items 必须为非空数组")
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, row in enumerate(raw_items):
        if not isinstance(row, dict):
            raise ValueError(f"items[{i}] 必须为对象")
        item_id = str(row.get("id") or f"t{i + 1}").strip()
        if not item_id:
            raise ValueError(f"items[{i}].id 不能为空")
        if item_id in seen_ids:
            raise ValueError(f"items 中 id 重复: {item_id}")
        seen_ids.add(item_id)
        agent_id = str(row.get("agent_id") or "").strip()
        task = str(row.get("task") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if not agent_id:
            raise ValueError(f"items[{i}].agent_id 不能为空")
        if not task:
            raise ValueError(f"items[{i}].task 不能为空")
        if not reason:
            raise ValueError(f"items[{i}].reason 不能为空")
        entry: dict[str, Any] = {
            "id": item_id,
            "agent_id": agent_id,
            "task": task,
            "reason": reason,
        }
        pg = str(row.get("parallel_group") or "").strip()
        if pg:
            entry["parallel_group"] = pg
        out.append(entry)
    return out


def validate_work_plan_items(
    items: list[dict[str, Any]],
    *,
    allowed_worker_ids: list[str],
    host_profile_id: str,
) -> None:
    allowed = {str(w).strip() for w in allowed_worker_ids if str(w).strip()}
    host_id = str(host_profile_id or "").strip()
    if host_id:
        allowed.discard(host_id)
    if not allowed:
        raise ValueError("当前节点未配置可委派的协作智能体（worker_profile_ids）")
    for item in items:
        aid = str(item.get("agent_id") or "").strip()
        if aid not in allowed:
            raise ValueError(
                f"agent_id `{aid}` 不在本节点协作阵容内；可委派: {', '.join(sorted(allowed))}"
            )


def build_plan_document(
    *,
    goal_summary: str,
    items: list[dict[str, Any]],
    node_id: str,
) -> dict[str, Any]:
    return {
        "type": PLAN_TYPE,
        "version": PLAN_VERSION,
        "node_id": node_id,
        "goal_summary": (goal_summary or "").strip(),
        "items": items,
        "plan_id": uuid.uuid4().hex[:12],
        "submitted_at": _now_iso(),
    }


def format_plan_summary_text(plan: dict[str, Any]) -> str:
    lines = ["# 工作安排计划"]
    goal = str(plan.get("goal_summary") or "").strip()
    if goal:
        lines.append(f"\n**目标**：{goal}")
    lines.append("\n**任务分配**：")
    for item in plan.get("items") or []:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("agent_id") or "")
        name = resolve_profile_display_name(aid)
        task = str(item.get("task") or "").strip()
        reason = str(item.get("reason") or "").strip()
        pg = str(item.get("parallel_group") or "").strip()
        pg_txt = f" · 并行组 `{pg}`" if pg else ""
        lines.append(f"- **{name}** (`{aid}`){pg_txt}：{task}")
        if reason:
            lines.append(f"  - 原因：{reason}")
    return "\n".join(lines)


def clear_work_plan(scope_id: str) -> None:
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = dict(load_room_state(sid) or {})
    if ROOM_STATE_KEY in rs:
        rs.pop(ROOM_STATE_KEY, None)
        save_room_state(sid, rs)


def get_work_plan(scope_id: str) -> dict[str, Any] | None:
    rs = load_room_state((scope_id or "").strip()) or {}
    plan = rs.get(ROOM_STATE_KEY)
    return dict(plan) if isinstance(plan, dict) else None


def submit_work_plan(
    *,
    session_id: str,
    goal_summary: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    ctx = meeting_context_from_session(session_id)
    if ctx is None:
        raise ValueError("仅研发会议室主控（小鲸）会话可提交工作安排计划")

    scope_id = ctx["scope_id"]
    room_id = ctx["room_id"]
    node_id = ctx["node_id"]

    rs = dict(load_room_state(scope_id) or {})
    existing = rs.get(ROOM_STATE_KEY)
    if isinstance(existing, dict) and existing.get("delegation_started"):
        raise ValueError("已开始委派协作智能体，不可再修改工作安排计划")

    binding = resolve_node_binding(node_id, scope_id=scope_id)
    workers = [str(w).strip() for w in (binding.get("worker_profile_ids") or []) if str(w).strip()]
    host_id = str(binding.get("host_profile_id") or "default")
    normalized = _normalize_items(items)
    validate_work_plan_items(normalized, allowed_worker_ids=workers, host_profile_id=host_id)

    plan = build_plan_document(goal_summary=goal_summary, items=normalized, node_id=node_id)
    plan["delegation_started"] = False
    plan["delegated_item_ids"] = []

    rs[ROOM_STATE_KEY] = plan
    save_room_state(scope_id, rs)

    summary_text = format_plan_summary_text(plan)
    append_history_event(
        scope_id,
        {
            "event": "work_plan_submitted",
            "room_id": room_id,
            "node_id": node_id,
            "text": summary_text,
            "log_type": "info",
            "agent_id": host_id,
            "plan_id": plan.get("plan_id"),
            "item_count": len(normalized),
        },
    )
    return plan


def check_delegation_allowed(
    session_id: str,
    *,
    agent_id: str,
    plan_item_id: str = "",
) -> str | None:
    """返回错误信息；None 表示允许委派。"""
    if not is_rd_meeting_host_session(session_id):
        return None

    ctx = meeting_context_from_session(session_id)
    if ctx is None:
        return "❌ 无法解析研发会议室上下文，委派已阻止"

    scope_id = ctx["scope_id"]
    plan = get_work_plan(scope_id)
    if plan is None:
        return (
            "❌ 尚未提交工作安排计划。请先调用 `submit_meeting_work_plan` "
            "明确各协作智能体的任务与原因，再使用 delegate_to_agent / delegate_parallel。"
        )

    plan_node = str(plan.get("node_id") or "")
    if plan_node and plan_node != ctx["node_id"]:
        return (
            f"❌ 当前工作安排计划属于节点 `{plan_node}`，与当前节点 `{ctx['node_id']}` 不一致；"
            "请重新 submit_meeting_work_plan。"
        )

    aid = (agent_id or "").strip()
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    item_ids = {str(it.get("id") or "") for it in items if isinstance(it, dict)}
    agent_ids_in_plan = {
        str(it.get("agent_id") or "").strip()
        for it in items
        if isinstance(it, dict) and str(it.get("agent_id") or "").strip()
    }

    pid = (plan_item_id or "").strip()
    if pid:
        if pid not in item_ids:
            return f"❌ plan_item_id `{pid}` 不在当前工作安排计划中"
        matched = next((it for it in items if isinstance(it, dict) and str(it.get("id")) == pid), None)
        if matched and str(matched.get("agent_id") or "").strip() != aid:
            return f"❌ plan_item_id `{pid}` 对应 agent 为 `{matched.get('agent_id')}`，与 `{aid}` 不一致"
    elif aid not in agent_ids_in_plan:
        return (
            f"❌ agent_id `{aid}` 未出现在当前工作安排计划中；"
            f"计划内协作智能体: {', '.join(sorted(agent_ids_in_plan))}"
        )

    return None


def mark_delegation_started(
    session_id: str,
    *,
    agent_id: str,
    plan_item_id: str = "",
) -> None:
    if not is_rd_meeting_host_session(session_id):
        return
    ctx = meeting_context_from_session(session_id)
    if ctx is None:
        return
    scope_id = ctx["scope_id"]
    rs = dict(load_room_state(scope_id) or {})
    plan = rs.get(ROOM_STATE_KEY)
    if not isinstance(plan, dict):
        return
    plan = dict(plan)
    plan["delegation_started"] = True
    delegated = plan.get("delegated_item_ids")
    if not isinstance(delegated, list):
        delegated = []
    pid = (plan_item_id or "").strip()
    if pid and pid not in delegated:
        delegated.append(pid)
    elif not pid:
        items = plan.get("items") if isinstance(plan.get("items"), list) else []
        for it in items:
            if isinstance(it, dict) and str(it.get("agent_id") or "").strip() == (agent_id or "").strip():
                iid = str(it.get("id") or "")
                if iid and iid not in delegated:
                    delegated.append(iid)
                break
    plan["delegated_item_ids"] = delegated
    rs[ROOM_STATE_KEY] = plan
    save_room_state(scope_id, rs)
