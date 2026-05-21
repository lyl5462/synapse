"""Pipeline 各步骤在协作会议流中的可读展示（chat_text）。"""

from __future__ import annotations

import json
from typing import Any

from synapse.rd_meeting.flow_log import flow_log_to_text
from synapse.rd_meeting.host_prompt import _format_node_init_sections_markdown
from synapse.rd_meeting.init_context import (
    build_node_init_log_data,
    normalize_node_init_log_data,
)


def format_room_opened_chat(
    *,
    room_id: str,
    scope_id: str,
    userwork_updates: dict[str, str] | None = None,
    current_node_id: str = "",
    sop_display: str = "",
) -> str:
    """【步骤 1/3】开启会议室。"""
    lines = [
        "【步骤 1/3】开启会议室",
        "",
        f"- 会议室 ID：`{room_id or '—'}`",
        f"- 工单范围：`{scope_id or '—'}`",
    ]
    if current_node_id and current_node_id not in ("pending", ""):
        lines.append(f"- 当前节点：`{current_node_id}`" + (f"（{sop_display}）" if sop_display else ""))
    updates = userwork_updates or {}
    if updates:
        lines.append("- userwork 已回写：")
        for k, v in updates.items():
            if v is not None and str(v).strip():
                lines.append(f"  - {k}：`{v}`")
    else:
        lines.append("- userwork：本次未同步（或无可写字段）")
    lines.append("")
    lines.append("会议室目录与流程状态已就绪，进入节点初始化。")
    return "\n".join(lines)


def format_node_init_chat(
    scope_type: str,
    scope_id: str,
    *,
    node_id: str = "",
) -> str:
    """【步骤 2/3】节点初始化（工单 + 产品 + 系统）。"""
    data = build_node_init_log_data(scope_type, scope_id, node_id=node_id)  # type: ignore[arg-type]
    body = _format_node_init_sections_markdown(data)
    return "\n".join(
        [
            "【步骤 2/3】节点初始化",
            "",
            "已加载 userwork 工单上下文，并按 prod 完成统一服务产品定位：",
            "",
            body,
        ]
    ).strip()


def format_node_init_chat_from_event(event: dict[str, Any]) -> str:
    """从 history 事件还原步骤 2 展示。"""
    payload = event.get("payload")
    if isinstance(payload, dict) and "order" in payload:
        data = normalize_node_init_log_data(payload)
    else:
        scope_type = str(event.get("scope_type") or "demand")
        scope_id = str(event.get("scope_id") or "").strip()
        node_id = str(event.get("node_id") or "").strip()
        if scope_id:
            data = build_node_init_log_data(scope_type, scope_id, node_id=node_id)  # type: ignore[arg-type]
        else:
            text = str(event.get("text") or "").strip()
            if text.startswith("{"):
                try:
                    parsed = json.loads(text)
                    data = normalize_node_init_log_data(parsed) if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return text
            else:
                return text or "【步骤 2/3】节点初始化"
    return format_node_init_chat(
        str(data.get("order", {}).get("scope_type") or event.get("scope_type") or "demand"),
        str(data.get("order", {}).get("scope_id") or event.get("scope_id") or ""),
        node_id=str(event.get("node_id") or ""),
    )


def format_pipeline_transition_chat(event: dict[str, Any]) -> str:
    from_label = str(event.get("from_step_label") or event.get("from_step") or "").strip()
    to_label = str(event.get("to_step_label") or event.get("to_step") or "").strip()
    reason = str(event.get("reason") or "").strip()
    lines = ["**流程迁移**", f"`{from_label}` → `{to_label}`"]
    if reason:
        lines.append(f"原因：{reason}")
    return "\n".join(lines)


def format_event_chat_display(event: dict[str, Any]) -> str:
    """将 history 事件转为协作会议流展示文案（优先完整 Markdown）。"""
    explicit = str(event.get("chat_text") or "").strip()
    if explicit:
        return explicit

    et = str(event.get("event") or "").strip()
    if et == "room_opened":
        text = str(event.get("text") or "").strip()
        updates: dict[str, str] = {}
        if text.startswith("{"):
            try:
                raw = json.loads(text)
                if isinstance(raw, dict):
                    updates = {k: str(v) for k, v in raw.items()}
            except json.JSONDecodeError:
                pass
        if not updates and isinstance(event.get("userwork_updates"), dict):
            updates = {k: str(v) for k, v in event["userwork_updates"].items()}
        return format_room_opened_chat(
            room_id=str(event.get("room_id") or ""),
            scope_id=str(event.get("scope_id") or ""),
            userwork_updates=updates,
            current_node_id=str(event.get("current_node_id") or ""),
            sop_display=str(event.get("sop_display") or updates.get("sop_node") or ""),
        )
    if et == "node_init":
        return format_node_init_chat_from_event(event)
    if et == "host_prompt_assembled":
        return str(event.get("text") or "").strip() or "【步骤 3/3】主控提示词已组装"
    if et == "pipeline_transition":
        payload = event.get("payload")
        if isinstance(payload, dict):
            merged = {**event, **payload}
            return format_pipeline_transition_chat(merged)
        return format_pipeline_transition_chat(event)
    if et == "work_plan_submitted":
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
        if et == "node_init" and isinstance(obj, dict) and "order" in obj:
            return _format_node_init_sections_markdown(normalize_node_init_log_data(obj))
        return flow_log_to_text(obj)
    return text
