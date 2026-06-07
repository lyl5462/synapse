"""研发会议室 SOP 主流程 Pipeline（按 scope 缓存 meeting_pipeline.json）。

``flow_step`` 标识**下一步**要执行的流程动作；执行器根据该字段调度具体逻辑。
本模块是会议室流程的单一入口，后续步骤在此扩展并登记 ``FLOW_STEP_REGISTRY``。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Literal

from synapse.rd_meeting.bootstrap import (
    append_host_prompt_chat,
    append_node_init_chat,
    append_system_node_init_chat,
)
from synapse.rd_meeting.host_prompt import assemble_host_prompt_bundle, save_host_prompt_snapshot
from synapse.rd_meeting.host_prompt_cache import save_host_prompt_cache
from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.pipeline_chat import format_room_opened_chat
from synapse.rd_meeting.dev_status import (
    ensure_room_id,
    load_dev_status,
    load_or_create_dev_status,
    save_dev_status,
)
from synapse.rd_meeting.participants import build_meeting_participants
from synapse.rd_meeting.paths import (
    agent_sop_node_dir,
    archive_node_dir,
    meeting_pipeline_path,
    scope_dir,
)
from synapse.rd_meeting.room_runtime import (
    append_history_event,
    load_room_state,
    read_json_file,
    save_room_state,
    sync_room_state_from_dev,
    write_json_file,
)
from synapse.rd_meeting.userwork_sync import build_title_index, patch_userwork_summary
from synapse.rd_sop.manifest import is_system_node
from synapse.rd_sop.nodes import (
    ALL_NODES,
    node_display_name,
    resolve_sop_raw_to_node_id,
    stage_id_for_node_id,
    stage_name_for_id,
)

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]
PipelinePhase = Literal[
    "idle",
    "running",
    "clarify_gate",
    "result_gate",
    "exception_gate",
    "completed",
    "waiting",
]

PIPELINE_SCHEMA_VERSION = 1

# --- 流程标识（flow_step）：下一步要做什么 ---
STEP_IDLE = "idle"
STEP_OPEN_MEETING = "open_meeting"
STEP_NODE_INIT = "node_init"
STEP_ASSEMBLE_HOST_PROMPT = "assemble_host_prompt"
STEP_NODE_REVIEW = "node_review"
STEP_NODE_FINISH = "node_finish"
STEP_REPROCESS_PREP = "reprocess_prep"
STEP_SYSTEM_NODE_EXEC = "system_node_exec"
STEP_WAITING = "waiting"
STEP_DONE = "done"

_VALID_FLOW_STEPS = frozenset(
    {
        STEP_IDLE,
        STEP_OPEN_MEETING,
        STEP_NODE_INIT,
        STEP_ASSEMBLE_HOST_PROMPT,
        STEP_NODE_REVIEW,
        STEP_NODE_FINISH,
        STEP_REPROCESS_PREP,
        STEP_SYSTEM_NODE_EXEC,
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
    STEP_NODE_REVIEW: "节点确认总结",
    STEP_NODE_FINISH: "节点收尾",
    STEP_REPROCESS_PREP: "重新处理准备",
    STEP_SYSTEM_NODE_EXEC: "系统节点执行",
    STEP_WAITING: "流程待机",
    STEP_DONE: "流程结束",
}

# 登记：某步完成后默认进入的下一步（可被 handler 覆盖）
FLOW_STEP_NEXT: dict[str, str] = {
    STEP_OPEN_MEETING: STEP_NODE_INIT,
    STEP_NODE_INIT: STEP_ASSEMBLE_HOST_PROMPT,
    STEP_ASSEMBLE_HOST_PROMPT: STEP_WAITING,
    STEP_NODE_REVIEW: STEP_WAITING,  # NODE_REVIEW → 等用户确认 → confirm_node_delivery → NODE_FINISH
    STEP_NODE_FINISH: STEP_NODE_INIT,
    STEP_REPROCESS_PREP: STEP_NODE_INIT,
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

    def _log_flow_transition(self, from_step: str, to_step: str, reason: str) -> None:
        """仅更新 pipeline 内存状态；不再写入 ``pipeline_transition`` 会议流事件。"""
        _ = from_step, to_step, reason

    @classmethod
    def exists(cls, scope_id: str) -> bool:
        sid = (scope_id or "").strip()
        if not sid:
            return False
        return meeting_pipeline_path(sid).is_file()

    @classmethod
    def load(cls, scope_id: str) -> MeetingPipeline:
        """加载已有 pipeline；文件不存在时抛 ``ValueError(meeting_pipeline_not_found)``。"""
        sid = (scope_id or "").strip()
        if not sid:
            raise ValueError("scope_id required")
        raw = read_json_file(meeting_pipeline_path(sid))
        if not raw:
            raise ValueError("meeting_pipeline_not_found")
        return cls(sid, raw)

    @classmethod
    def create(
        cls,
        scope_id: str,
        *,
        scope_type: ScopeType = "demand",
        flow_step: str = STEP_OPEN_MEETING,
    ) -> MeetingPipeline:
        """创建 pipeline 文件；已存在时抛 ``ValueError(meeting_pipeline_already_exists)``。"""
        sid = (scope_id or "").strip()
        if not sid:
            raise ValueError("scope_id required")
        if cls.exists(sid):
            raise ValueError("meeting_pipeline_already_exists")
        pipe = cls(
            sid,
            default_pipeline_state(
                scope_type=scope_type,
                scope_id=sid,
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
    prod: str = ""
    agent_pool: Any | None = None
    # 由步骤写入，供返回 API
    dev_status: dict[str, Any] = field(default_factory=dict)
    room_state: dict[str, Any] | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    node_run_scheduled: bool = False
    # 异步开门模式：True 时 _step_open_meeting 跳过外部 HTTP（catalog/userwork patch），
    # 由 service.open_meeting 在后台补做。让前端「一键开会」立刻拿到 room_id。
    defer_external: bool = False


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


def _canonical_node_id(node_id: str) -> str:
    return (node_id or "").strip()


def _is_valid_run_node(node_id: str) -> bool:
    nid = _canonical_node_id(node_id)
    return bool(nid) and nid != "pending"


def _resolve_run_node_id(
    pipe: MeetingPipeline,
    data: dict[str, Any] | None,
    *,
    sync_pipe: bool = True,
) -> str:
    """解析 pipeline 当前应运行的 SOP 节点。

    ``on_node_complete(advance=True)`` 会先更新 dev.status，而 meeting_pipeline 在
    NodeReview 等待期间可能仍停留在上一节点；因此以 dev.status 为准。
    """
    dev_node = _canonical_node_id(str((data or {}).get("current_node_id") or ""))
    pipe_node = _canonical_node_id(pipe.current_node_id)
    if _is_valid_run_node(dev_node):
        run_node = dev_node
    elif _is_valid_run_node(pipe_node):
        run_node = pipe_node
    else:
        run_node = dev_node or pipe_node or "pending"
    if sync_pipe and _is_valid_run_node(run_node):
        pipe._data["current_node_id"] = run_node
    return run_node


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

    userwork_updates: dict[str, str] = {"prod": prod}
    if ctx.defer_external:
        # 异步开门：跳过 HTTP 调用（catalog 校验 / userwork 回写），由后台异步任务补做。
        # prod 暂存到 dev_status.meeting_room 以便后台任务使用。
        data.setdefault("meeting_room", {})["prod"] = prod
        save_dev_status(sid, data)
    else:
        from synapse.rd_meeting.product_context import (
            ensure_prod_in_catalog,
            save_prod_catalog_to_pipeline,
        )

        catalog_rows, catalog_err = ensure_prod_in_catalog(prod)
        if catalog_err:
            raise ValueError(catalog_err)

        if ctx.sync_userwork:
            userwork_updates = patch_userwork_summary(
                scope_type=scope_type,
                scope_id=sid,
                sop_node=sop_display,
                local_process_state=local,
                prod=prod,
            )

        save_prod_catalog_to_pipeline(sid, catalog_rows, selected_prod=prod)

        from synapse.rd_meeting.product_assets import (
            bootstrap_product_assets,
            save_product_assets_to_pipeline,
        )
        from synapse.rd_meeting.product_context import match_prod_row_by_prod

        wire_hit = match_prod_row_by_prod(catalog_rows, prod)
        assets = bootstrap_product_assets(sid, prod, wire_row=wire_hit, catalog_rows=catalog_rows)
        save_product_assets_to_pipeline(sid, assets)
        pctx = pipe._data.get("context")
        if not isinstance(pctx, dict):
            pctx = {}
        pctx["product_assets"] = assets
        pipe._data["context"] = pctx

    open_binding = resolve_node_binding(
        node_id,
        scope_type=scope_type,
        scope_id=sid,
    )
    host_id = str(open_binding.get("host_profile_id") or "default").strip() or "default"

    room_opened_payload: dict[str, Any] = {
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
    }
    pctx_open = pipe._data.get("context")
    if isinstance(pctx_open, dict) and isinstance(pctx_open.get("product_assets"), dict):
        room_opened_payload["product_assets"] = pctx_open["product_assets"]
    append_history_event(sid, room_opened_payload)

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


AdvancePastResult = Literal["done", "skip_redirect", "continue"]


def _redirect_pipeline_to_finish_skipped(pipe: MeetingPipeline, skipped_nodes: list[str]) -> None:
    """pipeline 内 skip disabled 节点：同一次 while 切到 node_finish，不另 schedule。"""
    if not skipped_nodes:
        return
    pctx = pipe._data.get("context")
    if not isinstance(pctx, dict):
        pctx = {}
    first = skipped_nodes[0]
    rest = skipped_nodes[1:]
    pctx["last_finished_node_id"] = first
    if rest:
        pctx["pending_finish_node_ids"] = rest
    else:
        pctx.pop("pending_finish_node_ids", None)
    pipe._data["context"] = pctx
    pipe.set_flow_step(
        STEP_NODE_FINISH,
        reason=f"跳过 disabled 节点 {first}，同 pipeline 内收尾",
    )


def _advance_past_disabled_nodes(pipe: MeetingPipeline, ctx: PipelineRunContext) -> AdvancePastResult:
    """节点初始化/组装前跳过 disabled 节点。

    - ``done``：剩余节点均已跳过，流程结束
    - ``skip_redirect``：已 skip，caller 应 return，由同 pipeline while 进入 node_finish
    - ``continue``：当前节点 enabled，继续本 step
    """
    sid = ctx.scope_id
    data = ctx.dev_status or load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator

    result = MeetingRoomOrchestrator().advance_past_disabled_nodes(
        scope_type=ctx.scope_type,
        scope_id=sid,
        room_id=room_id,
        ticket_title=str(ctx.detail.get("ticket_title") or ""),
        agent_pool=ctx.agent_pool,
        schedule_pipeline_advance=False,
    )
    ctx.dev_status = load_dev_status(sid) or ctx.dev_status
    if result.get("status") == "completed":
        pipe.set_flow_step(STEP_DONE, reason="剩余节点均已跳过，流程结束")
        return "done"
    skipped = [str(n).strip() for n in (result.get("skipped_nodes") or []) if str(n).strip()]
    if skipped:
        _redirect_pipeline_to_finish_skipped(pipe, skipped)
        return "skip_redirect"
    return "continue"


def _step_node_init(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """第二步：节点初始化（userwork 上下文日志，不含主控 prompt）。"""
    sid = ctx.scope_id
    advance = _advance_past_disabled_nodes(pipe, ctx)
    if advance == "done":
        pipe.mark_step_completed(STEP_NODE_INIT)
        return
    if advance == "skip_redirect":
        return
    data = ctx.dev_status
    if not data:
        data = load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    run_node = _resolve_run_node_id(pipe, data)
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
    if is_system_node(run_node):
        append_system_node_init_chat(
            sid,
            room_id=room_id,
            node_id=run_node,
            binding=run_binding,
            scope_type=scope_type,
        )
    else:
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

    if not is_system_node(run_node):
        _schedule_prewarm_for_init(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            ticket_title=ticket_title,
            binding=run_binding,
            agent_pool=ctx.agent_pool,
        )

    pipe.mark_step_completed(STEP_NODE_INIT)
    if is_system_node(run_node):
        pipe.set_flow_step(
            STEP_SYSTEM_NODE_EXEC,
            reason=f"系统节点 {run_node} 初始化完成，进入代码执行",
        )
    else:
        pipe.set_flow_step(
            FLOW_STEP_NEXT[STEP_NODE_INIT],
            reason="节点初始化完成，进入主控提示词组装",
        )


def _step_assemble_host_prompt(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """第三步：组装小鲸主控提示词并写入协作会议流（完整展示）。"""
    sid = ctx.scope_id
    advance = _advance_past_disabled_nodes(pipe, ctx)
    if advance == "done":
        pipe.mark_step_completed(STEP_ASSEMBLE_HOST_PROMPT)
        return
    if advance == "skip_redirect":
        return
    data = ctx.dev_status
    if not data:
        data = load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    run_node = _resolve_run_node_id(pipe, data)
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
    save_host_prompt_cache(sid, bundle)
    append_host_prompt_chat(
        sid,
        room_id=room_id,
        scope_type=scope_type,
        node_id=run_node,
        binding=run_binding,
        ticket_title=ticket_title,
        bundle=bundle,
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
        "host_profile_id": str(bundle.get("host_profile_id") or ""),
    }
    pipe._data["context"] = pctx

    pipe.mark_step_completed(STEP_ASSEMBLE_HOST_PROMPT)
    if ctx.defer_external:
        # 异步开门：首节点的 schedule_run_node 推迟到 async tail 校验完 prod 之后再触发
        pipe.set_flow_step(STEP_WAITING, reason="主控提示词已组装，等待外部校验完成后调度节点")
    else:
        _schedule_current_node(pipe, ctx)
        pipe.set_flow_step(STEP_WAITING, reason="主控提示词已组装并已调度节点执行")


def _schedule_current_node(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """主控提示词组装后立刻后台执行当前节点。"""
    from synapse.rd_meeting.orchestrator import schedule_run_node

    schedule_run_node(
        scope_type=ctx.scope_type,
        scope_id=ctx.scope_id,
        room_id=pipe.room_id,
        ticket_title=str(ctx.detail.get("ticket_title") or ""),
        agent_pool=ctx.agent_pool,
        dry_run=None,
    )
    pipe.set_phase("running", sync_room_state=True)
    ctx.node_run_scheduled = True
    ctx.detail["node_run_scheduled"] = True


def _schedule_prewarm_for_init(
    *,
    scope_type: ScopeType,
    scope_id: str,
    room_id: str,
    ticket_title: str,
    binding: dict[str, Any],
    agent_pool: Any | None,
) -> None:
    """节点 INIT 阶段调度后台 prewarm，让前端立刻看到 Agent 卡片，不阻塞 pipeline。"""
    if agent_pool is None or not room_id:
        return
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 非 async 上下文（如纯同步测试），跳过

    from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator
    from synapse.rd_meeting.prewarm_coordinator import (
        bump_meeting_prewarm_generation,
        is_meeting_prewarm_generation_current,
    )

    host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
    orch = MeetingRoomOrchestrator()
    prewarm_gen = bump_meeting_prewarm_generation(room_id)

    async def _runner() -> None:
        try:
            if not is_meeting_prewarm_generation_current(room_id, prewarm_gen):
                return
            await orch._prewarm_meeting_room(
                agent_pool=agent_pool,
                room_id=room_id,
                scope_type=scope_type,
                scope_id=scope_id,
                ticket_title=ticket_title,
                binding=binding,
                host_profile_id=host_id,
                prewarm_generation=prewarm_gen,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("prewarm at node_init failed scope=%s: %s", scope_id, exc)

    try:
        loop.create_task(_runner())
    except Exception as exc:  # pragma: no cover
        logger.debug("schedule prewarm task failed: %s", exc)


def _cleanup_agents_for_finished_node(
    *,
    scope_id: str,
    room_id: str,
    agent_pool: Any | None,
    last_node_id: str,
    last_binding: dict[str, Any] | None,
) -> None:
    """节点收尾：dump host / worker trace 后严格清空 messages + TaskState。

    - 优先从 ``last_binding`` 解析 host / worker_profile_ids；
    - 若 binding 缺失则只清 host（向后兼容）。
    - 任何子步骤失败仅打 warning，避免阻断 pipeline 推进。
    """
    if agent_pool is None or not room_id:
        return
    try:
        from synapse.rd_meeting.agent_session import host_session_id
        from synapse.rd_meeting.agent_trace import (
            dump_agent_node_trace,
            reset_agent_node_context,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("agent_trace import failed scope=%s: %s", scope_id, exc)
        return

    host_pid = ""
    worker_ids: list[str] = []
    if isinstance(last_binding, dict):
        host_pid = str(last_binding.get("host_profile_id") or "").strip()
        worker_ids = [
            str(w).strip()
            for w in (last_binding.get("worker_profile_ids") or [])
            if str(w).strip() and str(w).strip() != host_pid
        ]

    host_sid = host_session_id(room_id)
    host_agent = None
    try:
        if hasattr(agent_pool, "get_existing"):
            host_agent = agent_pool.get_existing(host_sid)
    except Exception as exc:  # pragma: no cover
        logger.debug("get_existing host failed scope=%s: %s", scope_id, exc)

    if host_agent is not None:
        try:
            if last_node_id and host_pid:
                dump_agent_node_trace(
                    scope_id,
                    host_pid,
                    last_node_id,
                    agent=host_agent,
                    host_profile_id=host_pid,
                    worker_profile_ids=worker_ids,
                    role="host",
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("dump host trace failed scope=%s: %s", scope_id, exc)
        try:
            reset_agent_node_context(
                scope_id,
                host_pid or "default",
                last_node_id or "pending",
                agent=host_agent,
                reason="node_finish_host",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("reset host context failed scope=%s: %s", scope_id, exc)
        try:
            from synapse.rd_meeting.agent_prompt import clear_meeting_prompt_binding
            from synapse.rd_meeting.agent_session import release_meeting_pool_agent

            release_meeting_pool_agent(host_agent)
            clear_meeting_prompt_binding(host_agent)
        except Exception as exc:  # pragma: no cover
            logger.warning("clear host meeting prompt binding failed scope=%s: %s", scope_id, exc)

    for wid in worker_ids:
        worker_sid = f"rd_meeting:{room_id}:{wid}"
        worker_agent = None
        try:
            if hasattr(agent_pool, "get_existing"):
                worker_agent = agent_pool.get_existing(worker_sid)
        except Exception as exc:  # pragma: no cover
            logger.debug("get_existing worker %s failed: %s", wid, exc)
        if worker_agent is None:
            continue
        try:
            if last_node_id:
                dump_agent_node_trace(
                    scope_id,
                    wid,
                    last_node_id,
                    agent=worker_agent,
                    host_profile_id=host_pid,
                    worker_profile_ids=worker_ids,
                    role="worker",
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("dump worker %s trace failed scope=%s: %s", wid, scope_id, exc)
        try:
            reset_agent_node_context(
                scope_id,
                wid,
                last_node_id or "pending",
                agent=worker_agent,
                reason="node_finish_worker",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("reset worker %s context failed: %s", wid, exc)
        try:
            from synapse.rd_meeting.agent_prompt import clear_meeting_prompt_binding
            from synapse.rd_meeting.agent_session import release_meeting_pool_agent

            release_meeting_pool_agent(worker_agent)
            clear_meeting_prompt_binding(worker_agent)
        except Exception as exc:  # pragma: no cover
            logger.warning("clear worker %s meeting prompt binding failed: %s", wid, exc)


def sop_reprocess_node_id_range(target_node_id: str, current_node_id: str) -> list[str]:
    """返回 [target, current] 闭区间内的 SOP 节点 id（按流水线顺序）。"""
    ids = [str(n["id"]) for n in ALL_NODES]
    target = (target_node_id or "").strip()
    current = (current_node_id or "").strip()
    t_idx = ids.index(target)
    c_idx = ids.index(current)
    if t_idx > c_idx:
        raise ValueError("invalid_reprocess_target")
    return ids[t_idx : c_idx + 1]


def clear_current_node_reprocess_artifacts(
    scope_id: str,
    node_id: str,
    *,
    stage_id: int | None = None,
    clear_scope_root_files: bool = True,
) -> None:
    """重新处理：清理 SOP 节点归档、pipeline 节点缓存；可选清理工单级快照/标记。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid or nid == "pending":
        return

    stg_id = int(stage_id) if stage_id is not None else stage_id_for_node_id(nid)
    stage_name = stage_name_for_id(stg_id)
    archive_dir = archive_node_dir(sid, stage_name, nid)
    if archive_dir.is_dir():
        try:
            shutil.rmtree(archive_dir)
            logger.info("reprocess_prep: removed archive dir %s", archive_dir)
        except OSError as exc:
            logger.warning("reprocess_prep: failed to remove archive %s: %s", archive_dir, exc)

    if clear_scope_root_files:
        root = scope_dir(sid)
        for name in ("host_prompt_snapshot.md", "hitl.flag.json"):
            path = root / name
            if path.is_file():
                try:
                    path.unlink()
                    logger.info("reprocess_prep: removed %s", path)
                except OSError as exc:
                    logger.warning("reprocess_prep: failed to remove %s: %s", path, exc)

    path = meeting_pipeline_path(sid)
    raw = read_json_file(path)
    if not isinstance(raw, dict):
        return
    ctx = raw.get("context")
    if not isinstance(ctx, dict):
        ctx = {}
    node_review = ctx.get("node_review")
    if isinstance(node_review, dict) and nid in node_review:
        nr = dict(node_review)
        nr.pop(nid, None)
        ctx["node_review"] = nr
    if clear_scope_root_files:
        ctx.pop("host_prompt", None)
    raw["context"] = ctx
    raw["phase"] = "running"
    raw["updated_at"] = _now_iso()
    write_json_file(path, raw)


def _remove_agent_sop_node_dir(scope_id: str, node_id: str) -> None:
    node_dir = agent_sop_node_dir(scope_id, node_id)
    if node_dir.is_dir():
        try:
            shutil.rmtree(node_dir)
            logger.info("reprocess_prep: removed sop dir %s", node_dir)
        except OSError as exc:
            logger.warning("reprocess_prep: failed to remove %s: %s", node_dir, exc)


def clear_nodes_for_historical_reprocess(scope_id: str, node_ids: list[str]) -> None:
    """历史重处理：按 current→target 逆序清理索引区间内各节点产物与 agents 目录。"""
    ordered = [str(n).strip() for n in node_ids if str(n).strip() and str(n).strip() != "pending"]
    if not ordered:
        return
    for idx, nid in enumerate(reversed(ordered)):
        stg = stage_id_for_node_id(nid)
        clear_current_node_reprocess_artifacts(
            scope_id,
            nid,
            stage_id=stg,
            clear_scope_root_files=(idx == 0),
        )
        _remove_agent_sop_node_dir(scope_id, nid)


def clear_room_state_for_node_reprocess(
    scope_id: str,
    node_id: str,
    *,
    extra_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    """重新处理：清理 room_state 内节点缓存、门控残留与参会人列表。"""
    from synapse.rd_meeting.host_prompt_cache import clear_host_prompt_cache

    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    clear_host_prompt_cache(sid)

    metric_ids: list[str] = []
    if nid:
        metric_ids.append(nid)
    for x in extra_node_ids or []:
        xs = str(x).strip()
        if xs and xs not in metric_ids:
            metric_ids.append(xs)

    rs = dict(load_room_state(sid) or {})
    rs["status"] = "processing"
    rs["phase"] = "running"
    for key in (
        "hitl_form_schema",
        "hitl_locked",
        "hitl_submission",
        "pending_delivery",
        "intervention_kind",
        "agents_active",
        "rework_instruction",
        "user_context_pending",
        "participants",
        "pending_host_llm_begin_kind",
        "stopped_at",
        "stopped_reason",
        "solution_review_blocked",
        "escalate_reason",
    ):
        rs.pop(key, None)

    node_metrics = rs.get("node_metrics")
    if isinstance(node_metrics, dict):
        nm = dict(node_metrics)
        for mid in metric_ids:
            nm.pop(mid, None)
        rs["node_metrics"] = nm

    save_room_state(sid, rs)
    return rs


def _clear_reprocess_context_if_done(scope_id: str, finished_node_id: str) -> None:
    """重处理原因一次性生效：收尾到锚点节点后清除 room_state 中的注入字段。"""
    sid = (scope_id or "").strip()
    nid = (finished_node_id or "").strip()
    if not sid or not nid:
        return
    rs = dict(load_room_state(sid) or {})
    until = str(rs.get("reprocess_until_node_id") or "").strip()
    if not until or until != nid:
        return
    rs.pop("reprocess_reason", None)
    rs.pop("reprocess_until_node_id", None)
    save_room_state(sid, rs)


def _step_reprocess_prep(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """重新处理准备：清理当前节点过程目录、归档产出与 room_state 介入态。"""
    sid = ctx.scope_id
    data = ctx.dev_status or load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    run_node = _resolve_run_node_id(pipe, data)
    if run_node in ("pending", ""):
        pipe.mark_step_completed(STEP_REPROCESS_PREP)
        pipe.set_flow_step(STEP_WAITING, reason="无有效节点，无法重新处理")
        return

    pctx = pipe._data.get("context")
    if not isinstance(pctx, dict):
        pctx = {}
    raw_range = pctx.get("reprocess_node_ids")
    range_ids = (
        [str(x).strip() for x in raw_range if str(x).strip() and str(x).strip() != "pending"]
        if isinstance(raw_range, list)
        else []
    )
    historical = len(range_ids) > 1

    if historical:
        clear_nodes_for_historical_reprocess(sid, range_ids)
    else:
        stage_id = int(data.get("stage_id") or stage_id_for_node_id(run_node))
        clear_current_node_reprocess_artifacts(sid, run_node, stage_id=stage_id)
        _remove_agent_sop_node_dir(sid, run_node)

    from synapse.rd_meeting.hitl_lifecycle import reset_human_confirm_lifecycle
    from synapse.rd_meeting.hitl_submit import clear_pending_questionnaire

    reset_human_confirm_lifecycle(sid)
    clear_pending_questionnaire(sid)

    reason = str(pctx.get("reprocess_reason") or "").strip()
    until_node = str(pctx.get("reprocess_until_node_id") or run_node).strip() or run_node
    pctx.pop("reprocess_reason", None)
    pctx.pop("reprocess_until_node_id", None)

    extra = [n for n in range_ids if n != run_node] if historical else None
    ctx.room_state = clear_room_state_for_node_reprocess(sid, run_node, extra_node_ids=extra)
    if reason:
        rs = dict(load_room_state(sid) or {})
        rs["reprocess_reason"] = reason
        rs["reprocess_until_node_id"] = until_node
        save_room_state(sid, rs)
        ctx.room_state = rs
    pipe.set_phase("running", sync_room_state=False)
    if historical:
        pctx.pop("reprocess_node_ids", None)
        pctx.pop("reprocess_historical_target", None)
        pipe._data["context"] = pctx
    pipe.save()

    prep_text = (
        f"历史节点重新处理：已清理 {range_ids[0]} → {range_ids[-1]} 共 {len(range_ids)} 个节点"
        if historical
        else f"重新处理准备：已清理节点 {run_node} 的过程数据与归档产出"
    )
    append_history_event(
        sid,
        {
            "event": "reprocess_prep",
            "room_id": room_id,
            "node_id": run_node,
            "node_ids": range_ids if historical else [run_node],
            "text": prep_text,
            "flow_stage": FLOW_STEP_LABEL[STEP_REPROCESS_PREP],
            "log_type": "info",
            "agent_id": "system",
        },
    )

    pipe.mark_step_completed(STEP_REPROCESS_PREP)
    pipe.set_flow_step(
        FLOW_STEP_NEXT[STEP_REPROCESS_PREP],
        reason=f"过程数据已清理，重新初始化节点 {run_node}",
    )


def _step_system_node_exec(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """系统节点：纯代码 handler，完成后走 node_finish 自动推进。"""
    sid = ctx.scope_id
    data = ctx.dev_status or load_dev_status(sid) or {}
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")
    run_node = _resolve_run_node_id(pipe, data)
    if run_node in ("pending", "") or not is_system_node(run_node):
        pipe.mark_step_completed(STEP_SYSTEM_NODE_EXEC)
        pipe.set_flow_step(STEP_ASSEMBLE_HOST_PROMPT, reason="非系统节点，回退主控提示词组装")
        return

    scope_type = ctx.scope_type
    ticket_title = str(ctx.detail.get("ticket_title") or "")

    append_history_event(
        sid,
        {
            "event": "system_node_started",
            "room_id": room_id,
            "node_id": run_node,
            "flow_stage": FLOW_STEP_LABEL[STEP_SYSTEM_NODE_EXEC],
            "log_type": "info",
            "agent_id": "system",
            "system_node": True,
        },
    )

    rs = dict(load_room_state(sid) or {})
    rs["status"] = "processing"
    rs["current_node_id"] = run_node
    rs["agents_active"] = build_meeting_participants(
        resolve_node_binding(run_node, scope_type=scope_type, scope_id=sid, ticket_title=ticket_title)
    )
    save_room_state(sid, rs)
    ctx.room_state = rs

    from synapse.rd_meeting.system_nodes import run_system_node

    result = run_system_node(
        run_node,
        scope_type=scope_type,
        scope_id=sid,
        dev=data,
        pipe=pipe,
    )

    append_history_event(
        sid,
        {
            "event": "system_node_executed",
            "room_id": room_id,
            "node_id": run_node,
            "result": result,
            "flow_stage": FLOW_STEP_LABEL[STEP_SYSTEM_NODE_EXEC],
            "log_type": "info" if result.get("status") in ("ok", "partial") else "error",
            "agent_id": "system",
            "system_node": True,
        },
    )

    pctx = pipe._data.get("context")
    if not isinstance(pctx, dict):
        pctx = {}
    pctx["last_finished_node_id"] = run_node
    pctx["last_system_node_result"] = result
    pipe._data["context"] = pctx

    from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator

    orch = MeetingRoomOrchestrator()
    if result.get("status") == "failed":
        rs_fail = dict(load_room_state(sid) or {})
        rs_fail["status"] = "failed"
        save_room_state(sid, rs_fail)
        append_history_event(
            sid,
            {
                "event": "node_failed",
                "room_id": room_id,
                "node_id": run_node,
                "error": str(result.get("error") or "system_node_failed"),
                "agent_id": "system",
            },
        )
        pipe.mark_step_completed(STEP_SYSTEM_NODE_EXEC)
        pipe.set_flow_step(STEP_WAITING, reason="系统节点执行失败")
        return

    orch.on_node_complete(
        scope_type=scope_type,
        scope_id=sid,
        room_id=room_id,
        node_id=run_node,
        artifacts=result.get("artifacts") if isinstance(result.get("artifacts"), list) else [],
        tokens_used=0,
        duration_seconds=int(result.get("duration_seconds") or 0),
        sync_userwork=True,
        advance=True,
        schedule_pipeline_advance=False,
        ticket_title=ticket_title,
        agent_pool=ctx.agent_pool,
    )

    pipe.mark_step_completed(STEP_SYSTEM_NODE_EXEC)
    pipe.set_flow_step(STEP_NODE_FINISH, reason=f"系统节点 {run_node} 执行完成，进入收尾")


def _step_node_finish(pipe: MeetingPipeline, ctx: PipelineRunContext) -> None:
    """节点收尾：dump host + worker trace、严格冷启动 messages / TaskState，写流日志；
    随后自动进入下一节点的 INIT。

    本步骤由 ``schedule_node_finish`` 在 on_node_complete(advance=True) 之后异步触发。
    ``current_node_id`` 此时已经是**下一个节点**（dev_status 已被 on_node_complete 推进），
    所以"刚刚完成的节点"取 ``pipe.context.last_finished_node_id``，由
    ``schedule_node_finish`` 调用前写入。
    """
    sid = ctx.scope_id
    data = ctx.dev_status or load_dev_status(sid) or {}
    next_node = _resolve_run_node_id(pipe, data)
    room_id = pipe.room_id or str((data.get("meeting_room") or {}).get("room_id") or "")

    # 解析"刚完成的节点"以及对应 binding，用于 dump trace
    pctx = pipe._data.get("context") if isinstance(pipe._data.get("context"), dict) else {}
    last_node_id = str(pctx.get("last_finished_node_id") or "").strip()
    last_binding: dict[str, Any] | None = None
    if last_node_id:
        try:
            last_binding = resolve_node_binding(
                last_node_id,
                scope_type=ctx.scope_type,
                scope_id=sid,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("resolve last binding failed scope=%s node=%s: %s", sid, last_node_id, exc)
            last_binding = None

    _cleanup_agents_for_finished_node(
        scope_id=sid,
        room_id=room_id,
        agent_pool=ctx.agent_pool,
        last_node_id=last_node_id,
        last_binding=last_binding,
    )
    if last_node_id and isinstance(pctx, dict):
        pctx.pop("last_finished_node_id", None)
        pipe._data["context"] = pctx

    if last_node_id:
        _clear_reprocess_context_if_done(sid, last_node_id)

    append_history_event(
        sid,
        {
            "event": "node_finished",
            "room_id": room_id,
            "node_id": last_node_id or next_node,
            "next_node_id": next_node,
            "flow_stage": "节点收尾",
            "log_type": "info",
            "agent_id": _host_profile_id_for_scope(sid, node_id=next_node, scope_type=ctx.scope_type),
        },
    )

    pipe.mark_step_completed(STEP_NODE_FINISH)

    pctx_after = pipe._data.get("context") if isinstance(pipe._data.get("context"), dict) else {}
    pending = pctx_after.get("pending_finish_node_ids")
    if isinstance(pending, list) and pending:
        next_finish = str(pending.pop(0)).strip()
        if next_finish:
            pctx_after["last_finished_node_id"] = next_finish
            pctx_after["pending_finish_node_ids"] = pending
            pipe._data["context"] = pctx_after
            pipe.set_flow_step(
                STEP_NODE_FINISH,
                reason=f"继续收尾 skipped 节点 {next_finish}",
            )
            return
        pctx_after.pop("pending_finish_node_ids", None)
        pipe._data["context"] = pctx_after

    # 若没有下一个节点（next_node 为空 / "pending"），收尾后置 DONE，不再 INIT
    if not next_node or next_node == "pending":
        pipe.set_flow_step(STEP_DONE, reason="无下一节点，流程结束")
    else:
        pipe.set_flow_step(
            FLOW_STEP_NEXT[STEP_NODE_FINISH],
            reason=f"上一节点收尾完成，进入 {next_node} 初始化",
        )


# 流程标识 → 执行函数（主流程登记表，新增步骤在此挂载）
FLOW_STEP_HANDLERS: dict[str, StepHandler] = {
    STEP_OPEN_MEETING: _step_open_meeting,
    STEP_NODE_INIT: _step_node_init,
    STEP_ASSEMBLE_HOST_PROMPT: _step_assemble_host_prompt,
    STEP_SYSTEM_NODE_EXEC: _step_system_node_exec,
    STEP_REPROCESS_PREP: _step_reprocess_prep,
    STEP_NODE_FINISH: _step_node_finish,
}


def run_pipeline_until_waiting(
    ctx: PipelineRunContext,
    *,
    initial_flow_step: str = STEP_OPEN_MEETING,
    create: bool = False,
) -> MeetingPipeline:
    """从当前 ``flow_step`` 连续执行，直到 waiting/done/idle 或无 handler。

    - ``create=True``：仅用于 ``open_meeting``，新建 ``meeting_pipeline.json``。
    - ``create=False``：加载已有 pipeline 并推进（reprocess / node_finish 等）。
    """
    if create:
        pipe = MeetingPipeline.create(
            ctx.scope_id,
            scope_type=ctx.scope_type,
            flow_step=initial_flow_step,
        )
    else:
        pipe = MeetingPipeline.load(ctx.scope_id)
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


def schedule_node_finish(
    *,
    scope_type: ScopeType,
    scope_id: str,
    agent_pool: Any | None = None,
    ticket_title: str = "",
    last_node_id: str = "",
) -> None:
    """在 on_node_complete(advance=True) 之后异步推进：node_finish → node_init → assemble → schedule_run_node。

    设计：on_node_complete 已经把 dev_status.current_node_id 推到下一个节点；本函数把
    pipeline.flow_step 置为 STEP_NODE_FINISH 并跑 run_pipeline_until_waiting，让整条
    SOP 自动接力下去，无需用户再次"一键开会"。
    """
    sid = (scope_id or "").strip()
    if not sid:
        return
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    def _do_advance() -> None:
        try:
            pipe = MeetingPipeline.load(sid)
            dev = load_dev_status(sid) or {}
            if last_node_id:
                pctx = pipe._data.get("context")
                if not isinstance(pctx, dict):
                    pctx = {}
                pctx["last_finished_node_id"] = last_node_id.strip()
                pipe._data["context"] = pctx
            _resolve_run_node_id(pipe, dev)
            pipe.set_flow_step(STEP_NODE_FINISH, reason="节点完成，自动推进至下一节点")
            pipe.save()

            from synapse.rd_meeting.service import MeetingRoomService

            svc = MeetingRoomService()
            titles = build_title_index()
            detail = svc._room_detail_payload(dev, sid, titles)

            ctx = PipelineRunContext(
                scope_type=scope_type,
                scope_id=sid,
                sync_userwork=True,
                promote_to_processing=False,
                prod=str(dev.get("meeting_room", {}).get("prod") or "") if isinstance(dev.get("meeting_room"), dict) else "",
                agent_pool=agent_pool,
                dev_status=dev,
                detail=detail,
            )
            run_pipeline_until_waiting(ctx, initial_flow_step=STEP_NODE_FINISH)
        except Exception as exc:  # pragma: no cover
            logger.exception("schedule_node_finish failed scope=%s: %s", sid, exc)

    if loop is not None:
        try:
            loop.create_task(_run_node_finish_coro(_do_advance))
        except Exception as exc:  # pragma: no cover
            logger.debug("schedule_node_finish create_task failed: %s", exc)
            _do_advance()
    else:
        # 非 async 上下文（同步测试 / 命令行），直接执行
        _do_advance()


async def _run_node_finish_coro(fn: Callable[[], None]) -> None:
    fn()


def get_flow_step(scope_id: str) -> str:
    if not MeetingPipeline.exists(scope_id):
        return STEP_IDLE
    return MeetingPipeline.load(scope_id).flow_step


def set_flow_step(scope_id: str, step: str, *, reason: str = "") -> None:
    pipe = MeetingPipeline.load(scope_id)
    pipe.set_flow_step(step, reason=reason)
    pipe.save()


async def run_node_review_step(
    *,
    scope_type: ScopeType,
    scope_id: str,
    room_id: str,
    node_id: str,
    binding: dict[str, Any],
    report_body: str,
    tokens_used: int,
    duration_seconds: int,
    stage_id: int,
    agent_pool: Any | None,
    orchestrator: Any | None,
    use_llm_summary: bool = True,
) -> dict[str, Any]:
    """async：组装并落盘节点确认总结 payload，把 pipeline 切到 NODE_REVIEW。

    设计：``run_current_node`` 在 ``human_confirm=true`` 且报告就绪后调用，
    把"确认总结"从智能体提示词护栏迁到 pipeline 显式步骤。
    """
    from synapse.rd_meeting.node_review import (
        build_node_review_payload,
        save_node_review,
    )

    pipe = MeetingPipeline.load(scope_id)
    pipe.set_flow_step(STEP_NODE_REVIEW, reason=f"节点 {node_id} 执行完成，开始装配确认总结")
    pipe.save()

    payload = await build_node_review_payload(
        scope_type=scope_type,
        scope_id=scope_id,
        room_id=room_id,
        node_id=node_id,
        binding=binding,
        report_body=report_body,
        tokens_used=tokens_used,
        duration_seconds=duration_seconds,
        stage_id=stage_id,
        agent_pool=agent_pool,
        orchestrator=orchestrator,
        use_llm_summary=use_llm_summary,
    )
    save_node_review(scope_id, node_id, payload)

    pipe = MeetingPipeline.load(scope_id)
    pipe.mark_step_completed(STEP_NODE_REVIEW)
    pipe.set_flow_step(STEP_WAITING, reason="确认总结已装配，等待人工确认")
    pipe.save()
    return payload
