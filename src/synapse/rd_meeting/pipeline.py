"""研发会议室 SOP 主流程 Pipeline（按 scope 缓存 meeting_pipeline.json）。

``flow_step`` 标识**下一步**要执行的流程动作；执行器根据该字段调度具体逻辑。
本模块是会议室流程的单一入口，后续步骤在此扩展并登记 ``FLOW_STEP_REGISTRY``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from synapse.rd_meeting.bootstrap import append_host_prompt_chat, append_node_init_chat
from synapse.rd_meeting.host_prompt import assemble_host_prompt_bundle, save_host_prompt_snapshot
from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.pipeline_chat import (
    format_phase_change_chat,
    format_room_opened_chat,
    format_run_node_scheduled_chat,
)
from synapse.rd_meeting.dev_status import (
    ensure_room_id,
    load_dev_status,
    load_or_create_dev_status,
    save_dev_status,
)
from synapse.rd_meeting.participants import build_meeting_participants
from synapse.rd_meeting.paths import meeting_pipeline_path, scope_dir
from synapse.rd_meeting.room_runtime import (
    append_history_event,
    load_room_state,
    read_json_file,
    save_room_state,
    sync_room_state_from_dev,
    write_json_file,
)
from synapse.rd_meeting.userwork_sync import build_title_index, patch_userwork_summary
from synapse.rd_sop.nodes import (
    node_display_name,
    resolve_sop_raw_to_node_id,
    stage_id_for_node_id,
)

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]
PipelinePhase = Literal[
    "idle",
    "running",
    "clarify_gate",
    "result_gate",
    "exception_gate",
    "document",
    "completed",
    "waiting",
]

PIPELINE_SCHEMA_VERSION = 1

# --- 流程标识（flow_step）：下一步要做什么 ---
STEP_IDLE = "idle"
STEP_OPEN_MEETING = "open_meeting"
STEP_NODE_INIT = "node_init"
STEP_ASSEMBLE_HOST_PROMPT = "assemble_host_prompt"
STEP_RUN_NODE_SCHEDULE = "run_node_schedule"
STEP_RUN_NODE = "run_node"
STEP_WAITING = "waiting"
STEP_DONE = "done"

_VALID_FLOW_STEPS = frozenset(
    {
        STEP_IDLE,
        STEP_OPEN_MEETING,
        STEP_NODE_INIT,
        STEP_ASSEMBLE_HOST_PROMPT,
        STEP_RUN_NODE_SCHEDULE,
        STEP_RUN_NODE,
        STEP_WAITING,
        STEP_DONE,
    }
)

_VALID_PHASES = frozenset(
    {
        "idle",
        "running",
        "clarify_gate",
        "result_gate",
        "exception_gate",
        "document",
        "completed",
        "waiting",
    }
)

# 流程标识 → 人类可读标签（流程日志 / 排查）
FLOW_STEP_LABEL: dict[str, str] = {
    STEP_IDLE: "空闲",
    STEP_OPEN_MEETING: "开启会议室",
    STEP_NODE_INIT: "节点初始化",
    STEP_ASSEMBLE_HOST_PROMPT: "主控提示词组装",
    STEP_RUN_NODE_SCHEDULE: "调度节点执行",
    STEP_RUN_NODE: "执行当前节点",
    STEP_WAITING: "流程待机",
    STEP_DONE: "流程结束",
}

# 登记：某步完成后默认进入的下一步（可被 handler 覆盖）
FLOW_STEP_NEXT: dict[str, str] = {
    STEP_OPEN_MEETING: STEP_NODE_INIT,
    STEP_NODE_INIT: STEP_ASSEMBLE_HOST_PROMPT,
    STEP_ASSEMBLE_HOST_PROMPT: STEP_WAITING,
    STEP_RUN_NODE_SCHEDULE: STEP_RUN_NODE,
    STEP_RUN_NODE: STEP_WAITING,
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_pipeline_state(
    *,
    scope_type: ScopeType,
    scope_id: str,
    room_id: str = "",
    current_node_id: str = "pending",
    flow_step: str = STEP_OPEN_MEETING,
    phase: str = "idle",
) -> dict[str, Any]:
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "room_id": room_id,
        "current_node_id": current_node_id,
        "flow_step": flow_step,
        "phase": phase,
        "steps_completed": [],
        "context": {},
        "updated_at": _now_iso(),
    }


class MeetingPipeline:
    """单次会议 scope 的 pipeline 状态（读写 meeting_pipeline.json）。"""

    def __init__(self, scope_id: str, data: dict[str, Any]) -> None:
        self.scope_id = scope_id.strip()
        self._data = data

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @property
    def flow_step(self) -> str:
        step = str(self._data.get("flow_step") or STEP_IDLE)
        return step if step in _VALID_FLOW_STEPS else STEP_IDLE

    @flow_step.setter
    def flow_step(self, value: str) -> None:
        self._data["flow_step"] = value if value in _VALID_FLOW_STEPS else STEP_WAITING

    @property
    def phase(self) -> str:
        ph = str(self._data.get("phase") or "idle")
        return ph if ph in _VALID_PHASES else "idle"

    @phase.setter
    def phase(self, value: str) -> None:
        self._data["phase"] = value if value in _VALID_PHASES else "idle"

    @property
    def room_id(self) -> str:
        return str(self._data.get("room_id") or "")

    @property
    def current_node_id(self) -> str:
        return str(self._data.get("current_node_id") or "pending")

    def mark_step_completed(self, step_id: str) -> None:
        done = self._data.get("steps_completed")
        if not isinstance(done, list):
            done = []
        if step_id not in done:
            done.append(step_id)
        self._data["steps_completed"] = done

    def set_flow_step(self, step: str, *, reason: str = "") -> None:
        prev = self.flow_step
        self.flow_step = step
        self._data["updated_at"] = _now_iso()
        if reason:
            ctx = self._data.get("context")
            if not isinstance(ctx, dict):
                ctx = {}
            ctx["last_transition_reason"] = reason
            self._data["context"] = ctx
        if prev != step:
            self._log_flow_transition(prev, step, reason)

    def set_phase(self, phase: str, *, sync_room_state: bool = True) -> None:
        prev = self.phase
        self.phase = phase
        self._data["updated_at"] = _now_iso()
        if sync_room_state and prev != phase:
            rs = dict(load_room_state(self.scope_id) or {})
            rs["phase"] = phase
            save_room_state(self.scope_id, rs)
            host_id = _host_profile_id_for_scope(
                self.scope_id,
                node_id=self.current_node_id,
                scope_type=str(self._data.get("scope_type") or "demand"),
            )
            row: dict[str, Any] = {
                "event": "phase_change",
                "room_id": self.room_id,
                "from_phase": prev,
                "to_phase": phase,
                "log_type": "info",
                "agent_id": host_id,
                "flow_stage": "阶段切换",
            }
            phase_chat = format_phase_change_chat(to_phase=phase)
            if phase_chat:
                row["chat_text"] = phase_chat
            append_history_event(self.scope_id, row)

    def _log_flow_transition(self, from_step: str, to_step: str, reason: str) -> None:
        """仅更新 pipeline 内存状态；不再写入 ``pipeline_transition`` 会议流事件。"""
        _ = from_step, to_step, reason

    @classmethod
    def load(cls, scope_id: str) -> MeetingPipeline | None:
        sid = (scope_id or "").strip()
        if not sid:
            return None
        raw = read_json_file(meeting_pipeline_path(sid))
        if not raw:
            return None
        return cls(sid, raw)

    @classmethod
    def load_or_create(
        cls,
        scope_id: str,
        *,
        scope_type: ScopeType = "demand",
        flow_step: str = STEP_OPEN_MEETING,
    ) -> MeetingPipeline:
        existing = cls.load(scope_id)
        if existing is not None:
            return existing
        pipe = cls(
            scope_id,
            default_pipeline_state(
                scope_type=scope_type,
                scope_id=scope_id,
                flow_step=flow_step,
            ),
        )
        pipe.save()
        return pipe

    def save(self) -> None:
        self._data["updated_at"] = _now_iso()
        path = meeting_pipeline_path(self.scope_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(path, self._data)

    def snapshot_for_api(self) -> dict[str, Any]:
        return {
            "flow_step": self.flow_step,
            "flow_step_label": FLOW_STEP_LABEL.get(self.flow_step, self.flow_step),
            "phase": self.phase,
            "room_id": self.room_id,
            "current_node_id": self.current_node_id,
            "steps_completed": list(self._data.get("steps_completed") or []),
            "updated_at": self._data.get("updated_at"),
        }


@dataclass
class PipelineRunContext:
    """单次 pipeline 执行上下文。"""

    scope_type: ScopeType
    scope_id: str
    sync_userwork: bool = True
    promote_to_processing: bool = True
    auto_run_first_node: bool = False
    prod: str = ""
    agent_pool: Any | None = None
    # 由步骤写入，供返回 API
    dev_status: dict[str, Any] = field(default_factory=dict)
    room_state: dict[str, Any] | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    auto_run_started: bool = False


StepHandler = Callable[[MeetingPipeline, PipelineRunContext], None]


def _host_profile_id_for_scope(
    scope_id: str,
    *,
    node_id: str = "",
    scope_type: ScopeType = "demand",
) -> str:
    """当前节点 binding 中的主控 profile（默认小鲸 ``default``）。"""
    nid = (node_id or "").strip()
    if not nid or nid == "pending":
        dev = load_dev_status(scope_id)
        if dev:
            nid = str(dev.get("current_node_id") or "").strip()
    if not nid or nid == "pending":
        nid = "req_clarify"
    try:
        binding = resolve_node_binding(nid, scope_type=scope_type, scope_id=scope_id)
        return str(binding.get("host_profile_id") or "default").strip() or "default"
    except Exception:
        return "default"


def _resolve_open_node(
    scope_type: ScopeType,
    scope_id: str,
    *,
    promote: bool,
) -> tuple[str, int, str]:
    node_id = "pending"
    stage_id = 0
    from synapse.rd_meeting.service import MeetingRoomService

    snap = MeetingRoomService()._userwork_row_for_scope(scope_type, scope_id)
    if snap:
        sop_raw = str(snap.get("sop_node") or "").strip()
        resolved = resolve_sop_raw_to_node_id(sop_raw)
        if resolved:
            node_id = resolved
            stage_id = stage_id_for_node_id(node_id)
    if promote and (stage_id <= 0 or node_id in ("pending", "")):
        node_id = "req_clarify"
        stage_id = stage_id_for_node_id(node_id)
    sop_display = node_display_name(node_id) if node_id not in ("pending", "") else "等待调度"
    return node_id, stage_id, sop_display


def _step_open_meeting(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """第一步：开启会议室 + userwork 回写。"""
    sid = ctx.scope_id
    scope_type = ctx.scope_type
    local = "处理中"
    node_id, stage_id, sop_display = _resolve_open_node(
        scope_type, sid, promote=ctx.promote_to_processing
    )

    existing = load_dev_status(sid)
    if existing is not None:
        data = dict(existing)
    else:
        data = load_or_create_dev_status(
            sid,
            scope_type=scope_type,
            local_process_state=local,
            stage_id=stage_id,
            current_node_id=node_id,
            sop_node_display=sop_display,
            pipeline_enabled=True,
        )
    data["local_process_state"] = local
    data["pipeline_enabled"] = True
    data["stage_id"] = stage_id
    data["current_node_id"] = node_id
    data["sop_node_display"] = sop_display
    mr = data.get("meeting_room")
    if not isinstance(mr, dict):
        mr = {}
    data["meeting_room"] = {**mr, "active": True}
    data = ensure_room_id(data)
    save_dev_status(sid, data)
    scope_dir(sid).mkdir(parents=True, exist_ok=True)

    room_id = str(data["meeting_room"].get("room_id") or "")
    room_state = sync_room_state_from_dev(
        sid,
        room_id=room_id,
        scope_type=scope_type,
        stage_id=int(data.get("stage_id") or 0),
        current_node_id=str(data.get("current_node_id") or "pending"),
        local_process_state=local,
    )

    prod = (ctx.prod or "").strip()
    if not prod:
        raise ValueError("请选择产品（prod 不能为空）")

    from synapse.rd_meeting.product_context import (
        ensure_prod_in_catalog,
        save_prod_catalog_to_pipeline,
    )

    catalog_rows, catalog_err = ensure_prod_in_catalog(prod)
    if catalog_err:
        raise ValueError(catalog_err)

    userwork_updates: dict[str, str] = {}
    if ctx.sync_userwork:
        userwork_updates = patch_userwork_summary(
            scope_type=scope_type,
            scope_id=sid,
            sop_node=sop_display,
            local_process_state=local,
            prod=prod,
        )
    else:
        userwork_updates = {"prod": prod}

    save_prod_catalog_to_pipeline(sid, catalog_rows, selected_prod=prod)

    open_binding = resolve_node_binding(
        node_id,
        scope_type=scope_type,
        scope_id=sid,
    )
    host_id = str(open_binding.get("host_profile_id") or "default").strip() or "default"

    append_history_event(
        sid,
        {
            "event": "room_opened",
            "room_id": room_id,
            "scope_id": sid,
            "current_node_id": node_id,
            "sop_display": sop_display,
            "userwork_updates": userwork_updates,
            "chat_text": format_room_opened_chat(),
            "flow_stage": "开启会议室",
            "log_type": "info",
            "agent_id": host_id,
        },
    )

    pipe._data["room_id"] = room_id
    pipe._data["current_node_id"] = node_id
    pipe._data["scope_type"] = scope_type
    pipe.set_phase("idle", sync_room_state=True)

    titles = build_title_index()
    from synapse.rd_meeting.service import MeetingRoomService

    svc = MeetingRoomService()
    detail = svc._room_detail_payload(data, sid, titles)
    detail["room_state"] = room_state
    detail["pipeline"] = pipe.snapshot_for_api()

    ctx.dev_status = data
    ctx.room_state = room_state
    ctx.detail = detail

    pipe.mark_step_completed(STEP_OPEN_MEETING)
    nxt = FLOW_STEP_NEXT[STEP_OPEN_MEETING]
    pipe.set_flow_step(nxt, reason="开启会议室完成")


def _step_node_init(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """第二步：节点初始化（userwork 上下文日志，不含主控 prompt）。"""
    sid = ctx.scope_id
    data = ctx.dev_status
    if not data:
        data = load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    run_node = pipe.current_node_id or str(data.get("current_node_id") or "")
    if run_node in ("pending", ""):
        pipe.mark_step_completed(STEP_NODE_INIT)
        pipe.set_flow_step(STEP_WAITING, reason="无有效节点，跳过初始化")
        return

    scope_type = ctx.scope_type
    ticket_title = str(ctx.detail.get("ticket_title") or "")
    run_binding = resolve_node_binding(
        run_node,
        scope_type=scope_type,
        scope_id=sid,
        ticket_title=ticket_title,
    )
    run_binding["node_id"] = run_node
    append_node_init_chat(
        sid,
        room_id=room_id,
        node_id=run_node,
        binding=run_binding,
        scope_type=scope_type,
    )
    rs = load_room_state(sid) or {}
    if isinstance(rs, dict):
        rs = dict(rs)
        rs["participants"] = build_meeting_participants(run_binding)
        save_room_state(sid, rs)
        ctx.room_state = rs

    pipe.mark_step_completed(STEP_NODE_INIT)
    pipe.set_flow_step(
        FLOW_STEP_NEXT[STEP_NODE_INIT],
        reason="节点初始化完成，进入主控提示词组装",
    )


def _step_assemble_host_prompt(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """第三步：组装小鲸主控提示词并写入协作会议流（完整展示）。"""
    sid = ctx.scope_id
    data = ctx.dev_status
    if not data:
        data = load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    run_node = pipe.current_node_id or str(data.get("current_node_id") or "")
    scope_type = ctx.scope_type
    ticket_title = str(ctx.detail.get("ticket_title") or "")

    if run_node in ("pending", ""):
        pipe.mark_step_completed(STEP_ASSEMBLE_HOST_PROMPT)
        pipe.set_flow_step(STEP_WAITING, reason="无有效节点，跳过主控提示词组装")
        return

    run_binding = resolve_node_binding(
        run_node,
        scope_type=scope_type,
        scope_id=sid,
        ticket_title=ticket_title,
    )
    run_binding["node_id"] = run_node

    bundle = assemble_host_prompt_bundle(
        scope_type=scope_type,
        scope_id=sid,
        node_id=run_node,
        binding=run_binding,
        ticket_title=ticket_title,
    )
    snapshot_path = save_host_prompt_snapshot(sid, bundle)
    append_host_prompt_chat(
        sid,
        room_id=room_id,
        scope_type=scope_type,
        node_id=run_node,
        binding=run_binding,
        ticket_title=ticket_title,
    )

    pctx = pipe._data.get("context")
    if not isinstance(pctx, dict):
        pctx = {}
    pctx["host_prompt"] = {
        "node_id": run_node,
        "snapshot_path": snapshot_path,
        "dynamic_chars": len(str(bundle.get("dynamic_context") or "")),
        "meeting_prompt_chars": len(str(bundle.get("meeting_prompt") or "")),
        "user_chars": len(str(bundle.get("user_prompt") or "")),
        "skill_id": str(bundle.get("meeting_skill_id") or ""),
        "host_profile_id": str(bundle.get("host_profile_id") or ""),
    }
    pipe._data["context"] = pctx

    pipe.mark_step_completed(STEP_ASSEMBLE_HOST_PROMPT)
    if ctx.auto_run_first_node:
        pipe.set_flow_step(STEP_RUN_NODE_SCHEDULE, reason="主控提示词已组装，待调度执行")
    else:
        pipe.set_phase("waiting", sync_room_state=True)
        pipe.set_flow_step(STEP_WAITING, reason="主控提示词已组装，流程待机")


def _step_run_node_schedule(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """调度后台执行当前节点（可选，由 auto_run 触发）。"""
    from synapse.rd_meeting.orchestrator import schedule_run_node

    sid = ctx.scope_id
    room_id = pipe.room_id
    host_id = _host_profile_id_for_scope(
        sid,
        node_id=pipe.current_node_id,
        scope_type=ctx.scope_type,
    )
    append_history_event(
        sid,
        {
            "event": "run_node_scheduled",
            "room_id": room_id,
            "scope_type": ctx.scope_type,
            "current_node_id": pipe.current_node_id,
            "trigger": "pipeline_run_node_schedule",
            "chat_text": format_run_node_scheduled_chat(),
            "log_type": "info",
            "agent_id": host_id,
        },
    )
    schedule_run_node(
        scope_type=ctx.scope_type,
        scope_id=sid,
        room_id=room_id,
        ticket_title=str(ctx.detail.get("ticket_title") or ""),
        agent_pool=ctx.agent_pool,
        dry_run=None,
    )
    pipe.mark_step_completed(STEP_RUN_NODE_SCHEDULE)
    pipe.set_phase("running", sync_room_state=True)
    pipe.set_flow_step(STEP_RUN_NODE, reason="已调度 run_node")
    ctx.auto_run_started = True
    ctx.detail["auto_run_started"] = True


# 流程标识 → 执行函数（主流程登记表，新增步骤在此挂载）
FLOW_STEP_HANDLERS: dict[str, StepHandler] = {
    STEP_OPEN_MEETING: _step_open_meeting,
    STEP_NODE_INIT: _step_node_init,
    STEP_ASSEMBLE_HOST_PROMPT: _step_assemble_host_prompt,
    STEP_RUN_NODE_SCHEDULE: _step_run_node_schedule,
    # STEP_RUN_NODE: 仍由 orchestrator.run_current_node 执行，后续迁入
}


def run_pipeline_until_waiting(
    ctx: PipelineRunContext,
    *,
    initial_flow_step: str = STEP_OPEN_MEETING,
) -> MeetingPipeline:
    """从 ``initial_flow_step`` 起连续执行，直到 ``flow_step`` 为 waiting/done 或无 handler。"""
    pipe = MeetingPipeline.load_or_create(
        ctx.scope_id,
        scope_type=ctx.scope_type,
        flow_step=initial_flow_step,
    )
    guard = 0
    while pipe.flow_step not in (STEP_WAITING, STEP_DONE, STEP_IDLE) and guard < 16:
        guard += 1
        handler = FLOW_STEP_HANDLERS.get(pipe.flow_step)
        if handler is None:
            logger.info(
                "pipeline: no handler for flow_step=%s scope=%s",
                pipe.flow_step,
                ctx.scope_id,
            )
            break
        handler(pipe, ctx)
        pipe.save()
    ctx.detail["pipeline"] = pipe.snapshot_for_api()
    return pipe


def get_flow_step(scope_id: str) -> str:
    pipe = MeetingPipeline.load(scope_id)
    return pipe.flow_step if pipe else STEP_IDLE


def set_flow_step(scope_id: str, step: str, *, reason: str = "") -> None:
    pipe = MeetingPipeline.load_or_create(scope_id)
    pipe.set_flow_step(step, reason=reason)
    pipe.save()
