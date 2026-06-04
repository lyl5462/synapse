"""会议室节点编排：执行、归档、推进（Phase 2）。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any

from synapse.rd_meeting.agent_activity import (
    record_input,
    resolve_binding_for_profile,
    set_agent_activity_binding,
)
from synapse.rd_meeting.agent_prompt import set_meeting_prompt_node_id
from synapse.rd_meeting.agent_runtime import apply_meeting_agent_runtime
from synapse.rd_meeting.agent_session import (
    bind_meeting_agent_session,
    clear_meeting_agent_session,
    ensure_host_session,
    host_session_id,
)
from synapse.rd_meeting.agent_trace import append_event as trace_append_event
from synapse.rd_meeting.agent_trace import write_agent_meta
from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.bootstrap import build_node_init_message
from synapse.rd_meeting.dev_status import load_dev_status, save_dev_status
from synapse.rd_meeting.collaboration import has_collaboration_workers
from synapse.rd_meeting.dynamic_prompt import build_meeting_user_turn_prompt
from synapse.rd_meeting.hitl_form import (
    HitlGateFromReport,
    extract_hitl_from_agent_output,
    normalize_hitl_schema,
    resolve_hitl_schema_for_gate,
)
from synapse.rd_meeting.hitl_lifecycle import (
    HITL_CLARIFY_ROUND_KEY,
    MAX_HOST_QUESTIONNAIRE_ATTEMPTS,
    READY_FOR_NODE_REVIEW_KEY,
    bump_clarify_round,
    prompt_require_interactive_questionnaire,
    reset_human_confirm_lifecycle,
    set_ready_for_node_review,
    should_enter_node_review_after_hitl_locked,
    should_enter_node_review_gate,
)
from synapse.rd_meeting.hitl_submit import (
    clear_pending_questionnaire,
    consume_pending_questionnaire,
)
from synapse.rd_meeting.host_prompt_cache import (
    resolve_cached_host_meeting_prompt,
    resolve_cached_host_user_prompt,
)
from synapse.rd_meeting.init_context import build_node_init_log_data
from synapse.rd_meeting.notifications import schedule_human_intervention_notify
from synapse.rd_meeting.participants import build_meeting_participants
from synapse.rd_meeting.paths import archive_node_dir, scope_dir
from synapse.rd_meeting.phase import set_phase
from synapse.rd_meeting.pipeline_chat import format_host_first_call_chat
from synapse.rd_meeting.prewarm_coordinator import (
    bump_meeting_prewarm_generation,
    is_meeting_prewarm_generation_current,
)
from synapse.rd_meeting.room_runtime import (
    append_history_event,
    load_room_state,
    save_room_state,
)
from synapse.rd_meeting.sop_stage_hooks import schedule_sop_stage_transition_hook
from synapse.rd_meeting.room_skill import (
    DEFAULT_LLM_ENDPOINT_KEY,
    build_room_skill_prompt,
    get_meeting_room_rules,
    make_context,
)
from synapse.rd_meeting.user_context import drain_user_context_for_prompt
from synapse.rd_meeting.userwork_sync import patch_userwork_summary
from synapse.rd_meeting.validation import (
    normalize_node_output_body,
    validate_node_archive_artifacts,
)
from synapse.rd_sop.manifest import (
    next_node_id,
    node_output_artifacts,
)
from synapse.rd_sop.nodes import (
    ALL_NODES,
    node_display_name,
    stage_id_for_node_id,
    stage_name_for_id,
)

_MAX_SKIP_CHAIN = len(ALL_NODES) + 2

logger = logging.getLogger(__name__)

_running_tasks: dict[str, asyncio.Task[None]] = {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dry_run_enabled() -> bool:
    return os.environ.get("SYNAPSE_MEETING_ROOM_DRY_RUN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _resolve_profile(profile_id: str):
    from synapse.agents.presets import SYSTEM_PRESETS
    from synapse.agents.profile import get_profile_store

    pid = (profile_id or "").strip() or "default"
    store = get_profile_store()
    loaded = store.get(pid)
    if loaded:
        return loaded
    for sp in SYSTEM_PRESETS:
        if sp.id == pid:
            return sp
    for sp in SYSTEM_PRESETS:
        if sp.id == "default":
            return sp
    return SYSTEM_PRESETS[0] if SYSTEM_PRESETS else None


def build_node_prompt(
    *,
    scope_type: str,
    scope_id: str,
    node_id: str,
    binding: dict[str, Any],
    ticket_title: str = "",
) -> str:
    """主控首轮 user 消息（议程数据均在 meeting-room SKILL 四段式动态上下文）。"""
    _ = scope_type, scope_id, node_id, ticket_title
    return build_meeting_user_turn_prompt(has_collaborators=has_collaboration_workers(binding))


def _skip_node_report_body(node_id: str) -> str:
    name = node_display_name(node_id)
    return (
        f"# {name} — 节点已跳过\n\n"
        "本节点在会议室配置中已关闭（`enabled: false`），未执行智能体处理。\n"
        "系统已自动推进至下一议程。\n\n"
        "结论：本节点按配置跳过，交付完成。\n"
    )


def _write_simulated_agent_deliverables(
    scope_id: str,
    stage_name: str,
    node_id: str,
    content: str,
) -> None:
    """dry-run 专用：模拟智能体按 NODE_OUTPUTS 约定落盘（非 confirm 流程代写）。"""
    body = normalize_node_output_body(node_id, content)
    if len(body.strip()) < 80:
        body = f"{body.rstrip()}\n\n{'x' * 80}"
    dest_dir = archive_node_dir(scope_id, stage_name, node_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in node_output_artifacts(node_id):
        if not name or name.startswith("（") or not name.lower().endswith(".md"):
            continue
        (dest_dir / name).write_text(body, encoding="utf-8")


class MeetingRoomOrchestrator:
    """节点执行与状态推进（可 dry-run，不依赖 LLM）。"""

    async def _prewarm_meeting_room(
        self,
        *,
        agent_pool: Any,
        room_id: str,
        scope_type: str,
        scope_id: str,
        ticket_title: str,
        binding: dict[str, Any],
        host_profile_id: str,
        prewarm_generation: int = 0,
    ) -> None:
        """为本会议室预先创建所有 Worker 实例并注入会议室 SKILL / 端点。

        预热的好处：
        - 小鲸通过 ``delegate_to_agent`` 委派时，pool 已有正确端点 + SKILL；
        - Worker 之间可直接 ``send_agent_message`` 协作（pool 内可见）。

        ``prewarm_generation`` 与 :mod:`prewarm_coordinator` 配合，丢弃过期的异步 prewarm。
        """
        if prewarm_generation > 0 and not is_meeting_prewarm_generation_current(
            room_id, prewarm_generation
        ):
            logger.debug(
                "prewarm skipped stale generation room=%s gen=%s",
                room_id,
                prewarm_generation,
            )
            return
        worker_ids = [
            str(w).strip()
            for w in binding.get("worker_profile_ids") or []
            if str(w).strip() and str(w).strip() != host_profile_id
        ]
        if not worker_ids:
            return
        skill_body = get_meeting_room_rules()
        for wid in worker_ids:
            if prewarm_generation > 0 and not is_meeting_prewarm_generation_current(
                room_id, prewarm_generation
            ):
                logger.debug(
                    "prewarm aborted mid-loop stale generation room=%s gen=%s",
                    room_id,
                    prewarm_generation,
                )
                return
            profile = _resolve_profile(wid)
            if profile is None:
                logger.warning("worker profile %s not found, skip prewarm", wid)
                continue
            try:
                worker_agent = await agent_pool.get_or_create(
                    session_id=f"rd_meeting:{room_id}:{wid}",
                    profile=profile,
                )
            except Exception as exc:
                logger.warning("prewarm worker %s failed: %s", wid, exc)
                continue
            self._configure_meeting_agent(
                worker_agent,
                role="worker",
                binding=binding,
                scope_type=scope_type,
                scope_id=scope_id,
                ticket_title=ticket_title,
                scope_path=str(scope_dir(scope_id)),
                skill_body=skill_body,
                self_profile_id=wid,
            )

    @staticmethod
    def _configure_meeting_agent(
        agent: Any,
        *,
        role: str,
        binding: dict[str, Any],
        scope_type: str,
        scope_id: str,
        ticket_title: str,
        scope_path: str,
        skill_body: str | None = None,
        self_profile_id: str | None = None,
    ) -> bool:
        """覆盖 agent 实例的 cwd / preferred_endpoint / prompt suffix。

        会议室 SKILL 渲染后写入 ``_custom_prompt_suffix``，并强制重建 system
        prompt 让新内容生效。Worker 视角会把同事的能力卡片暴露给它，方便互
        相协作。

        主控（host）优先复用第三步 ``room_state.host_prompt_cache``。

        Returns:
            主控是否复用了缓存提示词（worker 恒为 False）。
        """
        reused_host_prompt = False
        agent.default_cwd = scope_path
        shell_tool = getattr(agent, "shell_tool", None)
        if shell_tool is not None:
            try:
                shell_tool.default_cwd = scope_path  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug("set shell_tool.default_cwd failed: %s", exc)

        endpoint_key = (
            str(binding.get("host_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY)
            if role == "host"
            else str(binding.get("worker_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY)
        )
        if endpoint_key:
            agent._preferred_endpoint = endpoint_key

        ctx = make_context(
            role=role,  # type: ignore[arg-type]
            binding=binding,
            scope_type=scope_type,
            scope_id=scope_id,
            ticket_title=ticket_title,
            archive_dir=str(
                archive_node_dir(
                    scope_id,
                    str(binding.get("stage_name") or stage_name_for_id(int(binding.get("stage_id") or 0))),
                    str(binding.get("node_id") or ""),
                )
            ),
            self_profile_id=str(self_profile_id or "").strip(),
        )
        if self_profile_id:
            ctx.worker_profile_ids = [self_profile_id] + [
                w for w in ctx.worker_profile_ids if w != self_profile_id
            ]
        nid = str(binding.get("node_id") or "")
        init_data = build_node_init_log_data(
            scope_type,  # type: ignore[arg-type]
            scope_id,
            node_id=nid,
        )
        dev = load_dev_status(scope_id)
        sop_display = str(dev.get("sop_node_display") or "") if dev else ""
        suffix: str | None = None
        if role == "host":
            cached, reused_host_prompt = resolve_cached_host_meeting_prompt(scope_id, binding)
            if cached:
                suffix = cached
        if suffix is None:
            suffix = build_room_skill_prompt(
                ctx,
                skill_body=skill_body,
                init_context=init_data,
                binding=binding,
                sop_node_display=sop_display,
            )
        # 会议室提示词 + Profile 技能全文 + 任务级工具白名单（对齐产品知识生成）
        agent._custom_prompt_suffix = ""
        target_pid = (self_profile_id or "").strip()
        if role == "host" and not target_pid:
            target_pid = str(binding.get("host_profile_id") or "default").strip() or "default"
        profile = _resolve_profile(target_pid) if target_pid else None
        agent_ctx = getattr(agent, "_context", None)
        if agent_ctx is not None:
            agent_ctx.system = apply_meeting_agent_runtime(
                agent,
                role=role,  # type: ignore[arg-type]
                profile=profile,
                base_system_prompt=suffix or "",
            )
        try:
            agent._org_context = True  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("set _org_context failed for role=%s: %s", role, exc)
        set_meeting_prompt_node_id(agent, nid or "pending")

        if target_pid:
            try:
                display_name = ""
                if profile is not None:
                    display_name = profile.get_display_name() or profile.name or target_pid
                write_agent_meta(
                    scope_id,
                    target_pid,
                    node_id=nid or "pending",
                    role=role,
                    display_name=display_name,
                    llm_endpoint=endpoint_key,
                    capabilities={
                        "skills": list(getattr(profile, "skills", None) or []) if profile else [],
                    },
                )
                trace_append_event(
                    scope_id,
                    target_pid,
                    nid or "pending",
                    event="configured",
                    detail={
                        "role": role,
                        "endpoint": endpoint_key,
                        "node_id": nid or "pending",
                        "reused_host_prompt": reused_host_prompt,
                    },
                )
            except Exception as exc:  # pragma: no cover
                logger.debug("write agent meta failed pid=%s: %s", target_pid, exc)
            try:
                dev_mr = load_dev_status(scope_id) or {}
                mr = dev_mr.get("meeting_room")
                room_id = str(mr.get("room_id") or "").strip() if isinstance(mr, dict) else ""
                host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
                set_agent_activity_binding(
                    agent,
                    scope_id=scope_id,
                    node_id=nid or "pending",
                    profile_id=target_pid,
                    host_profile_id=host_id,
                    role=role,
                    room_id=room_id,
                )
            except Exception as exc:
                logger.debug("set_agent_activity_binding failed pid=%s: %s", target_pid, exc)
        return reused_host_prompt

    def on_node_complete(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        artifacts: list[dict[str, Any]] | None = None,
        tokens_used: int = 0,
        duration_seconds: int = 0,
        sync_userwork: bool = True,
        advance: bool = True,
        schedule_pipeline_advance: bool = True,
        ticket_title: str = "",
        agent_pool: Any | None = None,
    ) -> dict[str, Any]:
        sid = scope_id.strip()
        dev = load_dev_status(sid)
        if dev is None:
            raise ValueError("dev_status_not_found")

        now = _now_iso()

        room_state = load_room_state(sid) or {}
        room_state = dict(room_state)
        node_metrics = room_state.get("node_metrics")
        if not isinstance(node_metrics, dict):
            node_metrics = {}
        prev = node_metrics.get(node_id) if isinstance(node_metrics.get(node_id), dict) else {}
        started = str(prev.get("started_at") or now)
        node_metrics[node_id] = {
            "started_at": started,
            "completed_at": now,
            "seconds": max(int(duration_seconds), int(prev.get("seconds") or 0)),
            "tokens": max(int(tokens_used), int(prev.get("tokens") or 0)),
        }
        room_state["node_metrics"] = node_metrics

        metrics = room_state.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        metrics["tokens"] = int(metrics.get("tokens") or 0) + int(tokens_used)
        metrics["stage_seconds"] = int(metrics.get("stage_seconds") or 0) + int(duration_seconds)
        room_state["metrics"] = metrics
        room_state["agents_active"] = []
        room_state["status"] = "processing"

        next_id: str | None = None
        prev_stage_id = stage_id_for_node_id(node_id)
        if advance:
            next_id = next_node_id(node_id)
            if next_id:
                dev["current_node_id"] = next_id
                dev["stage_id"] = stage_id_for_node_id(next_id)
                dev["sop_node_display"] = node_display_name(next_id)
                room_state["current_node_id"] = next_id
                room_state["stage_id"] = dev["stage_id"]
                next_stage_id = int(dev["stage_id"])
                if prev_stage_id != next_stage_id:
                    schedule_sop_stage_transition_hook(
                        scope_type=scope_type,  # type: ignore[arg-type]
                        scope_id=sid,
                        from_stage=prev_stage_id,
                        to_stage=next_stage_id,
                        completed_node_id=node_id,
                        next_node_id=next_id,
                    )
            else:
                dev["local_process_state"] = "已完成"
                room_state["status"] = "completed"
        else:
            room_state["current_node_id"] = node_id

        if advance and next_id:
            room_state.pop(READY_FOR_NODE_REVIEW_KEY, None)
            room_state.pop(HITL_CLARIFY_ROUND_KEY, None)

        save_dev_status(sid, dev)
        save_room_state(sid, room_state)

        append_history_event(
            sid,
            {
                "event": "node_completed",
                "room_id": room_id,
                "node_id": node_id,
                "artifacts": artifacts or [],
                "tokens_used": tokens_used,
                "duration_seconds": duration_seconds,
                "next_node_id": next_id,
            },
        )

        if sync_userwork:
            patch_userwork_summary(
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id=sid,
                sop_node=str(dev.get("sop_node_display") or node_display_name(str(dev.get("current_node_id")))),
                local_process_state=str(dev.get("local_process_state") or "").strip() or None,
            )

        # 节点完成 + 已推进到下一节点 → 异步触发 node_finish → init → assemble → schedule_run_node
        # 让 SOP 流程自动接力，不再依赖人工再次"一键开会"。
        # pipeline 内 inline skip 时由同一次 run_pipeline while 切 flow_step，不再 schedule。
        if advance and next_id and schedule_pipeline_advance:
            try:
                from synapse.rd_meeting.pipeline import schedule_node_finish

                schedule_node_finish(
                    scope_type=scope_type,  # type: ignore[arg-type]
                    scope_id=sid,
                    ticket_title=ticket_title,
                    agent_pool=agent_pool,
                    last_node_id=node_id,
                )
            except Exception as exc:
                logger.warning("schedule_node_finish after node_complete failed: %s", exc)

        return {"dev_status": dev, "room_state": room_state, "next_node_id": next_id}

    def advance_past_disabled_nodes(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        ticket_title: str = "",
        sync_userwork: bool = True,
        agent_pool: Any | None = None,
        schedule_pipeline_advance: bool = True,
    ) -> dict[str, Any]:
        """跳过配置关闭的 SOP 节点（不写 node_init / 不跑 LLM），推进到首个 enabled 节点。"""
        sid = scope_id.strip()
        dev = load_dev_status(sid)
        if dev is None:
            raise ValueError("dev_status_not_found")

        skipped_nodes: list[str] = []
        for _ in range(_MAX_SKIP_CHAIN):
            node_id = str(dev.get("current_node_id") or "pending")
            if node_id == "pending":
                return {
                    "current_node_id": node_id,
                    "skipped_nodes": skipped_nodes,
                    "status": "pending",
                    "dev_status": dev,
                }
            binding = resolve_node_binding(
                node_id,
                scope_type=scope_type,
                scope_id=sid,
                ticket_title=ticket_title,
            )
            if binding.get("enabled", True):
                return {
                    "current_node_id": node_id,
                    "skipped_nodes": skipped_nodes,
                    "status": "ready",
                    "dev_status": dev,
                }
            skipped_nodes.append(node_id)
            skip_out = self.on_node_skipped(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                node_id=node_id,
                ticket_title=ticket_title,
                sync_userwork=sync_userwork,
                agent_pool=agent_pool,
                schedule_pipeline_advance=schedule_pipeline_advance,
            )
            next_id = skip_out.get("next_node_id")
            if not next_id:
                return {
                    "skipped_nodes": skipped_nodes,
                    "status": "completed",
                    "skipped_llm": True,
                }
            dev = load_dev_status(sid)
            if dev is None:
                raise ValueError("dev_status_not_found")

        raise ValueError("skip_chain_exceeded")

    def on_node_skipped(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        ticket_title: str = "",
        sync_userwork: bool = True,
        agent_pool: Any | None = None,
        schedule_pipeline_advance: bool = True,
    ) -> dict[str, Any]:
        """配置关闭的节点：不写 LLM、不写产出物，仅记录事件并推进。"""
        sid = scope_id.strip()
        append_history_event(
            sid,
            {
                "event": "node_skipped",
                "room_id": room_id,
                "node_id": node_id,
                "reason": "disabled_in_config",
            },
        )
        return self.on_node_complete(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            artifacts=None,
            tokens_used=0,
            duration_seconds=0,
            sync_userwork=sync_userwork,
            advance=True,
            schedule_pipeline_advance=schedule_pipeline_advance,
            ticket_title=ticket_title,
            agent_pool=agent_pool,
        )

    def _gate_from_tool_questionnaire(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        binding: dict[str, Any],
        questionnaire: dict[str, Any],
        report_body: str,
        tokens_used: int,
        duration_seconds: int,
        stage_id: int,
        ticket_title: str,
        skipped_nodes: list[str] | None = None,
    ) -> dict[str, Any]:
        """主控通过 ``submit_hitl_questionnaire`` 工具直接锁定时的门控分支。"""
        schema = normalize_hitl_schema(questionnaire.get("schema")) or questionnaire.get("schema")
        kind = (questionnaire.get("kind") or "interactive").strip().lower()
        await_confirm = bool(questionnaire.get("await_confirm"))
        summary = str(questionnaire.get("summary") or "").strip()

        phase_map = {
            "result_confirm": "result_gate",
            "exception": "exception_gate",
            "interactive": "clarify_gate",
        }
        set_phase(scope_id, phase_map.get(kind, "clarify_gate"))

        # report_body 仅做摘要展示，不再用作 LLM 终稿
        body = (report_body or "").strip()
        if summary:
            body = f"{summary}\n\n---\n\n{body}" if body else summary
        pending = {
            "node_id": node_id,
            "report_body": body,
            "await_confirm": await_confirm,
            "tokens_used": tokens_used,
            "duration_seconds": duration_seconds,
            "stage_id": stage_id,
            "source": "tool",
        }
        reason_map = {
            "result_confirm": f"{node_display_name(node_id)} 待确认总结，请填写表单后归档推进",
            "exception": f"{node_display_name(node_id)} 异常待人工裁决，请填写表单后继续",
            "interactive": f"{node_display_name(node_id)} 需人工填写问卷后继续",
        }
        reason = reason_map.get(kind, reason_map["interactive"])
        gate_state = self.mark_human_gate(
            scope_type=scope_type,
            scope_id=scope_id,
            room_id=room_id,
            node_id=node_id,
            reason=reason,
            ticket_title=ticket_title,
            hitl_form_schema=schema,
            pending_delivery=pending,
            intervention_kind=kind,
        )
        append_history_event(
            scope_id,
            {
                "event": "hitl_dynamic",
                "room_id": room_id,
                "node_id": node_id,
                "detail": (
                    f"主控通过工具提交问卷 kind={kind} "
                    f"questions={len((schema or {}).get('questions') or [])} "
                    f"await_confirm={await_confirm}"
                ),
                "log_type": "info",
                "agent_id": str(binding.get("host_profile_id") or "default"),
                "source": "tool",
            },
        )
        if await_confirm:
            append_history_event(
                scope_id,
                {
                    "event": "node_pending_confirm",
                    "room_id": room_id,
                    "node_id": node_id,
                    "tokens_used": tokens_used,
                    "duration_seconds": duration_seconds,
                    "dynamic_form": True,
                    "source": "tool",
                },
            )
        return {
            "status": "human_intervention",
            "node_id": node_id,
            "skipped_nodes": skipped_nodes or None,
            "pending_confirm": await_confirm,
            "dynamic_hitl": True,
            "source": "tool",
            **gate_state,
        }

    def _gate_from_agent_hitl(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        binding: dict[str, Any],
        gate: HitlGateFromReport,
        report_body: str,
        tokens_used: int,
        duration_seconds: int,
        stage_id: int,
        ticket_title: str,
        skipped_nodes: list[str] | None = None,
    ) -> dict[str, Any]:
        """智能体显式输出 hitl-questionnaire 标记时进入人工门控。"""
        hitl_schema = resolve_hitl_schema_for_gate(
            binding,
            dynamic_schema=gate.schema,
            intervention_kind=gate.intervention_kind,
        )
        phase = "result_gate" if gate.intervention_kind == "result_confirm" else "clarify_gate"
        if gate.intervention_kind == "exception":
            phase = "exception_gate"
        set_phase(scope_id, phase)
        await_confirm = gate.await_confirm if gate.await_confirm is not None else False
        pending: dict[str, Any] | None = None
        if report_body.strip() or await_confirm:
            pending = {
                "node_id": node_id,
                "report_body": report_body,
                "await_confirm": await_confirm,
                "tokens_used": tokens_used,
                "duration_seconds": duration_seconds,
                "stage_id": stage_id,
            }
        reason = (
            f"{node_display_name(node_id)} 待确认总结，请填写表单后归档推进"
            if await_confirm
            else f"{node_display_name(node_id)} 需人工填写问卷后继续"
        )
        gate_state = self.mark_human_gate(
            scope_type=scope_type,
            scope_id=scope_id,
            room_id=room_id,
            node_id=node_id,
            reason=reason,
            ticket_title=ticket_title,
            hitl_form_schema=hitl_schema,
            pending_delivery=pending,
            intervention_kind=gate.intervention_kind,
        )
        if await_confirm:
            append_history_event(
                scope_id,
                {
                    "event": "node_pending_confirm",
                    "room_id": room_id,
                    "node_id": node_id,
                    "tokens_used": tokens_used,
                    "duration_seconds": duration_seconds,
                    "dynamic_form": True,
                },
            )
        return {
            "status": "human_intervention",
            "node_id": node_id,
            "skipped_nodes": skipped_nodes or None,
            "pending_confirm": await_confirm,
            "dynamic_hitl": True,
            **gate_state,
        }

    def mark_human_gate(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        reason: str = "",
        ticket_title: str = "",
        hitl_form_schema: dict[str, Any] | None = None,
        pending_delivery: dict[str, Any] | None = None,
        intervention_kind: str = "gate",
    ) -> dict[str, Any]:
        sid = scope_id.strip()
        room_state = load_room_state(sid) or {}
        room_state = dict(room_state)
        room_state["status"] = "human_intervention"
        room_state["current_node_id"] = node_id
        room_state["intervention_kind"] = intervention_kind
        room_state.pop("hitl_locked", None)
        room_state.pop("hitl_submission", None)
        if hitl_form_schema:
            room_state["hitl_form_schema"] = hitl_form_schema
        else:
            room_state.pop("hitl_form_schema", None)
        if pending_delivery:
            room_state["pending_delivery"] = pending_delivery
        save_room_state(sid, room_state)

        msg = reason or f"节点 {node_display_name(node_id)} 需人工处理"
        gate_binding = resolve_node_binding(
            node_id, scope_type=scope_type, scope_id=sid, ticket_title=ticket_title
        )
        append_history_event(
            sid,
            {
                "event": "human_gate",
                "room_id": room_id,
                "node_id": node_id,
                "text": msg,
                "intervention_kind": intervention_kind,
                "log_type": "warning",
                "agent_id": str(gate_binding.get("host_profile_id") or "default"),
            },
        )
        schedule_human_intervention_notify(
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            ticket_title=ticket_title,
            reason=msg,
        )
        return room_state

    async def enter_solution_review_gate(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        report_body: str,
        tokens_used: int,
        duration_seconds: int,
        stage_id: int,
        ticket_title: str,
        skipped_nodes: list[str] | None = None,
    ) -> dict[str, Any]:
        """方案评审节点：加载 solution_review.json，进入专用人工评审面板（非问卷）。"""
        from synapse.rd_meeting.solution_review import (
            load_solution_review_payload,
            validate_solution_review_json,
        )

        sid = scope_id.strip()
        set_phase(sid, "result_gate")
        ok, val_errors = validate_solution_review_json(sid)
        if not ok:
            gate = self.mark_human_gate(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                node_id=node_id,
                reason=(
                    f"{node_display_name(node_id)} 结构化评审产物未就绪："
                    + "; ".join(val_errors)
                ),
                ticket_title=ticket_title,
                hitl_form_schema=resolve_hitl_schema_for_gate(
                    resolve_node_binding(node_id),
                    dynamic_schema=None,
                    reason="; ".join(val_errors),
                    intervention_kind="exception",
                ),
                pending_delivery={
                    "node_id": node_id,
                    "report_body": report_body,
                    "await_confirm": False,
                    "tokens_used": tokens_used,
                    "duration_seconds": duration_seconds,
                    "stage_id": stage_id,
                },
                intervention_kind="exception",
            )
            set_phase(sid, "exception_gate")
            return {
                "status": "human_intervention",
                "node_id": node_id,
                "exception": True,
                "validation_errors": val_errors,
                **gate,
            }

        skipped = set(skipped_nodes or [])
        sr_payload = load_solution_review_payload(sid, skipped_node_ids=skipped)
        pending: dict[str, Any] = {
            "node_id": node_id,
            "report_body": report_body,
            "await_confirm": True,
            "tokens_used": tokens_used,
            "duration_seconds": duration_seconds,
            "stage_id": stage_id,
            "solution_review_payload": sr_payload,
        }
        gate = self.mark_human_gate(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            reason=f"{node_display_name(node_id)} 待人工方案评审（补丁选择 + 通过/不通过）",
            ticket_title=ticket_title,
            hitl_form_schema=None,
            pending_delivery=pending,
            intervention_kind="solution_review",
        )
        append_history_event(
            sid,
            {
                "event": "solution_review_gate",
                "room_id": room_id,
                "node_id": node_id,
                "text": f"{node_display_name(node_id)} 待人工方案评审（补丁选择 + 通过/不通过）",
                "intervention_kind": "solution_review",
                "tokens_used": tokens_used,
                "duration_seconds": duration_seconds,
                "log_type": "info",
            },
        )
        return {
            "status": "human_intervention",
            "node_id": node_id,
            "skipped_nodes": skipped_nodes or None,
            "pending_confirm": True,
            "solution_review_payload": sr_payload,
            **gate,
        }

    def confirm_solution_review_decision(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        decision: str,
        comment: str = "",
        patches: list[dict[str, Any]] | None = None,
        ticket_title: str = "",
        agent_pool: Any | None = None,
    ) -> dict[str, Any]:
        """方案评审专用裁决：通过则归档并推进；不通过则落盘结论并阻断流程（异常门控）。"""
        from synapse.rd_meeting.solution_review import apply_human_decision

        sid = scope_id.strip()
        room_state = load_room_state(sid) or {}
        pending = room_state.get("pending_delivery")
        if not isinstance(pending, dict):
            raise ValueError("no_pending_delivery")
        node_id = str(pending.get("node_id") or room_state.get("current_node_id") or "")
        if node_id != "solution_review":
            raise ValueError("not_solution_review_node")

        dec = (decision or "").strip().lower()
        if dec not in ("approve", "reject"):
            raise ValueError("invalid_decision")

        demand_no = sid
        try:
            from synapse.rd_meeting.auto_split_assets import _resolve_demand_no

            demand_no = _resolve_demand_no(scope_type, sid)  # type: ignore[arg-type]
        except Exception:
            pass

        payload = apply_human_decision(
            sid,
            decision="approve" if dec == "approve" else "reject",
            comment=comment,
            patches=patches if dec == "approve" else None,
            demand_no=demand_no,
        )

        if dec == "reject":
            room_state = dict(load_room_state(sid) or {})
            room_state["status"] = "human_intervention"
            room_state["intervention_kind"] = "exception"
            room_state["solution_review_blocked"] = True
            if comment.strip():
                room_state["escalate_reason"] = comment.strip()
            pending["solution_review_payload"] = payload
            pending["await_confirm"] = False
            room_state["pending_delivery"] = pending
            save_room_state(sid, room_state)
            set_phase(sid, "exception_gate")
            append_history_event(
                sid,
                {
                    "event": "solution_review_rejected",
                    "room_id": room_id,
                    "node_id": node_id,
                    "comment": comment.strip(),
                    "log_type": "warning",
                    "agent_id": "user",
                },
            )
            return {
                "status": "blocked",
                "node_id": node_id,
                "solution_review_payload": payload,
                "room_state": room_state,
            }

        stage_id = int(pending.get("stage_id") or stage_id_for_node_id(node_id))
        stage_name = stage_name_for_id(stage_id)
        validation = validate_node_archive_artifacts(sid, stage_name, node_id)
        if not validation.ok:
            raise ValueError("node_archive_validation_failed: " + "; ".join(validation.errors))

        tokens_used = int(pending.get("tokens_used") or 0)
        duration = int(pending.get("duration_seconds") or 0)
        out = self.on_node_complete(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            artifacts=validation.artifacts,
            tokens_used=tokens_used,
            duration_seconds=duration,
            sync_userwork=True,
            advance=True,
            ticket_title=ticket_title,
            agent_pool=agent_pool,
        )
        rs = dict(load_room_state(sid) or {})
        rs.pop("pending_delivery", None)
        rs.pop("hitl_form_schema", None)
        rs.pop("solution_review_blocked", None)
        rs.pop("intervention_kind", None)
        save_room_state(sid, rs)
        append_history_event(
            sid,
            {
                "event": "solution_review_approved",
                "room_id": room_id,
                "node_id": node_id,
                "comment": comment.strip(),
                "log_type": "info",
                "agent_id": "user",
            },
        )
        return {
            "status": "approved",
            "node_id": node_id,
            "solution_review_payload": payload,
            **out,
        }

    async def enter_node_review_gate(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        binding: dict[str, Any],
        report_body: str,
        tokens_used: int,
        duration_seconds: int,
        stage_id: int,
        ticket_title: str,
        agent_pool: Any | None = None,
        skipped_nodes: list[str] | None = None,
    ) -> dict[str, Any]:
        """human_confirm 且会中问卷已满足：装配 node_review 并进入 result_confirm 门控。"""
        from synapse.rd_meeting.solution_review import uses_solution_review_gate

        if uses_solution_review_gate(node_id):
            return await self.enter_solution_review_gate(
                scope_type=scope_type,
                scope_id=scope_id,
                room_id=room_id,
                node_id=node_id,
                report_body=report_body,
                tokens_used=tokens_used,
                duration_seconds=duration_seconds,
                stage_id=stage_id,
                ticket_title=ticket_title,
                skipped_nodes=skipped_nodes,
            )

        sid = scope_id.strip()
        from synapse.rd_meeting.agent_session import resolve_meeting_orchestrator
        from synapse.rd_meeting.pipeline import run_node_review_step

        set_phase(sid, "result_gate")
        review_payload: dict[str, Any] | None = None
        try:
            review_payload = await run_node_review_step(
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id=sid,
                room_id=room_id,
                node_id=node_id,
                binding=binding,
                report_body=report_body,
                tokens_used=tokens_used,
                duration_seconds=duration_seconds,
                stage_id=stage_id,
                agent_pool=agent_pool,
                orchestrator=resolve_meeting_orchestrator(agent_pool),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("run_node_review_step failed scope=%s: %s", sid, exc)

        pending: dict[str, Any] = {
            "node_id": node_id,
            "report_body": report_body,
            "await_confirm": True,
            "tokens_used": tokens_used,
            "duration_seconds": duration_seconds,
            "stage_id": stage_id,
        }
        if review_payload is not None:
            pending["review_payload"] = review_payload
        gate = self.mark_human_gate(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            reason=f"{node_display_name(node_id)} 待人工确认总结，请审阅后通过/打回/异常",
            ticket_title=ticket_title,
            hitl_form_schema=None,
            pending_delivery=pending,
            intervention_kind="result_confirm",
        )
        append_history_event(
            sid,
            {
                "event": "node_pending_confirm",
                "room_id": room_id,
                "node_id": node_id,
                "tokens_used": tokens_used,
                "duration_seconds": duration_seconds,
                "review_summary_count": len((review_payload or {}).get("summaries") or []),
                "review_artifact_count": len((review_payload or {}).get("artifacts") or []),
            },
        )
        return {
            "status": "human_intervention",
            "node_id": node_id,
            "skipped_nodes": skipped_nodes or None,
            "pending_confirm": True,
            "review_payload": review_payload,
            **gate,
        }

    async def _ensure_host_interactive_questionnaire(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        node_id: str,
        binding: dict[str, Any],
        prompt: str,
        report_body: str,
        tokens_used: int,
        duration_seconds: int,
        stage_id: int,
        ticket_title: str,
        agent_pool: Any | None,
        skipped_nodes: list[str] | None,
        host_profile_id: str,
        host_id: str,
        run_host: Any,
    ) -> dict[str, Any]:
        """校验已通过但主控未交 interactive 问卷：强制重跑主控直至其生成（无系统兜底表单）。"""
        sid = scope_id.strip()
        rs_locked = load_room_state(sid) or {}
        if should_enter_node_review_after_hitl_locked(sid, node_id, rs_locked):
            return await self.enter_node_review_gate(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                node_id=node_id,
                binding=binding,
                report_body=report_body,
                tokens_used=tokens_used,
                duration_seconds=duration_seconds,
                stage_id=stage_id,
                ticket_title=ticket_title,
                agent_pool=agent_pool,
                skipped_nodes=skipped_nodes,
            )
        round_n = bump_clarify_round(sid)
        if round_n > MAX_HOST_QUESTIONNAIRE_ATTEMPTS:
            append_history_event(
                sid,
                {
                    "event": "node_failed",
                    "room_id": room_id,
                    "node_id": node_id,
                    "error": "主控多次未提交 interactive 会中问卷",
                    "log_type": "warning",
                    "agent_id": host_profile_id,
                },
            )
            gate = self.mark_human_gate(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                node_id=node_id,
                reason=(
                    f"{node_display_name(node_id)}：主控多次未提交会中问卷，"
                    "请人工介入或调整主控提示词后重跑"
                ),
                ticket_title=ticket_title,
                hitl_form_schema=resolve_hitl_schema_for_gate(
                    binding,
                    dynamic_schema=None,
                    reason="主控未提交 interactive 问卷",
                    intervention_kind="exception",
                ),
                pending_delivery={
                    "node_id": node_id,
                    "report_body": report_body,
                    "await_confirm": False,
                    "tokens_used": tokens_used,
                    "duration_seconds": duration_seconds,
                    "stage_id": stage_id,
                },
                intervention_kind="exception",
            )
            set_phase(sid, "exception_gate")
            return {
                "status": "human_intervention",
                "node_id": node_id,
                "exception": True,
                **gate,
            }

        append_history_event(
            sid,
            {
                "event": "host_retry",
                "room_id": room_id,
                "node_id": node_id,
                "reason": "主控未提交 interactive 会中问卷，强制重跑",
                "round": round_n,
                "log_type": "warning",
                "agent_id": host_profile_id,
            },
        )
        retry_prompt = f"{prompt}\n\n{prompt_require_interactive_questionnaire()}"
        retry_result = await run_host(retry_prompt)
        retry_questionnaire = consume_pending_questionnaire(sid)
        if retry_result.success:
            report_body = str(retry_result.data or retry_result.error or report_body)

        if retry_questionnaire and retry_questionnaire.get("schema"):
            kind = (retry_questionnaire.get("kind") or "interactive").strip().lower()
            if kind == "interactive":
                return self._gate_from_tool_questionnaire(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    questionnaire={**retry_questionnaire, "kind": "interactive"},
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration_seconds,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    skipped_nodes=skipped_nodes,
                )
            if kind == "exception":
                return self._gate_from_tool_questionnaire(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    questionnaire=retry_questionnaire,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration_seconds,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    skipped_nodes=skipped_nodes,
                )

        hitl_gate = extract_hitl_from_agent_output(report_body)
        report_body = hitl_gate.clean_body
        if hitl_gate.explicit and hitl_gate.intervention_kind in ("interactive", "exception"):
            return self._gate_from_agent_hitl(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                node_id=node_id,
                binding=binding,
                gate=hitl_gate,
                report_body=report_body,
                tokens_used=tokens_used,
                duration_seconds=duration_seconds,
                stage_id=stage_id,
                ticket_title=ticket_title,
                skipped_nodes=skipped_nodes,
            )

        rs = dict(load_room_state(sid) or {})
        rs["status"] = "processing"
        rs["rework_instruction"] = prompt_require_interactive_questionnaire()
        save_room_state(sid, rs)
        schedule_run_node(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            ticket_title=ticket_title,
            agent_pool=agent_pool,
        )
        append_history_event(
            sid,
            {
                "event": "awaiting_host_questionnaire",
                "room_id": room_id,
                "node_id": node_id,
                "text": "主控仍未提交会中问卷，已自动续跑本节点",
                "log_type": "info",
                "agent_id": host_id,
            },
        )
        return {
            "status": "processing",
            "node_id": node_id,
            "awaiting_host_questionnaire": True,
            "skipped_nodes": skipped_nodes or None,
        }

    def confirm_node_delivery(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        approved: bool,
        comment: str = "",
        ticket_title: str = "",
        sync_userwork: bool = True,
        agent_pool: Any | None = None,
        mode: str = "",
    ) -> dict[str, Any]:
        """人工确认待归档总结：通过/打回/异常介入三种模式。

        - ``mode="approve"`` 或 ``approved=True``：归档并推进
        - ``mode="reject"`` 或 ``approved=False``：清 pending、写返工备注、重跑节点
        - ``mode="escalate"``：转入 exception_gate，等待人工兜底（不重跑、不归档）
        """
        sid = scope_id.strip()
        room_state = load_room_state(sid) or {}
        pending = room_state.get("pending_delivery")
        if not isinstance(pending, dict) or not pending.get("report_body"):
            raise ValueError("no_pending_delivery")

        node_id = str(pending.get("node_id") or room_state.get("current_node_id") or "")
        if not node_id:
            raise ValueError("invalid_pending_node")

        mode_norm = (mode or "").strip().lower()
        if mode_norm == "escalate":
            room_state = dict(room_state)
            room_state["status"] = "human_intervention"
            room_state["intervention_kind"] = "exception"
            if comment.strip():
                room_state["escalate_reason"] = comment.strip()
            save_room_state(sid, room_state)
            set_phase(sid, "exception_gate")
            append_history_event(
                sid,
                {
                    "event": "hitl_escalated",
                    "room_id": room_id,
                    "node_id": node_id,
                    "comment": comment.strip(),
                    "log_type": "warning",
                    "agent_id": "user",
                },
            )
            return {"status": "escalated", "node_id": node_id, "room_state": room_state}

        if mode_norm in ("approve", "reject"):
            approved = mode_norm == "approve"

        if not approved:
            set_ready_for_node_review(sid, False)
            reset_human_confirm_lifecycle(sid)
            room_state = dict(room_state)
            room_state.pop("pending_delivery", None)
            room_state["status"] = "processing"
            if comment.strip():
                room_state["rework_instruction"] = comment.strip()
            save_room_state(sid, room_state)
            append_history_event(
                sid,
                {
                    "event": "hitl_rejected",
                    "room_id": room_id,
                    "node_id": node_id,
                    "comment": comment.strip(),
                    "log_type": "warning",
                    "agent_id": "user",
                },
            )
            try:
                from synapse.rd_meeting.agent_activity import record_host_human_input
                from synapse.rd_meeting.binding import resolve_node_binding

                binding = resolve_node_binding(node_id)
                host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
                record_host_human_input(
                    sid,
                    node_id,
                    host_id,
                    input_kind="summary_feedback",
                    title="人类驳回总结",
                    summary=comment.strip(),
                )
            except Exception as exc:
                logger.debug("hitl reject activity record failed: %s", exc)
            schedule_run_node(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                ticket_title=ticket_title,
            )
            return {"status": "rework", "node_id": node_id, "room_state": room_state}

        stage_id = int(pending.get("stage_id") or stage_id_for_node_id(node_id))
        stage_name = stage_name_for_id(stage_id)
        validation = validate_node_archive_artifacts(sid, stage_name, node_id)
        if not validation.ok:
            raise ValueError("node_archive_validation_failed: " + "; ".join(validation.errors))
        tokens_used = int(pending.get("tokens_used") or 0)
        duration = int(pending.get("duration_seconds") or 0)

        out = self.on_node_complete(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            artifacts=validation.artifacts,
            tokens_used=tokens_used,
            duration_seconds=duration,
            sync_userwork=sync_userwork,
            advance=True,
            ticket_title=ticket_title,
            agent_pool=agent_pool,
        )

        rs = load_room_state(sid) or {}
        rs = dict(rs)
        rs.pop("pending_delivery", None)
        rs.pop("hitl_form_schema", None)
        rs.pop("hitl_locked", None)
        rs.pop("hitl_submission", None)
        set_phase(sid, "completed")
        save_room_state(sid, rs)

        from synapse.rd_meeting.binding import resolve_node_binding

        binding = resolve_node_binding(node_id)
        host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
        append_history_event(
            sid,
            {
                "event": "host_llm_begin",
                "room_id": room_id,
                "node_id": node_id,
                "host_profile_id": host_id,
                "log_type": "info",
                "agent_id": host_id,
                "llm_begin_kind": "delivery_confirmed",
                "chat_text": format_host_first_call_chat(kind="delivery_confirmed"),
            },
        )
        append_history_event(
            sid,
            {
                "event": "hitl_approved",
                "room_id": room_id,
                "node_id": node_id,
                "comment": comment.strip(),
                "log_type": "user",
                "agent_id": "user",
            },
        )
        try:
            from synapse.rd_meeting.agent_activity import record_host_human_input
            from synapse.rd_meeting.binding import resolve_node_binding

            binding = resolve_node_binding(node_id)
            host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
            record_host_human_input(
                sid,
                node_id,
                host_id,
                input_kind="summary_feedback",
                title="人类确认通过",
                summary=comment.strip() or "用户确认节点产出",
            )
        except Exception as exc:
            logger.debug("hitl approve activity record failed: %s", exc)
        return {"status": "approved", **out, "room_state": rs}

    async def run_current_node(
        self,
        *,
        scope_type: str,
        scope_id: str,
        room_id: str,
        ticket_title: str = "",
        agent_pool: Any | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        sid = scope_id.strip()
        dev = load_dev_status(sid)
        if dev is None:
            raise ValueError("dev_status_not_found")

        skip_prep = self.advance_past_disabled_nodes(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            ticket_title=ticket_title,
            sync_userwork=True,
            agent_pool=agent_pool,
            schedule_pipeline_advance=False,
        )
        skipped_nodes: list[str] = list(skip_prep.get("skipped_nodes") or [])
        if skip_prep.get("status") == "completed":
            return {
                "status": "completed",
                "skipped_nodes": skipped_nodes,
                "skipped_llm": True,
            }
        node_id = str(skip_prep.get("current_node_id") or "pending")
        if node_id == "pending" or skip_prep.get("status") == "pending":
            raise ValueError("invalid_current_node")
        from synapse.rd_sop.manifest import is_system_node

        if is_system_node(node_id):
            raise ValueError("system_node_use_pipeline")
        dev = skip_prep.get("dev_status") or load_dev_status(sid)
        if dev is None:
            raise ValueError("dev_status_not_found")

        binding = resolve_node_binding(
            node_id,
            scope_type=scope_type,
            scope_id=sid,
            ticket_title=ticket_title,
        )

        binding["node_id"] = node_id
        node_name = node_display_name(node_id)
        participants = build_meeting_participants(binding)
        init_text = build_node_init_message(
            binding,
            node_id=node_id,
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_id=sid,
        )
        host_id = str(binding.get("host_profile_id") or "default")

        append_history_event(
            sid,
            {
                "event": "node_started",
                "room_id": room_id,
                "node_id": node_id,
                "text": init_text,
                "agent_id": host_id,
                "log_type": "info",
                "binding": {
                    "enabled": binding.get("enabled", True),
                    "host_profile_id": binding.get("host_profile_id"),
                    "worker_profile_ids": binding.get("worker_profile_ids"),
                },
                "participants": participants,
            },
        )

        room_state = load_room_state(sid) or {}
        room_state = dict(room_state)
        room_state["status"] = "processing"
        room_state["current_node_id"] = node_id
        room_state["agents_active"] = [
            {"profile_id": p["profile_id"], "role": p["role"], "display_name": p["display_name"]}
            for p in participants
        ]
        room_state["participants"] = participants
        room_state["current_node_binding"] = {
            "node_id": node_id,
            "node_name": node_name,
            "host_profile_id": binding.get("host_profile_id"),
            "worker_profile_ids": binding.get("worker_profile_ids"),
            "node_intent": binding.get("node_intent"),
            "human_confirm": binding.get("human_confirm"),
        }
        nm = room_state.get("node_metrics")
        if not isinstance(nm, dict):
            nm = {}
        if node_id not in nm or not isinstance(nm.get(node_id), dict):
            nm[node_id] = {"started_at": _now_iso(), "seconds": 0, "tokens": 0}
        room_state["node_metrics"] = nm
        rework = str(room_state.pop("rework_instruction", "") or "").strip()
        room_state.pop("current_work_plan", None)
        llm_begin_kind = str(room_state.pop("pending_host_llm_begin_kind", "") or "").strip() or "start_work"
        if llm_begin_kind != "delivery_confirmed":
            llm_begin_kind = "start_work"
        save_room_state(sid, room_state)
        set_phase(sid, "running")

        use_dry = _dry_run_enabled() if dry_run is None else dry_run
        started = time.monotonic()
        tokens_used = 0
        report_body = ""
        tool_questionnaire: dict[str, Any] | None = None
        clear_pending_questionnaire(sid)

        host_run_fn: Any | None = None
        host_run_prompt = ""
        host_run_profile_id = str(binding.get("host_profile_id") or host_id or "default")

        if use_dry:
            report_body = (
                f"# {node_display_name(node_id)} 交付结论（dry-run）\n\n"
                f"scope: {scope_type}/{sid}\n\n"
                f"本节点模拟执行完成，交付完成。完成时间：{_now_iso()}。\n"
            )
            tokens_used = 128
            _dry_stage = stage_name_for_id(
                int(dev.get("stage_id") or stage_id_for_node_id(node_id))
            )
            _write_simulated_agent_deliverables(sid, _dry_stage, node_id, report_body)
        else:
            host_profile_id = str(binding.get("host_profile_id") or host_id or "default")
            host_profile = _resolve_profile(host_profile_id)
            if host_profile is None or agent_pool is None:
                report_body = (
                    f"# {node_display_name(node_id)} 交付结论（stub）\n\n"
                    "Agent 池不可用或未找到主控画像（host）；已写入占位产物，待后续重试。\n"
                )
                tokens_used = 64
                use_dry = True
            else:
                scope_dir(sid).mkdir(parents=True, exist_ok=True)

                worker_ids = [
                    str(w).strip()
                    for w in (binding.get("worker_profile_ids") or [])
                    if str(w).strip() and str(w).strip() != host_profile_id
                ]
                append_history_event(
                    sid,
                    {
                        "event": "prewarm_workers",
                        "room_id": room_id,
                        "node_id": node_id,
                        "worker_profile_ids": worker_ids,
                        "log_type": "info",
                        "agent_id": host_profile_id,
                    },
                )
                prewarm_gen = bump_meeting_prewarm_generation(room_id)
                await self._prewarm_meeting_room(
                    agent_pool=agent_pool,
                    room_id=room_id,
                    scope_type=scope_type,
                    scope_id=sid,
                    ticket_title=ticket_title,
                    binding=binding,
                    host_profile_id=host_profile_id,
                    prewarm_generation=prewarm_gen,
                )

                host_sid = host_session_id(room_id)
                host_agent = await agent_pool.get_or_create(
                    session_id=host_sid,
                    profile=host_profile,
                )
                reused_prompt = self._configure_meeting_agent(
                    host_agent,
                    role="host",
                    binding=binding,
                    scope_type=scope_type,
                    scope_id=sid,
                    ticket_title=ticket_title,
                    scope_path=str(scope_dir(sid)),
                )

                cached_user, _ = resolve_cached_host_user_prompt(sid, binding)
                if cached_user:
                    prompt = cached_user
                else:
                    prompt = build_node_prompt(
                        scope_type=scope_type,
                        scope_id=sid,
                        node_id=node_id,
                        binding=binding,
                        ticket_title=ticket_title,
                    )
                user_ctx = drain_user_context_for_prompt(sid)
                if user_ctx:
                    prompt = f"{prompt}\n\n{user_ctx}"
                try:
                    from synapse.rd_meeting.hitl_context import read_hitl_context
                    from synapse.rd_meeting.hitl_feedback import (
                        prompt_for_followup_interactive_round,
                    )

                    prior_ctx = read_hitl_context(sid, node_id, binding=binding)
                    prior_rounds = len(prior_ctx.get("rounds") or [])
                    if prior_rounds >= 1:
                        prompt = (
                            f"{prompt}\n\n"
                            f"{prompt_for_followup_interactive_round(prior_rounds + 1)}"
                        )
                except Exception:
                    pass
                if rework:
                    prompt = f"{prompt}\n\n## 人工返工意见\n{rework}\n"
                rs_cont = load_room_state(sid) or {}
                pending_ctx = rs_cont.get("pending_delivery")
                if (
                    isinstance(pending_ctx, dict)
                    and pending_ctx.get("report_body")
                    and not pending_ctx.get("await_confirm", True)
                ):
                    body = str(pending_ctx.get("report_body") or "").strip()
                    if body:
                        prompt = f"{prompt}\n\n## 上一轮待续上下文\n{body}\n"
                from synapse.rd_meeting.pipeline_chat import format_host_first_call_chat

                append_history_event(
                    sid,
                    {
                        "event": "host_llm_begin",
                        "room_id": room_id,
                        "node_id": node_id,
                        "host_profile_id": host_profile_id,
                        "log_type": "info",
                        "agent_id": host_profile_id,
                        "llm_begin_kind": llm_begin_kind,
                        "reused_host_prompt_cache": reused_prompt,
                        "chat_text": format_host_first_call_chat(kind=llm_begin_kind),  # type: ignore[arg-type]
                    },
                )
                meeting_session = ensure_host_session(room_id, host_profile_id)

                host_act = resolve_binding_for_profile(
                    sid, node_id, host_profile_id, host_profile_id=host_profile_id
                )
                record_input(
                    host_act,
                    source="system",
                    input_kind="node_task",
                    title="节点任务指令",
                    summary=prompt[:1200],
                    detail={"reused_host_prompt_cache": reused_prompt},
                )

                async def _run_host(message: str) -> Any:
                    bind_meeting_agent_session(host_agent, meeting_session)
                    try:
                        host_agent._hitl_locked = False
                        return await host_agent.execute_task_from_message(
                            message,
                            usage_scene=f"rd_meeting_{sid}_{node_id}",
                        )
                    finally:
                        clear_meeting_agent_session(host_agent)

                result = await _run_host(prompt)
                # 主控通过 submit_hitl_questionnaire 工具直接锁定时优先采用
                tool_questionnaire = consume_pending_questionnaire(sid)
                if result.success:
                    report_body = str(result.data or result.error or "完成")
                else:
                    err = str(result.error or "unknown")
                    append_history_event(
                        sid,
                        {
                            "event": "node_failed",
                            "room_id": room_id,
                            "node_id": node_id,
                            "error": err,
                        },
                    )
                    gate = self.mark_human_gate(
                        scope_type=scope_type,
                        scope_id=sid,
                        room_id=room_id,
                        node_id=node_id,
                        reason=f"{node_display_name(node_id)} 执行异常，需人工介入：{err}",
                        ticket_title=ticket_title,
                        hitl_form_schema=resolve_hitl_schema_for_gate(
                            binding,
                            dynamic_schema=None,
                            reason=err,
                            intervention_kind="exception",
                        ),
                        intervention_kind="exception",
                    )
                    set_phase(sid, "exception_gate")
                    return {
                        "status": "human_intervention",
                        "node_id": node_id,
                        "exception": True,
                        **gate,
                    }

                usage = getattr(host_agent, "last_usage", None) or {}
                tokens_used = int(usage.get("total_tokens") or usage.get("tokens") or 256)
                append_history_event(
                    sid,
                    {
                        "event": "host_llm_end",
                        "room_id": room_id,
                        "node_id": node_id,
                        "host_profile_id": host_profile_id,
                        "success": bool(result.success),
                        "report_preview": report_body[:400],
                        "tokens_used": tokens_used,
                        "log_type": "info" if result.success else "warning",
                        "agent_id": host_profile_id,
                    },
                )

                # E：human_confirm 节点的「自动重跑一次」
                # 触发：未通过工具提交问卷 + 终稿无标记块 + 产出物文档校验失败
                _retry_stage_name = stage_name_for_id(
                    int(dev.get("stage_id") or stage_id_for_node_id(node_id))
                )
                if (
                    bool(binding.get("human_confirm"))
                    and tool_questionnaire is None
                    and not extract_hitl_from_agent_output(report_body).explicit
                    and not validate_node_archive_artifacts(sid, _retry_stage_name, node_id).ok
                ):
                    append_history_event(
                        sid,
                        {
                            "event": "host_retry",
                            "room_id": room_id,
                            "node_id": node_id,
                            "reason": "主控未提交结构化问卷且产出物文档未通过校验，自动重跑一次",
                            "log_type": "warning",
                            "agent_id": host_profile_id,
                        },
                    )
                    retry_prompt = (
                        f"{prompt}\n\n"
                        "## ⚠️ 系统提示：上一次输出未提交合法问卷\n"
                        "你上一次的回复既没有调用 `submit_hitl_questionnaire` 工具，"
                        "也没有按 `whalecloud-dev-tool-ask-user` 技能在末尾输出 "
                        "`<!-- hitl-questionnaire -->` 标记块；同时约定产出物文档未通过校验。\n\n"
                        "**本次重跑要求**：直接调用 `submit_hitl_questionnaire` 工具提交 "
                        "`kind=interactive` 会中问卷，无需再写工具调用前的总结性文字；"
                        "**禁止** `kind=result_confirm`（完成总结由用户在问卷无补充后系统自动进入）。\n"
                        "调用工具后立即停止，不要重复总结。\n\n"
                        "**题目颗粒度（强约束）**：每个独立可决策点 = 一道独立题。\n"
                        "- 禁止把多个决策点合并成一道「整体确认 / 部分修改 / 拒绝」单选；\n"
                        "- 交付文档中列出的每个 P0 问题 / 待澄清项都要单独成题，"
                        "把「可默认结论」放进选项里（可标 ✅ 推荐）；\n"
                        "- 即使有 14 题也要全部列出，前端会用 stepped 布局分步引导。\n"
                        "- ``summary`` 只写与 questions 对齐的待确认简表；"
                        "禁止 ``### 下一步``、确认后进入某阶段、Phase 1~N、SOP 下一节点预告。"
                    )
                    retry_result = await _run_host(retry_prompt)
                    retry_questionnaire = consume_pending_questionnaire(sid)
                    if retry_result.success:
                        report_body = str(retry_result.data or retry_result.error or "完成")
                    tool_questionnaire = retry_questionnaire or tool_questionnaire
                    append_history_event(
                        sid,
                        {
                            "event": "host_retry_end",
                            "room_id": room_id,
                            "node_id": node_id,
                            "tool_used": bool(retry_questionnaire),
                            "log_type": "info",
                            "agent_id": host_profile_id,
                        },
                    )

                host_run_fn = _run_host
                host_run_prompt = prompt
                host_run_profile_id = host_profile_id

        stage_id = int(dev.get("stage_id") or stage_id_for_node_id(node_id))
        stage_name = stage_name_for_id(stage_id)
        duration = max(1, int(time.monotonic() - started))

        need_human_confirm = bool(binding.get("human_confirm"))
        room_rs = load_room_state(sid) or {}

        # 本轮回主控 submit_hitl_questionnaire 优先于历史 hitl_locked / ready 标记，
        # 避免「用户已填过一轮 + 归档已就绪」时跳过新一轮 interactive 问卷直达 NodeReview。
        if need_human_confirm and tool_questionnaire and tool_questionnaire.get("schema"):
            t_kind = (tool_questionnaire.get("kind") or "interactive").strip().lower()
            if t_kind == "interactive":
                return self._gate_from_tool_questionnaire(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    questionnaire={**tool_questionnaire, "kind": "interactive"},
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    skipped_nodes=skipped_nodes or None,
                )
            if t_kind == "exception":
                return self._gate_from_tool_questionnaire(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    questionnaire=tool_questionnaire,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    skipped_nodes=skipped_nodes or None,
                )

        ready_for_review = should_enter_node_review_gate(sid, node_id, room_rs)

        if need_human_confirm and not ready_for_review:
            hitl_gate = extract_hitl_from_agent_output(report_body)
            report_body = hitl_gate.clean_body
            if hitl_gate.explicit and hitl_gate.intervention_kind in ("interactive", "exception"):
                append_history_event(
                    sid,
                    {
                        "event": "hitl_dynamic",
                        "room_id": room_id,
                        "node_id": node_id,
                        "detail": (
                            f"主控输出动态问卷 kind={hitl_gate.intervention_kind} "
                            f"questions={len((hitl_gate.schema or {}).get('questions') or [])}"
                        ),
                        "log_type": "info",
                        "agent_id": host_id,
                    },
                )
                return self._gate_from_agent_hitl(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    gate=hitl_gate,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    skipped_nodes=skipped_nodes or None,
                )
        else:
            hitl_gate = extract_hitl_from_agent_output(report_body)
            report_body = hitl_gate.clean_body

        if need_human_confirm:
            validation = validate_node_archive_artifacts(sid, stage_name, node_id)
            if not validation.ok:
                append_history_event(
                    sid,
                    {
                        "event": "node_validation_failed",
                        "room_id": room_id,
                        "node_id": node_id,
                        "errors": validation.errors,
                    },
                )
                gate = self.mark_human_gate(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    reason=(
                        f"{node_display_name(node_id)} 产出物文档未达标，需人工介入："
                        + "; ".join(validation.errors)
                    ),
                    ticket_title=ticket_title,
                    hitl_form_schema=resolve_hitl_schema_for_gate(
                        binding,
                        dynamic_schema=None,
                        reason="; ".join(validation.errors),
                        intervention_kind="exception",
                    ),
                    pending_delivery={
                        "node_id": node_id,
                        "report_body": report_body,
                        "await_confirm": False,
                        "tokens_used": tokens_used,
                        "duration_seconds": duration,
                        "stage_id": stage_id,
                    },
                    intervention_kind="exception",
                )
                set_phase(sid, "exception_gate")
                return {
                    "status": "human_intervention",
                    "node_id": node_id,
                    "exception": True,
                    "validation_errors": validation.errors,
                    **gate,
                }

            from synapse.rd_meeting.solution_review import (
                uses_solution_review_gate,
                validate_solution_review_json,
            )

            if uses_solution_review_gate(node_id):
                return await self.enter_solution_review_gate(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=int(duration),
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    skipped_nodes=skipped_nodes or None,
                )
            if ready_for_review:
                return await self.enter_node_review_gate(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=int(duration),
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    agent_pool=agent_pool,
                    skipped_nodes=skipped_nodes or None,
                )
            if host_run_fn is not None:
                return await self._ensure_host_interactive_questionnaire(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    prompt=host_run_prompt,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=int(duration),
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    agent_pool=agent_pool,
                    skipped_nodes=skipped_nodes or None,
                    host_profile_id=host_run_profile_id,
                    host_id=host_id,
                    run_host=host_run_fn,
                )
            rs_wait = dict(load_room_state(sid) or {})
            rs_wait["status"] = "processing"
            rs_wait["rework_instruction"] = prompt_require_interactive_questionnaire()
            save_room_state(sid, rs_wait)
            schedule_run_node(
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                ticket_title=ticket_title,
                agent_pool=agent_pool,
            )
            return {
                "status": "processing",
                "node_id": node_id,
                "awaiting_host_questionnaire": True,
                "skipped_nodes": skipped_nodes or None,
            }

        validation = validate_node_archive_artifacts(sid, stage_name, node_id)
        if not validation.ok:
            append_history_event(
                sid,
                {
                    "event": "node_validation_failed",
                    "room_id": room_id,
                    "node_id": node_id,
                    "errors": validation.errors,
                },
            )
            rs_fail = dict(load_room_state(sid) or {})
            rs_fail["status"] = "failed"
            save_room_state(sid, rs_fail)
            return {
                "status": "failed",
                "node_id": node_id,
                "validation_errors": validation.errors,
            }
        from synapse.rd_meeting.solution_review import uses_solution_review_gate

        if not uses_solution_review_gate(node_id):
            try:
                from synapse.rd_meeting.agent_session import resolve_meeting_orchestrator
                from synapse.rd_meeting.node_review import build_node_review_payload, save_node_review

                review_payload = await build_node_review_payload(
                    scope_type=scope_type,  # type: ignore[arg-type]
                    scope_id=sid,
                    room_id=room_id,
                    node_id=node_id,
                    binding=binding,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=int(duration),
                    stage_id=stage_id,
                    agent_pool=agent_pool,
                    orchestrator=resolve_meeting_orchestrator(agent_pool),
                    use_llm_summary=True,
                )
                save_node_review(sid, node_id, review_payload, sync_pending=False)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "persist node review before auto-complete failed scope=%s node=%s: %s",
                    sid,
                    node_id,
                    exc,
                )
        out = self.on_node_complete(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=node_id,
            artifacts=validation.artifacts,
            tokens_used=tokens_used,
            duration_seconds=duration,
            advance=True,
            ticket_title=ticket_title,
            agent_pool=agent_pool,
        )
        if skipped_nodes:
            out["skipped_nodes"] = skipped_nodes
        return out


def _mark_room_after_run_node_exception(
    orch: MeetingRoomOrchestrator,
    *,
    scope_type: str,
    scope_id: str,
    room_id: str,
    fail_node: str,
    ticket_title: str,
    error: str,
) -> None:
    """后台 run_node 未捕获异常：与主控执行失败一致，落盘 human_intervention。"""
    sid = scope_id.strip()
    err = (error or "unknown").strip()
    try:
        binding = resolve_node_binding(
            fail_node,
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_id=sid,
            ticket_title=ticket_title,
        )
        orch.mark_human_gate(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            node_id=fail_node,
            reason=f"{node_display_name(fail_node)} 执行异常，需人工介入：{err[:500]}",
            ticket_title=ticket_title,
            hitl_form_schema=resolve_hitl_schema_for_gate(
                binding,
                dynamic_schema=None,
                reason=err,
                intervention_kind="exception",
            ),
            intervention_kind="exception",
        )
        set_phase(sid, "exception_gate")
    except Exception as gate_exc:
        logger.warning("mark_human_gate after run_node exception failed scope=%s: %s", sid, gate_exc)
        rs_fail = dict(load_room_state(sid) or {})
        rs_fail["status"] = "failed"
        rs_fail["current_node_id"] = fail_node
        save_room_state(sid, rs_fail)


def schedule_run_node(
    *,
    scope_type: str,
    scope_id: str,
    room_id: str,
    ticket_title: str = "",
    agent_pool: Any | None = None,
    dry_run: bool | None = None,
    host_llm_begin_kind: str = "start_work",
) -> str:
    """后台执行当前节点，返回 task key。"""
    sid = scope_id.strip()
    if sid:
        rs = dict(load_room_state(sid) or {})
        rs["pending_host_llm_begin_kind"] = (host_llm_begin_kind or "start_work").strip() or "start_work"
        save_room_state(sid, rs)

    key = room_id.strip() or scope_id.strip()
    existing = _running_tasks.get(key)
    if existing and not existing.done():
        return key

    orch = MeetingRoomOrchestrator()

    async def _runner() -> None:
        try:
            await orch.run_current_node(
                scope_type=scope_type,
                scope_id=scope_id,
                room_id=room_id,
                ticket_title=ticket_title,
                agent_pool=agent_pool,
                dry_run=dry_run,
            )
        except Exception as exc:
            logger.exception("meeting room run_node failed room=%s: %s", room_id, exc)
            sid = scope_id.strip()
            rs_fail = load_room_state(sid) or {}
            fail_node = (
                str(rs_fail.get("current_node_id") or "pending") if isinstance(rs_fail, dict) else "pending"
            )
            err = str(exc)
            append_history_event(
                sid,
                {
                    "event": "node_failed",
                    "room_id": room_id,
                    "node_id": fail_node,
                    "error": err,
                    "text": err,
                    "id": uuid.uuid4().hex[:12],
                    "log_type": "error",
                    "agent_id": "system",
                },
            )
            _mark_room_after_run_node_exception(
                orch,
                scope_type=scope_type,
                scope_id=sid,
                room_id=room_id,
                fail_node=fail_node,
                ticket_title=ticket_title,
                error=err,
            )
        finally:
            _running_tasks.pop(key, None)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("schedule_run_node: no event loop, skip background run for %s", key)
        return key

    task = loop.create_task(_runner())
    _running_tasks[key] = task
    return key


def schedule_enter_node_review(
    *,
    scope_type: str,
    scope_id: str,
    room_id: str,
    ticket_title: str = "",
    agent_pool: Any | None = None,
) -> str:
    """用户会中问卷无补充后，异步进入 node_review 门控。"""
    key = f"{room_id.strip() or scope_id.strip()}::node_review"
    sid = scope_id.strip()
    rid = room_id.strip()

    async def _runner() -> None:
        try:
            from synapse.rd_meeting.solution_review import uses_solution_review_gate

            orch = MeetingRoomOrchestrator()
            rs = load_room_state(sid) or {}
            pending = rs.get("pending_delivery") if isinstance(rs.get("pending_delivery"), dict) else {}
            node_id = str(pending.get("node_id") or rs.get("current_node_id") or "")
            if not node_id:
                logger.warning("schedule_enter_node_review: missing node_id scope=%s", sid)
                return
            binding = resolve_node_binding(
                node_id,
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id=sid,
                ticket_title=ticket_title,
            )
            binding["node_id"] = node_id
            report_body = str(pending.get("report_body") or "").strip()
            tokens_used = int(pending.get("tokens_used") or 0)
            duration_seconds = int(pending.get("duration_seconds") or 0)
            stage_id = int(pending.get("stage_id") or stage_id_for_node_id(node_id))
            if uses_solution_review_gate(node_id):
                await orch.enter_solution_review_gate(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=rid,
                    node_id=node_id,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration_seconds,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                )
            else:
                await orch.enter_node_review_gate(
                    scope_type=scope_type,
                    scope_id=sid,
                    room_id=rid,
                    node_id=node_id,
                    binding=binding,
                    report_body=report_body,
                    tokens_used=tokens_used,
                    duration_seconds=duration_seconds,
                    stage_id=stage_id,
                    ticket_title=ticket_title,
                    agent_pool=agent_pool,
                )
        except Exception as exc:
            logger.exception("schedule_enter_node_review failed scope=%s: %s", sid, exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("schedule_enter_node_review: no event loop scope=%s", sid)
        return key
    loop.create_task(_runner())
    return key


def is_room_run_in_progress(room_id: str) -> bool:
    t = _running_tasks.get(room_id.strip())
    return t is not None and not t.done()


def cancel_room_run(room_id: str) -> bool:
    """取消进行中的节点执行任务（重新处理前调用）。"""
    key = room_id.strip()
    t = _running_tasks.get(key)
    if t is None or t.done():
        return False
    t.cancel()
    _running_tasks.pop(key, None)
    return True
