"""submit_hitl_questionnaire 工具底层入口：写入 room_state.pending_questionnaire。

设计：工具调用即「锁定」本节点 host 的下一步。orchestrator 在 ``execute_task``
结束后优先读取 ``room_state.pending_questionnaire``，跳过 LLM 终稿解析，避免模型
最后一轮把问卷块覆盖掉。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from synapse.rd_meeting.hitl_form import coerce_questionnaire_schema
from synapse.rd_meeting.live import parse_rd_meeting_session, scope_id_for_room_id
from synapse.rd_meeting.room_runtime import append_history_event, load_room_state, save_room_state

logger = logging.getLogger(__name__)

PENDING_QUESTIONNAIRE_KEY = "pending_questionnaire"

_DEFAULT_AWAIT_CONFIRM = {
    "interactive": False,
    "result_confirm": True,
    "exception": False,
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def submit_questionnaire(
    *,
    session_id: str,
    kind: str,
    questions: Any,
    title: str = "",
    description: str = "",
    summary: str = "",
    await_confirm: bool | None = None,
    render: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """rd_meeting host 会话内调用：写入 room_state.pending_questionnaire。

    Returns:
        dict: {"scope_id", "room_id", "node_id", "schema", "await_confirm", "kind"}

    Raises:
        ValueError: 非 rd_meeting host 会话 / 输入校验失败 / 已有未消费问卷
    """
    parsed = parse_rd_meeting_session(session_id or "")
    if not parsed or parsed.get("role") != "host":
        raise ValueError("仅研发会议室主控（小鲸）会话可提交人机问卷")

    room_id = str(parsed.get("room_id") or "").strip()
    scope_id = scope_id_for_room_id(room_id)
    if not scope_id:
        raise ValueError(f"无法解析房间 {room_id} 对应的 scope_id")

    schema = coerce_questionnaire_schema(
        kind=kind,
        questions=questions,
        title=title,
        description=description,
        summary=summary,
        render=render,
    )
    kind_norm = schema.get("intervention_kind") or kind.strip().lower()
    if await_confirm is None:
        await_confirm = _DEFAULT_AWAIT_CONFIRM.get(kind_norm, False)

    rs = dict(load_room_state(scope_id) or {})
    node_id = str(rs.get("current_node_id") or "").strip() or "pending"
    existing = rs.get(PENDING_QUESTIONNAIRE_KEY)
    if isinstance(existing, dict) and not existing.get("consumed"):
        logger.info(
            "[hitl_submit] override pending questionnaire scope=%s node=%s old_kind=%s",
            scope_id,
            node_id,
            existing.get("kind"),
        )

    payload = {
        "schema": schema,
        "kind": kind_norm,
        "await_confirm": bool(await_confirm),
        "summary": summary.strip() or "",
        "node_id": node_id,
        "submitted_at": _now_iso(),
        "consumed": False,
    }
    rs[PENDING_QUESTIONNAIRE_KEY] = payload
    save_room_state(scope_id, rs)

    append_history_event(
        scope_id,
        {
            "event": "hitl_questionnaire_submitted",
            "room_id": room_id,
            "node_id": node_id,
            "intervention_kind": kind_norm,
            "await_confirm": bool(await_confirm),
            "question_count": len(schema.get("questions") or []),
            "log_type": "info",
            "agent_id": "default",
        },
    )

    try:
        from synapse.rd_meeting.agent_activity import record_output, resolve_binding_for_profile
        from synapse.rd_meeting.binding import resolve_node_binding

        binding = resolve_node_binding(node_id)
        host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
        act = resolve_binding_for_profile(scope_id, node_id, host_id, host_profile_id=host_id)
        record_output(
            act,
            output_kind="questionnaire",
            title="提交人机问卷",
            summary=summary.strip() or str(schema.get("title") or ""),
            detail={
                "kind": kind_norm,
                "question_count": len(schema.get("questions") or []),
            },
        )
    except Exception as exc:
        logger.debug("hitl_submit activity record failed: %s", exc)

    return {
        "scope_id": scope_id,
        "room_id": room_id,
        "node_id": node_id,
        "schema": schema,
        "await_confirm": bool(await_confirm),
        "kind": kind_norm,
    }


def consume_pending_questionnaire(scope_id: str) -> dict[str, Any] | None:
    """orchestrator 取出 host 工具写入的问卷；取出后标记 consumed=True。

    Returns:
        dict 或 None：{"schema", "kind", "await_confirm", "summary", "node_id"}
    """
    sid = (scope_id or "").strip()
    if not sid:
        return None
    rs = dict(load_room_state(sid) or {})
    pending = rs.get(PENDING_QUESTIONNAIRE_KEY)
    if not isinstance(pending, dict) or pending.get("consumed"):
        return None
    out = {
        "schema": pending.get("schema") or None,
        "kind": str(pending.get("kind") or "interactive"),
        "await_confirm": bool(pending.get("await_confirm")),
        "summary": str(pending.get("summary") or ""),
        "node_id": str(pending.get("node_id") or ""),
        "submitted_at": str(pending.get("submitted_at") or ""),
    }
    pending["consumed"] = True
    rs[PENDING_QUESTIONNAIRE_KEY] = pending
    save_room_state(sid, rs)
    return out


def clear_pending_questionnaire(scope_id: str) -> None:
    """节点切换 / 重启时清理（避免脏数据）。"""
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = dict(load_room_state(sid) or {})
    if PENDING_QUESTIONNAIRE_KEY in rs:
        rs.pop(PENDING_QUESTIONNAIRE_KEY, None)
        save_room_state(sid, rs)
