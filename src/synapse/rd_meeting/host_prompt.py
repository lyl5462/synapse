"""第三步：组装研发会议室主控（小鲸）提示词，并生成协作会议流展示文案。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.dynamic_prompt import build_dynamic_meeting_context, build_meeting_user_turn_prompt
from synapse.rd_meeting.init_context import build_node_init_log_data
from synapse.rd_meeting.paths import scope_dir
from synapse.rd_meeting.pipeline_chat import format_host_prompt_step_chat
from synapse.rd_meeting.room_skill import build_room_skill_prompt, load_meeting_skill_body, make_context
from synapse.rd_sop.nodes import node_display_name, stage_id_for_node_id

ScopeType = Literal["demand", "task"]


def assemble_host_prompt_bundle(
    *,
    scope_type: ScopeType,
    scope_id: str,
    node_id: str,
    binding: dict[str, Any] | None = None,
    ticket_title: str = "",
) -> dict[str, Any]:
    """组装主控提示词：仅 meeting-room SKILL + 四段式动态上下文（唯一注入点）。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    bind = dict(binding) if binding else resolve_node_binding(
        nid,
        scope_type=scope_type,
        scope_id=sid,
        ticket_title=ticket_title,
    )
    bind["node_id"] = nid
    stg = int(bind.get("stage_id") or stage_id_for_node_id(nid))

    dev = load_dev_status(sid)
    sop_display = str(dev.get("sop_node_display") or "") if dev else ""

    init_data = build_node_init_log_data(scope_type, sid, node_id=nid)
    dynamic_context = build_dynamic_meeting_context(
        binding=bind,
        init_data=init_data,
        scope_type=scope_type,
        scope_id=sid,
        sop_node_display=sop_display,
    )

    skill_body = load_meeting_skill_body(str(bind.get("meeting_skill_id") or ""))
    ctx = make_context(
        role="host",
        binding=bind,
        scope_type=scope_type,
        scope_id=sid,
        ticket_title=ticket_title,
        archive_dir=str(scope_dir(sid) / str(stg) / nid) if sid and nid else "",
    )
    meeting_prompt = build_room_skill_prompt(
        ctx,
        skill_body=skill_body,
        init_context=init_data,
        binding=bind,
        sop_node_display=sop_display,
    )
    user_prompt = build_meeting_user_turn_prompt()

    host_id = str(bind.get("host_profile_id") or "default")
    worker_ids = [
        str(w).strip()
        for w in (bind.get("worker_profile_ids") or [])
        if str(w).strip() and str(w).strip() != host_id
    ]

    return {
        "scope_type": scope_type,
        "scope_id": sid,
        "node_id": nid,
        "node_name": str(bind.get("node_name") or node_display_name(nid)),
        "host_profile_id": host_id,
        "worker_profile_ids": worker_ids,
        "meeting_skill_id": str(bind.get("meeting_skill_id") or ""),
        "dynamic_context": dynamic_context,
        "meeting_prompt": meeting_prompt,
        "user_prompt": user_prompt,
        "init_context": init_data,
        "sop_node_display": sop_display,
    }


def format_host_prompt_chat_display(bundle: dict[str, Any] | None = None) -> str:
    """协作会议流：步骤 3 流程说明（实例数据见快照 ``host_prompt_snapshot.md``）。"""
    _ = bundle
    return format_host_prompt_step_chat()


def format_host_prompt_snapshot(bundle: dict[str, Any]) -> str:
    """落盘：完整系统提示（含四段式 + SKILL），供排查。"""
    meeting_txt = str(bundle.get("meeting_prompt") or "").strip()
    user_txt = str(bundle.get("user_prompt") or "").strip()
    return "\n".join(
        [
            "# 主控系统提示（meeting-room SKILL 注入后）",
            "",
            meeting_txt or "（空）",
            "",
            "---",
            "",
            "# 首轮 User",
            "",
            user_txt or "（空）",
        ]
    )


def save_host_prompt_snapshot(scope_id: str, bundle: dict[str, Any]) -> str:
    """落盘完整快照，便于排查（返回文件路径字符串）。"""
    sid = (scope_id or "").strip()
    if not sid:
        return ""
    path = scope_dir(sid) / "host_prompt_snapshot.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_host_prompt_snapshot(bundle), encoding="utf-8")
    return str(path)
