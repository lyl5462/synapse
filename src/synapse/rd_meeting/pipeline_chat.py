"""Pipeline 各步骤在协作会议流中的可读展示（chat_text）。

``chat_text`` 仅描述**流程步骤**完成情况；实例数据在 ``text``（JSON）或快照中。
大模型 / 协作智能体的具体产出由其它事件（如 ``work_plan_submitted``、``delegation_*``）展示。
"""

from __future__ import annotations

import json
from typing import Any

from synapse.rd_meeting.flow_log import flow_log_to_text

# --- 步骤完成说明（流程层，不含工单/产品等实例字段）---

STEP_OPEN_SUMMARY = (
    "【步骤 1/3】开启会议室\n\n"
    "已为当前工单创建研发会议室并同步流程状态，下一步将进行节点初始化。"
)

STEP_NODE_INIT_SUMMARY = (
    "【步骤 2/3】节点初始化\n\n"
    "已解析本节点绑定关系，并加载工单 / 产品 / 系统上下文，供后续主控提示词注入。"
)

STEP_HOST_PROMPT_SUMMARY = (
    "【步骤 3/3】主控提示词组装\n\n"
    "已将会诊室 SKILL 与四段式动态上下文写入小鲸系统提示；"
    "待机后可触发「执行当前节点」开始主控推理。"
)

PHASE_WAITING_SUMMARY = (
    "【流程待机】\n\n"
    "会议室准备流程已完成，等待执行当前 SOP 节点或人工触发。"
)

STEP_RUN_NODE_SCHEDULE_SUMMARY = (
    "【调度执行】\n\n"
    "已提交当前 SOP 节点后台执行，主控将开始推理并按计划委派协作智能体。"
)


def format_room_opened_chat() -> str:
    """步骤 1：开启会议室（流程说明）。"""
    return STEP_OPEN_SUMMARY


def format_node_init_chat() -> str:
    """步骤 2：节点初始化（流程说明）。"""
    return STEP_NODE_INIT_SUMMARY


def format_host_prompt_step_chat() -> str:
    """步骤 3：主控提示词组装（流程说明）。"""
    return STEP_HOST_PROMPT_SUMMARY


def format_phase_change_chat(*, to_phase: str) -> str | None:
    """阶段切换：仅对需在会议流展示的阶段返回文案。"""
    phase = (to_phase or "").strip().lower()
    if phase == "waiting":
        return PHASE_WAITING_SUMMARY
    return None


def format_run_node_scheduled_chat() -> str:
    """可选步骤：调度节点执行。"""
    return STEP_RUN_NODE_SCHEDULE_SUMMARY


def format_event_chat_display(event: dict[str, Any]) -> str:
    """将 history 事件转为协作会议流展示文案（优先 ``chat_text``）。"""
    explicit = str(event.get("chat_text") or "").strip()
    if explicit:
        return explicit

    et = str(event.get("event") or "").strip()
    if et == "room_opened":
        return format_room_opened_chat()
    if et == "node_init":
        return format_node_init_chat()
    if et == "host_prompt_assembled":
        return format_host_prompt_step_chat()
    if et == "phase_change":
        return format_phase_change_chat(to_phase=str(event.get("to_phase") or "")) or ""
    if et == "work_plan_submitted":
        return str(event.get("text") or "").strip()
    if et == "run_node_scheduled":
        return format_run_node_scheduled_chat()

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
