"""协作会议流：history 事件 → 结构化 chat log（含展示类型与发言角色）。"""

from __future__ import annotations

import json
import re
from typing import Any

from synapse.rd_meeting.flow_log import CHAT_VISIBLE_EVENTS
from synapse.rd_meeting.pipeline_chat import format_event_chat_display

# 发言角色：system=编排/日志；host=小鲸；worker=协作智能体；user=人工
SPEAKER_SYSTEM = "system"
SPEAKER_HOST = "host"
SPEAKER_WORKER = "worker"
SPEAKER_USER = "user"

# 仅展示流程说明，不重复实例数据
SYSTEM_PIPELINE_EVENTS = frozenset(
    {
        "room_opened",
        "host_prompt_assembled",
        "run_node_scheduled",
    }
)

# 不写入协作会议流（已在其它事件展示）
CHAT_SKIP_EVENTS = frozenset(
    {
        "prewarm_workers",
    }
)

DELEGATION_START_RE = re.compile(
    r"^小鲸\s*→\s*(.+?)：已委派协作",
)
DELEGATION_DONE_RE = re.compile(
    r"^(.+?)\s+(completed|failed)(?:\s*·\s*(\d+)s)?(?:\s*：(.*))?$",
    re.DOTALL,
)


def _try_parse_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw.startswith("{"):
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _unwrap_message_body(text: str) -> str:
    """flow_log / 旧数据：``{"message": "..."}`` → 可渲染正文。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    obj = _try_parse_json(raw)
    if obj is not None:
        msg = obj.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    return raw


def _is_node_context_payload(obj: dict[str, Any]) -> bool:
    return isinstance(obj.get("order"), dict) and (
        isinstance(obj.get("product"), dict) or isinstance(obj.get("system"), dict)
    )


def _is_participants_meta(obj: dict[str, Any]) -> bool:
    return bool(obj.get("room_id")) and (
        obj.get("worker_profile_ids") is not None or obj.get("participants") is not None
    )


def _is_human_report_meta(obj: dict[str, Any]) -> bool:
    return bool(str(obj.get("report_preview") or "").strip()) or obj.get("success") is not None


def _format_ts_hms(iso: str) -> str:
    from synapse.rd_meeting.room_runtime import _format_ts_hms as _fmt

    return _fmt(iso)


def _history_chat_id(ev: dict[str, Any], index: int) -> str:
    """节点级唯一 id，避免 mergeChatLogs 时不同 SOP 节点的 hist-{n} 互相覆盖。"""
    nid = str(ev.get("node_id") or "").strip() or "pending"
    raw = str(ev.get("id") or f"hist-{index}").strip() or f"hist-{index}"
    prefix = f"{nid}:"
    if raw.startswith(prefix):
        return raw
    return f"{prefix}{raw}"


def _base_row(ev: dict[str, Any], index: int) -> dict[str, Any]:
    et = str(ev.get("event") or "")
    node_id = str(ev.get("node_id") or "").strip() or None
    return {
        "id": _history_chat_id(ev, index),
        "event": et,
        "nodeId": node_id,
        "timestamp": _format_ts_hms(str(ev.get("ts") or "")),
        "type": str(ev.get("log_type") or ("user" if et == "human_intervene" else "info")),
    }


def _row(
    ev: dict[str, Any],
    index: int,
    *,
    text: str,
    agent_id: str,
    speaker_role: str,
    display_kind: str,
    payload: dict[str, Any] | None = None,
    rich: bool = False,
    suffix: str = "",
) -> dict[str, Any]:
    row = _base_row(ev, index)
    row["agentId"] = agent_id
    row["speakerRole"] = speaker_role
    row["displayKind"] = display_kind
    row["text"] = text
    if payload is not None:
        row["payload"] = payload
    if rich:
        row["rich"] = True
    if suffix:
        row["id"] = f"{row['id']}{suffix}"
    return row


def _host_row(
    ev: dict[str, Any],
    index: int,
    *,
    text: str,
    display_kind: str,
    host_id: str,
    payload: dict[str, Any] | None = None,
    rich: bool = False,
    suffix: str = "",
) -> dict[str, Any]:
    return _row(
        ev,
        index,
        text=text,
        agent_id=host_id,
        speaker_role=SPEAKER_HOST,
        display_kind=display_kind,
        payload=payload,
        rich=rich,
        suffix=suffix,
    )


_INTERVENTION_KIND_LABELS: dict[str, str] = {
    "solution_review": "方案评审",
    "result_confirm": "结果确认",
    "interactive": "会中澄清",
    "exception": "异常裁决",
    "gate": "流程门控",
}


def _intervention_kind_label(kind: str) -> str:
    k = (kind or "").strip()
    return _INTERVENTION_KIND_LABELS.get(k, k or "人工处理")


def _expand_intervention_gate(
    ev: dict[str, Any], index: int, host_id: str
) -> list[dict[str, Any]]:
    from synapse.rd_sop.nodes import node_display_name

    et = str(ev.get("event") or "")
    node_id = str(ev.get("node_id") or "").strip()
    kind = str(ev.get("intervention_kind") or "").strip()
    node_label = node_display_name(node_id) if node_id else node_id
    reason = str(ev.get("text") or ev.get("chat_text") or "").strip()

    if et == "solution_review_gate":
        title = reason or (
            f"{node_label} 待人工方案评审（补丁选择 + 通过/不通过）"
            if node_id
            else "待人工方案评审"
        )
        display_kind = "solution_review_gate"
    else:
        title = reason or (f"{node_label} 需人工处理" if node_id else "需要人工处理")
        display_kind = "human_gate"

    lines = [title]
    if node_id:
        lines.append(f"节点：{node_label}（{node_id}）")
    if kind:
        lines.append(f"类型：{_intervention_kind_label(kind)}")

    dur = ev.get("duration_seconds")
    if dur is not None and str(dur).strip() not in ("", "None"):
        lines.append(f"本节点已运行 {dur}s")
    tok = ev.get("tokens_used")
    if tok is not None and str(tok).strip() not in ("", "None"):
        lines.append(f"Token 消耗：{tok}")

    payload: dict[str, Any] = {
        "room_id": str(ev.get("room_id") or ""),
        "node_id": node_id,
        "node_label": node_label,
        "intervention_kind": kind,
        "intervention_kind_label": _intervention_kind_label(kind),
        "reason": reason or title,
    }
    if dur is not None:
        payload["duration_seconds"] = dur
    if tok is not None:
        payload["tokens_used"] = tok

    return [
        _host_row(
            ev,
            index,
            text="\n".join(lines),
            display_kind=display_kind,
            host_id=host_id,
            payload=payload,
        )
    ]


def _participants_payload(ev: dict[str, Any]) -> dict[str, Any]:
    binding = ev.get("binding") if isinstance(ev.get("binding"), dict) else {}
    participants = ev.get("participants") if isinstance(ev.get("participants"), list) else []
    workers = binding.get("worker_profile_ids")
    if workers is None and participants:
        host_pid = str(binding.get("host_profile_id") or ev.get("agent_id") or "default")
        workers = [
            str(p.get("profile_id") or "")
            for p in participants
            if isinstance(p, dict)
            and str(p.get("profile_id") or "") != host_pid
            and str(p.get("role") or "") != "host"
        ]
    return {
        "room_id": str(ev.get("room_id") or ""),
        "node_id": str(ev.get("node_id") or ""),
        "host_profile_id": str(binding.get("host_profile_id") or ev.get("agent_id") or "default"),
        "worker_profile_ids": list(workers or []),
        "participants": participants,
        "log_type": str(ev.get("log_type") or "info"),
        "agent_id": str(ev.get("agent_id") or "default"),
    }


def _append_participants_chat_row(
    out: list[dict[str, Any]],
    ev: dict[str, Any],
    index: int,
    *,
    suffix: str = "-roster",
) -> None:
    """参会阵容：node_init 后展示（系统节点展示系统执行方）。"""
    if ev.get("system_node"):
        part = _participants_payload(ev)
        out.append(
            _row(
                ev,
                index,
                text="系统执行方",
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="system_roster",
                payload={**part, "system_node": True},
                suffix=suffix,
            )
        )
        return
    part = _participants_payload(ev)
    if not (part.get("worker_profile_ids") or part.get("participants")):
        return
    out.append(
        _row(
            ev,
            index,
            text="参会人员名单",
            agent_id=SPEAKER_SYSTEM,
            speaker_role=SPEAKER_SYSTEM,
            display_kind="participants",
            payload=part,
            suffix=suffix,
        )
    )


def _expand_node_init(ev: dict[str, Any], index: int, host_id: str) -> list[dict[str, Any]]:
    """node_init：节点上下文 + 流程说明「节点初始化」+ 参会人员名单（仅此处）。"""
    _ = host_id
    out: list[dict[str, Any]] = []
    raw_text = str(ev.get("text") or "").strip()
    obj = _try_parse_json(raw_text)
    if obj and _is_node_context_payload(obj):
        out.append(
            _row(
                ev,
                index,
                text="节点基础信息（工单 / 产品 / 系统）",
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="node_context",
                payload=obj,
                suffix="-ctx",
            )
        )
    summary = format_event_chat_display(ev)
    if summary:
        out.append(
            _row(
                ev,
                index,
                text=summary,
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="pipeline",
                suffix="-pipe",
            )
        )
    _append_participants_chat_row(out, ev, index)
    return out


def _expand_node_started(ev: dict[str, Any], index: int, host_id: str) -> list[dict[str, Any]]:
    """node_started：运行态事件，参会名单已在 node_init 展示，协作流不再重复。"""
    _ = host_id
    _ = index
    _ = ev
    return []


def expand_history_event_to_chat(ev: dict[str, Any], index: int) -> list[dict[str, Any]]:
    """单条 history → 0..n 条 UI chat log。"""
    et = str(ev.get("event") or "")
    if et not in CHAT_VISIBLE_EVENTS or et in CHAT_SKIP_EVENTS:
        return []

    host_id = str(ev.get("agent_id") or "default")

    if et == "human_intervene":
        text = format_event_chat_display(ev)
        if not text:
            return []
        return [
            _row(
                ev,
                index,
                text=text,
                agent_id="user",
                speaker_role=SPEAKER_USER,
                display_kind="plain",
            )
        ]

    if et == "node_init":
        return _expand_node_init(ev, index, host_id)

    if et == "system_node_executed":
        payload = ev.get("result") if isinstance(ev.get("result"), dict) else {}
        out: list[dict[str, Any]] = []
        summary = format_event_chat_display(ev)
        if summary:
            out.append(
                _row(
                    ev,
                    index,
                    text=summary,
                    agent_id=SPEAKER_SYSTEM,
                    speaker_role=SPEAKER_SYSTEM,
                    display_kind="pipeline",
                    suffix="-pipe",
                )
            )
        if payload:
            out.append(
                _row(
                    ev,
                    index,
                    text="系统节点执行结果",
                    agent_id=SPEAKER_SYSTEM,
                    speaker_role=SPEAKER_SYSTEM,
                    display_kind="system_exec",
                    payload=payload,
                    suffix="-exec",
                )
            )
        return out

    if et == "node_started":
        return _expand_node_started(ev, index, host_id)

    if et == "work_plan_submitted":
        text = _unwrap_message_body(str(ev.get("text") or format_event_chat_display(ev) or ""))
        if not text:
            return []
        return [
            _host_row(
                ev,
                index,
                text=text,
                display_kind="work_plan",
                host_id=host_id,
                payload={
                    "room_id": str(ev.get("room_id") or ""),
                    "node_id": str(ev.get("node_id") or ""),
                    "plan_id": ev.get("plan_id"),
                    "item_count": ev.get("item_count"),
                },
                rich=True,
            )
        ]

    if et == "delegation_started":
        text = format_event_chat_display(ev)
        if not text:
            return []
        payload = {
            "headline": text.split("\n")[0] if text else "",
            "plan_item_id": str(ev.get("plan_item_id") or ""),
            "reason": str(ev.get("reason") or ""),
            "task_preview": str(ev.get("task_preview") or ""),
            "to_agent": str(ev.get("to_agent") or ""),
            "from_agent": str(ev.get("from_agent") or host_id),
        }
        return [
            _host_row(
                ev,
                index,
                text=text,
                display_kind="delegation_start",
                host_id=host_id,
                payload=payload,
            )
        ]

    if et == "delegation_finished":
        text = format_event_chat_display(ev)
        if not text:
            return []
        worker_id = str(ev.get("to_agent") or ev.get("agent_id") or "worker")
        payload = {
            "headline": text.split("\n")[0] if text else "",
            "ok": bool(ev.get("ok", True)),
            "status": str(ev.get("status") or ""),
            "result_summary": str(ev.get("result_summary") or ""),
            "elapsed_s": ev.get("elapsed_s"),
            "to_agent": worker_id,
        }
        return [
            _row(
                ev,
                index,
                text=text,
                agent_id=worker_id,
                speaker_role=SPEAKER_WORKER,
                display_kind="delegation_done",
                payload=payload,
            )
        ]

    if et == "hitl_dynamic":
        detail = str(ev.get("detail") or format_event_chat_display(ev) or "").strip()
        if not detail:
            return []
        return [
            _host_row(
                ev,
                index,
                text=detail,
                display_kind="hitl_tool",
                host_id=host_id,
                payload={
                    "room_id": str(ev.get("room_id") or ""),
                    "node_id": str(ev.get("node_id") or ""),
                    "source": str(ev.get("source") or "tool"),
                },
            )
        ]

    if et in ("host_llm_end", "human_gate") and str(ev.get("report_preview") or "").strip():
        preview = str(ev.get("report_preview") or "")[:800]
        payload = {
            k: ev[k]
            for k in (
                "room_id",
                "node_id",
                "report_preview",
                "success",
                "host_profile_id",
            )
            if k in ev
        }
        return [
            _row(
                ev,
                index,
                text=preview,
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="human_report",
                payload=payload,
            )
        ]

    if et == "node_pending_confirm":
        payload = {
            k: ev[k]
            for k in (
                "room_id",
                "node_id",
                "duration_seconds",
                "dynamic_form",
                "source",
                "review_summary_count",
                "review_artifact_count",
            )
            if k in ev
        }
        dur = payload.get("duration_seconds", "?")
        text = f"等待问卷反馈 · 已运行 {dur}s"
        return [
            _host_row(
                ev,
                index,
                text=text,
                display_kind="pending_confirm",
                host_id=host_id,
                payload=payload,
            )
        ]

    if et == "human_gate" and str(ev.get("intervention_kind") or "") == "solution_review":
        return []

    if et in ("human_gate", "solution_review_gate"):
        return _expand_intervention_gate(ev, index, host_id)

    if et == "host_llm_begin":
        display = format_event_chat_display(ev)
        if not display:
            return []
        return [
            _host_row(
                ev,
                index,
                text=display,
                display_kind="pipeline",
                host_id=host_id,
            )
        ]

    raw_text = str(ev.get("text") or "").strip()
    obj = _try_parse_json(raw_text) if raw_text else None

    # node_started 的 text 含 order/product JSON：勿再生成 node_context（已在 node_init）
    if et == "node_started":
        return []

    if obj and _is_node_context_payload(obj) and et != "node_init":
        return [
            _row(
                ev,
                index,
                text="节点基础信息（工单 / 产品 / 系统）",
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="node_context",
                payload=obj,
            )
        ]

    if obj and _is_participants_meta(obj) and et not in ("node_started", "node_init"):
        return [
            _row(
                ev,
                index,
                text="参会人员名单",
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="participants",
                payload=obj,
            )
        ]

    if obj and _is_human_report_meta(obj):
        preview = str(obj.get("report_preview") or obj.get("message") or "")[:500]
        return [
            _row(
                ev,
                index,
                text=preview or "人工确认门控",
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="human_report",
                payload=obj,
            )
        ]

    if obj and et == "work_plan_submitted":
        body = _unwrap_message_body(raw_text)
        if body:
            return [
                _host_row(
                    ev,
                    index,
                    text=body,
                    display_kind="work_plan",
                    host_id=host_id,
                    rich=True,
                )
            ]

    if obj and et not in ("host_prompt_assembled",):
        body = _unwrap_message_body(raw_text)
        if body.strip().startswith("# 工作安排计划"):
            return [
                _host_row(
                    ev,
                    index,
                    text=body,
                    display_kind="work_plan",
                    host_id=host_id,
                    rich=True,
                )
            ]
        return [
            _row(
                ev,
                index,
                text=str(resolve_flow_stage_label(et)),
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="flow_meta",
                payload=obj,
            )
        ]

    display = _unwrap_message_body(format_event_chat_display(ev))
    if not display:
        return []

    if et in SYSTEM_PIPELINE_EVENTS or (
        _looks_like_pipeline_chat(display, et) and et not in ("host_llm_begin", "host_llm_end")
    ):
        return [
            _row(
                ev,
                index,
                text=display,
                agent_id=SPEAKER_SYSTEM,
                speaker_role=SPEAKER_SYSTEM,
                display_kind="pipeline",
            )
        ]

    if et in ("host_llm_end", "chat_message") or (
        et == "host_prompt_assembled" and host_id != "system"
    ):
        return [
            _host_row(
                ev,
                index,
                text=display,
                display_kind="pipeline" if _looks_like_pipeline_chat(display, et) else "plain",
                host_id=host_id,
            )
        ]

    if display.strip().startswith("# 工作安排计划"):
        return [
            _host_row(
                ev,
                index,
                text=display,
                display_kind="work_plan",
                host_id=host_id,
                rich=True,
            )
        ]

    return [
        _row(
            ev,
            index,
            text=display,
            agent_id=SPEAKER_SYSTEM,
            speaker_role=SPEAKER_SYSTEM,
            display_kind="plain",
        )
    ]


def resolve_flow_stage_label(event_type: str) -> str:
    from synapse.rd_meeting.flow_log import EVENT_FLOW_STAGE

    return EVENT_FLOW_STAGE.get(event_type, event_type or "流程")


def _looks_like_pipeline_chat(text: str, event_type: str) -> bool:
    if event_type in (
        "room_opened",
        "node_init",
        "system_node_executed",
        "host_prompt_assembled",
        "host_llm_begin",
        "phase_change",
    ):
        return True
    first = (text or "").split("\n")[0].strip()
    return first in (
        "开启会议室",
        "节点初始化",
        "主控提示词组装",
        "流程待机",
        "主控触发执行",
        "主控触发总结",
        "主控推理开始",
    )


def history_to_chat_logs(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """会议室 UI chat log（结构化展示 + 系统/主持/协作角色）。"""
    logs: list[dict[str, Any]] = []
    for i, ev in enumerate(history):
        if not isinstance(ev, dict):
            continue
        logs.extend(expand_history_event_to_chat(ev, i))
    return logs
