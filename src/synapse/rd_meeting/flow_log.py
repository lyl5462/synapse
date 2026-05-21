"""研发会议室流程日志：统一 ``会议室流程日志 -- 阶段 -- 内容`` 格式。"""

from __future__ import annotations

from typing import Any

FLOW_LOG_PREFIX = "会议室流程日志"

# event → 流程阶段（UI / room_history 展示用）
EVENT_FLOW_STAGE: dict[str, str] = {
    "room_opened": "开启会议室",
    "node_init": "节点初始化",
    "node_started": "节点开始执行",
    "run_node_scheduled": "调度节点执行",
    "run_node_begin": "节点执行中",
    "prewarm_workers": "预热协作智能体",
    "host_llm_begin": "主控推理开始",
    "host_llm_end": "主控推理结束",
    "delegation_started": "委派协作",
    "delegation_finished": "协作反馈",
    "human_gate": "人工门控",
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
    "phase_change": "阶段切换",
    "pipeline_transition": "流程迁移",
    "system": "系统",
    "chat_message": "对话",
}

# 写入 room_history 且需在右侧协作流展示的事件
CHAT_VISIBLE_EVENTS = frozenset(
    {
        "chat_message",
        "human_intervene",
        "room_opened",
        "system",
        "node_started",
        "node_init",
        "run_node_scheduled",
        "run_node_begin",
        "prewarm_workers",
        "host_llm_begin",
        "host_llm_end",
        "human_gate",
        "delegation_started",
        "delegation_finished",
        "node_failed",
        "node_validation_failed",
        "hitl_approved",
        "hitl_rejected",
        "hitl_dynamic",
        "node_pending_confirm",
        "node_pending_clarify",
        "node_completed",
        "node_skipped",
        "phase_change",
        "pipeline_transition",
    }
)


def format_flow_log(stage: str, content: str) -> str:
    """``会议室流程日志 -- {阶段} -- {内容}``"""
    stage_txt = (stage or "流程").strip()
    body = (content or "").strip() or "（无详情）"
    return f"{FLOW_LOG_PREFIX} -- {stage_txt} -- {body}"


def is_flow_log_formatted(text: str) -> bool:
    return str(text or "").strip().startswith(FLOW_LOG_PREFIX)


def resolve_flow_stage(event: dict[str, Any]) -> str:
    explicit = str(event.get("flow_stage") or "").strip()
    if explicit:
        return explicit
    et = str(event.get("event") or "").strip()
    return EVENT_FLOW_STAGE.get(et, et or "流程")


def build_event_body(event: dict[str, Any]) -> str:
    """为缺少 text/message 的事件合成可读正文（格式化前）。"""
    et = str(event.get("event") or "")
    text = str(event.get("text") or event.get("message") or "").strip()
    if text and not is_flow_log_formatted(text):
        return text

    if et == "room_opened":
        return (
            f"room_id={event.get('room_id')} "
            f"scope={event.get('scope_type')}/{event.get('scope_id')} "
            f"node={event.get('current_node_id')} stage={event.get('stage_id')}"
        )
    if et == "run_node_scheduled":
        return f"已调度后台执行当前节点 room={event.get('room_id')}"
    if et == "run_node_begin":
        return f"开始执行节点 {event.get('node_id')} room={event.get('room_id')}"
    if et == "prewarm_workers":
        workers = event.get("worker_profile_ids") or []
        return f"预热协作智能体：{', '.join(str(w) for w in workers) or '（无）'}"
    if et == "host_llm_begin":
        return f"主控 {event.get('host_profile_id')} 开始处理议程 node={event.get('node_id')}"
    if et == "host_llm_end":
        preview = str(event.get("report_preview") or "")[:200].replace("\n", " ")
        ok = event.get("success", True)
        return f"主控结束 success={ok}" + (f" · {preview}" if preview else "")
    if et == "node_completed":
        nxt = event.get("next_node_id")
        return (
            f"节点 {event.get('node_id')} 已完成"
            f" tokens={event.get('tokens_used')} duration={event.get('duration_seconds')}s"
            f" 下一节点={nxt or '（流水线结束）'}"
        )
    if et == "node_skipped":
        return f"节点 {event.get('node_id')} 已跳过（配置关闭）"
    if et == "node_failed":
        return str(event.get("error") or event.get("message") or "执行失败")
    if et == "node_validation_failed":
        errs = event.get("errors") or []
        if isinstance(errs, list):
            return "; ".join(str(e) for e in errs)
        return str(errs)
    if et == "node_pending_confirm":
        dyn = "动态问卷" if event.get("dynamic_form") else "默认确认表单"
        return (
            f"节点 {event.get('node_id')} 等待结果确认（{dyn}）"
            f" tokens={event.get('tokens_used')}"
        )
    if et == "hitl_approved":
        c = str(event.get("comment") or "").strip()
        return f"用户确认通过 node={event.get('node_id')}" + (f" · {c}" if c else "")
    if et == "hitl_rejected":
        c = str(event.get("comment") or "").strip()
        return f"用户要求返工 node={event.get('node_id')}" + (f" · {c}" if c else "")
    if et == "hitl_dynamic":
        return str(event.get("detail") or "检测到动态 HITL 问卷")
    if et == "human_intervene":
        mt = event.get("message_type") or "instruction"
        raw = str(event.get("text") or "").strip()
        if raw and not is_flow_log_formatted(raw):
            return f"[{mt}] {raw[:500]}"
        return f"用户消息 type={mt}"
    if et == "phase_change":
        return f"phase: {event.get('from_phase')} → {event.get('to_phase')}"
    if et == "delegation_started":
        to_a = event.get("to_agent") or ""
        reason = event.get("reason") or ""
        preview = event.get("task_preview") or ""
        parts = [f"→ {to_a}"]
        if reason:
            parts.append(f"原因={reason}")
        if preview:
            parts.append(f"任务={preview}")
        return " ".join(parts)
    if et == "delegation_finished":
        return str(event.get("text") or event.get("summary") or "").strip() or (
            f"协作 {event.get('to_agent')} status={event.get('status')}"
        )
    return text


def apply_flow_log_format(event: dict[str, Any]) -> dict[str, Any]:
    """为 history 事件写入统一流程日志文案（就地修改并返回）。"""
    row = dict(event)
    existing = str(row.get("text") or row.get("message") or "").strip()
    if is_flow_log_formatted(existing):
        row.setdefault("flow_stage", resolve_flow_stage(row))
        return row
    stage = resolve_flow_stage(row)
    body = build_event_body(row)
    formatted = format_flow_log(stage, body)
    if row.get("text") is not None or "text" in row:
        row["text"] = formatted
    elif row.get("message") is not None or "message" in row:
        row["message"] = formatted
    else:
        row["text"] = formatted
    row["flow_stage"] = stage
    return row
