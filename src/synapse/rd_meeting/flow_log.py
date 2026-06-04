"""研发会议室流程日志：``text`` 为紧凑 JSON，事件行不重复 payload。"""

from __future__ import annotations

import json
from typing import Any

FLOW_LOG_PREFIX = "会议室流程日志"

# event → 流程阶段（UI / room_history 展示用）
EVENT_FLOW_STAGE: dict[str, str] = {
    "room_opened": "开启会议室",
    "node_init": "节点初始化",
    "system_node_executed": "系统节点执行",
    "system_node_started": "系统节点开始",
    "host_prompt_assembled": "主控提示词组装",
    "node_started": "节点开始执行",
    "run_node_scheduled": "调度节点执行",
    "prewarm_workers": "预热协作智能体",
    "host_llm_begin": "主控推理开始",
    "host_llm_end": "主控推理结束",
    "delegation_started": "委派协作",
    "delegation_finished": "协作反馈",
    "work_plan_submitted": "工作安排计划",
    "human_gate": "人工门控",
    "solution_review_gate": "方案评审门控",
    "node_pending_clarify": "会中澄清",
    "node_pending_confirm": "结果确认",
    "node_validation_failed": "产物校验失败",
    "node_failed": "节点失败",
    "node_completed": "节点完成",
    "node_skipped": "节点跳过",
    "human_intervene": "人工介入",
    "hitl_approved": "确认通过",
    "hitl_rejected": "确认驳回",
    "hitl_dynamic": "动态问卷",
    "user_context": "用户上下文",
    "system": "系统",
    "chat_message": "对话",
}

CHAT_VISIBLE_EVENTS = frozenset(
    {
        "chat_message",
        "human_intervene",
        "room_opened",
        "system",
        "node_started",
        "node_init",
        "system_node_executed",
        "system_node_started",
        "host_prompt_assembled",
        "run_node_scheduled",
        "prewarm_workers",
        "host_llm_begin",
        "host_llm_end",
        "human_gate",
        "solution_review_gate",
        "delegation_started",
        "delegation_finished",
        "work_plan_submitted",
        "node_failed",
        "node_validation_failed",
        "hitl_approved",
        "hitl_rejected",
        "hitl_dynamic",
        "node_pending_confirm",
        "node_pending_clarify",
        "node_completed",
        "node_skipped",
        "run_node_scheduled",
    }
)

# room_opened 写入 history 后应剥离的重复字段
_ROOM_OPENED_STRIP = frozenset(
    {
        "payload",
        "userwork_updates",
        "sop_display",
        "local_process_state",
        "userwork_synced",
        "scope_type",
        "stage_id",
        "current_node_id",
    }
)

_NODE_INIT_STRIP = frozenset({"payload"})


def flow_log_to_text(data: Any) -> str:
    """紧凑单行 JSON（无缩进、无转义换行）。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def format_flow_log(stage: str, content: str) -> str:
    """兼容旧调用。"""
    _ = stage
    return flow_log_to_text({"message": (content or "").strip() or "（无详情）"})


def format_flow_log_json(
    stage: str,
    data: dict[str, Any],
    *,
    event: str = "",
) -> str:
    """兼容旧调用，直接序列化 data（不再套 envelope）。"""
    _ = stage, event
    return flow_log_to_text(data)


def is_flow_log_formatted(text: str) -> bool:
    return str(text or "").strip().startswith(FLOW_LOG_PREFIX)


def is_flow_log_json(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw.startswith("{"):
        return False
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict)


def resolve_flow_stage(event: dict[str, Any]) -> str:
    explicit = str(event.get("flow_stage") or "").strip()
    if explicit:
        return explicit
    et = str(event.get("event") or "").strip()
    return EVENT_FLOW_STAGE.get(et, et or "流程")


def _legacy_userwork_updates(event: dict[str, Any]) -> dict[str, str]:
    """从旧版重复字段推断 userwork 更新内容。"""
    if not event.get("userwork_synced"):
        return {}
    out: dict[str, str] = {}
    sop = str(event.get("sop_display") or "").strip()
    if sop:
        out["sop_node"] = sop
    local = str(event.get("local_process_state") or "").strip()
    if local:
        out["local_process_state"] = local
    return out


def _room_opened_text(event: dict[str, Any]) -> str:
    updates = event.get("userwork_updates")
    if isinstance(updates, dict):
        data = {k: str(v) for k, v in updates.items() if v is not None and str(v).strip()}
    else:
        data = _legacy_userwork_updates(event)
    return flow_log_to_text(data)


def _node_init_text(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    if isinstance(payload, dict) and "order" in payload:
        from synapse.rd_meeting.init_context import normalize_node_init_log_data

        return flow_log_to_text(normalize_node_init_log_data(payload))
    scope_type = str(event.get("scope_type") or "demand")
    scope_id = str(event.get("scope_id") or "").strip()
    node_id = str(event.get("node_id") or "").strip()
    if scope_id:
        from synapse.rd_meeting.init_context import build_node_init_log_data

        return flow_log_to_text(
            build_node_init_log_data(scope_type, scope_id, node_id=node_id)  # type: ignore[arg-type]
        )
    return flow_log_to_text({})


def _generic_event_text(event: dict[str, Any]) -> str:
    et = str(event.get("event") or "")
    text = str(event.get("text") or event.get("message") or "").strip()
    if is_flow_log_json(text):
        return text
    payload = event.get("payload")
    if isinstance(payload, dict):
        return flow_log_to_text(payload)
    if et == "human_intervene":
        content = text if text and not is_flow_log_formatted(text) else ""
        return flow_log_to_text(
            {
                "message_type": event.get("message_type"),
                "content": content,
            }
        )
    if text and not is_flow_log_formatted(text):
        return flow_log_to_text({"message": text})
    skip = frozenset({"text", "message", "payload", "ts", "flow_stage", "event"})
    meta = {k: v for k, v in event.items() if k not in skip and v is not None}
    return flow_log_to_text(meta if meta else {"message": "（无详情）"})


def _strip_event_fields(row: dict[str, Any], *, remove: frozenset[str]) -> None:
    for key in remove:
        row.pop(key, None)


def apply_flow_log_format(event: dict[str, Any]) -> dict[str, Any]:
    """写入 history：``text`` 仅含业务 JSON，去掉与 text 重复的顶层字段。"""
    row = dict(event)
    et = str(row.get("event") or "")
    row["flow_stage"] = resolve_flow_stage(row)
    chat_text = str(row.get("chat_text") or "").strip()

    existing = str(row.get("text") or row.get("message") or "").strip()
    if et == "host_prompt_assembled" and existing and not is_flow_log_json(existing):
        row["text"] = existing
        row.pop("payload", None)
        if chat_text:
            row["chat_text"] = chat_text
        return row

    if is_flow_log_json(existing):
        row["text"] = existing
        if et == "room_opened":
            _strip_event_fields(row, remove=_ROOM_OPENED_STRIP)
        elif et == "node_init":
            _strip_event_fields(row, remove=_NODE_INIT_STRIP)
        else:
            row.pop("payload", None)
        if chat_text:
            row["chat_text"] = chat_text
        return row

    if et == "room_opened":
        row["text"] = _room_opened_text(row)
        _strip_event_fields(row, remove=_ROOM_OPENED_STRIP)
    elif et == "node_init":
        row["text"] = _node_init_text(row)
        _strip_event_fields(row, remove=_NODE_INIT_STRIP)
    else:
        row["text"] = _generic_event_text(row)
        row.pop("payload", None)

    if chat_text:
        row["chat_text"] = chat_text
    return row


def build_event_body(event: dict[str, Any]) -> str:
    """会议室 UI 摘要：解析 ``text`` JSON 或回退原文。"""
    text = str(event.get("text") or "").strip()
    if is_flow_log_json(text):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return text[:500]
        if isinstance(obj, dict) and obj.get("message"):
            return str(obj["message"])[:500]
        return flow_log_to_text(obj)[:500]
    return text[:500] if text else ""
