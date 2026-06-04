"""Pipeline 各步骤在协作会议流中的可读展示（chat_text）。

``chat_text`` 仅描述**流程步骤**完成情况；实例数据在 ``text``（JSON）或快照中。
大模型 / 协作智能体的具体产出由其它事件（如 ``work_plan_submitted``、``delegation_*``）展示。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from synapse.rd_meeting.flow_log import flow_log_to_text

# host_llm_begin 会议流文案：按流程场景区分，与 host_prompt_cache 无关
HostLlmBeginKind = Literal["start_work", "delivery_confirmed"]

# --- 步骤完成说明（流程层，不含工单/产品等实例字段）---

STEP_OPEN_SUMMARY = (
    "开启会议室\n\n"
    "已为当前工单创建研发会议室并同步流程状态，下一步将进行节点初始化。"
)

STEP_NODE_INIT_SUMMARY = (
    "节点初始化\n\n"
    "已解析本节点绑定关系，并加载工单 / 产品 / 系统上下文，供后续主控提示词注入。"
)

STEP_SYSTEM_NODE_INIT_SUMMARY = (
    "系统节点初始化\n\n"
    "本节点由系统脚本执行（无大模型、无人工确认）。已加载工单 / 产品上下文，准备执行代码任务。"
)

STEP_SYSTEM_NODE_EXEC_SUMMARY = (
    "系统节点执行\n\n"
    "系统脚本已完成本节点任务，产出物与目录信息已落盘。"
)

STEP_HOST_PROMPT_SUMMARY = (
    "主控提示词组装\n\n"
    "已将会诊室 SKILL 与四段式动态上下文写入小鲸系统提示；"
    "将立即调度小鲸执行当前 SOP 节点。"
)

PHASE_WAITING_SUMMARY = (
    "流程待机\n\n"
    "会议室准备流程已完成，等待执行当前 SOP 节点或人工触发。"
)

STEP_HOST_FIRST_CALL_SUMMARY = (
    "主控触发执行\n\n"
    "小鲸开始执行当前 SOP 节点（计划、委派、产出与人工确认等）。"
)

STEP_HOST_FIRST_CALL_REUSED_SUMMARY = (
    "主控触发总结\n\n"
    "用户已确认本节点总结无误；系统归档交付物并推进 SOP（进入节点收尾 / 下一节点准备）。"
)


def format_room_opened_chat() -> str:
    """步骤 1：开启会议室（流程说明）。"""
    return STEP_OPEN_SUMMARY


def format_node_init_chat() -> str:
    """步骤 2：节点初始化（流程说明）。"""
    return STEP_NODE_INIT_SUMMARY


def format_system_node_init_chat(node_id: str = "") -> str:
    """系统节点初始化（流程说明）。"""
    _ = node_id
    return STEP_SYSTEM_NODE_INIT_SUMMARY


def format_system_node_exec_chat() -> str:
    return STEP_SYSTEM_NODE_EXEC_SUMMARY


def format_host_prompt_step_chat() -> str:
    """步骤 3：主控提示词组装（流程说明）。"""
    return STEP_HOST_PROMPT_SUMMARY


def format_phase_change_chat(*, to_phase: str) -> str | None:
    """阶段切换：仅对需在会议流展示的阶段返回文案。"""
    phase = (to_phase or "").strip().lower()
    if phase == "waiting":
        return PHASE_WAITING_SUMMARY
    return None


def format_host_first_call_chat(
    *,
    kind: HostLlmBeginKind = "start_work",
    reused_prompt: bool | None = None,
) -> str:
    """``host_llm_begin`` 气泡文案（流程场景，非缓存命中）。

    - ``start_work``：触发模型继续干活（Pipeline / 问卷反馈 / 驳回返工）
    - ``delivery_confirmed``：用户确认总结无误后收尾推进
    """
    _ = reused_prompt  # 遗留参数，仅兼容旧调用方
    if kind == "delivery_confirmed":
        return STEP_HOST_FIRST_CALL_REUSED_SUMMARY
    return STEP_HOST_FIRST_CALL_SUMMARY


def resolve_host_llm_begin_kind(event: dict[str, Any]) -> HostLlmBeginKind:
    """从 history 事件解析场景（兼容旧数据）。"""
    raw = str(event.get("llm_begin_kind") or "").strip()
    if raw == "delivery_confirmed":
        return "delivery_confirmed"
    return "start_work"


def format_event_chat_display(event: dict[str, Any]) -> str:
    """将 history 事件转为协作会议流展示文案（优先 ``chat_text``）。"""
    explicit = str(event.get("chat_text") or "").strip()
    if explicit:
        return explicit

    et = str(event.get("event") or "").strip()
    if et == "room_opened":
        return format_room_opened_chat()
    if et == "node_init":
        if event.get("system_node"):
            return format_system_node_init_chat(str(event.get("node_id") or ""))
        return format_node_init_chat()
    if et == "system_node_executed":
        return format_system_node_exec_chat()
    if et == "host_prompt_assembled":
        return format_host_prompt_step_chat()
    if et == "phase_change":
        return format_phase_change_chat(to_phase=str(event.get("to_phase") or "")) or ""
    if et == "work_plan_submitted":
        return str(event.get("text") or "").strip()
    if et == "host_llm_begin":
        return format_host_first_call_chat(kind=resolve_host_llm_begin_kind(event))
    if et == "delegation_started":
        preview = str(event.get("task_preview") or "").strip()
        plan = str(event.get("plan_item_id") or "").strip()
        reason = str(event.get("reason") or "").strip()
        lines = [str(event.get("text") or "小鲸已委派协作智能体").strip()]
        if plan:
            lines.append(f"计划项：{plan}")
        if reason:
            lines.append(f"原因：{reason}")
        if preview:
            lines.append(f"委派内容：\n{preview}")
        return "\n".join(lines)
    if et == "delegation_finished":
        summary = str(event.get("result_summary") or "").strip()
        lines = [str(event.get("text") or "协作智能体已返回").strip()]
        if summary and summary not in lines[0]:
            lines.append(f"返回摘要：\n{summary[:2000]}")
        return "\n".join(lines)
    if et == "solution_review_gate":
        return str(event.get("text") or "").strip()

    text = str(event.get("text") or event.get("message") or "").strip()
    if text and not text.startswith("{"):
        return text
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return text[:8000]
        if isinstance(obj, dict) and obj.get("message"):
            return str(obj["message"])
        return flow_log_to_text(obj)
    return text
