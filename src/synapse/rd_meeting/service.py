"""研发会议室：work/<scope_id>/ 流水线与会议运行时（Phase 0/1）。"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from synapse.rd_meeting.binding import list_resolved_bindings, resolve_node_binding
from synapse.rd_meeting.participants import build_meeting_participants
from synapse.rd_meeting.config_store import (
    DEFAULT_MEETING_SKILL_ID,
    load_meeting_room_config,
    save_meeting_room_config,
)
from synapse.rd_meeting.dev_status import (
    ensure_room_id,
    load_dev_status,
    load_or_create_dev_status,
    read_dev_status_file,
    save_dev_status,
    should_list_in_meeting_rooms,
)
from synapse.rd_meeting.live import collect_live_sub_agents
from synapse.rd_meeting.orchestrator import (
    MeetingRoomOrchestrator,
    is_room_run_in_progress,
    schedule_run_node,
)
from synapse.rd_meeting.paths import iter_work_order_directories, scope_dir
from synapse.rd_meeting.phase import get_phase
from synapse.rd_meeting.pipeline import MeetingPipeline
from synapse.rd_meeting.room_runtime import (
    append_history_event,
    build_meeting_summary_nodes,
    history_to_chat_logs,
    list_archive_index,
    load_room_state,
    read_history,
    save_room_state,
    sync_room_state_from_dev,
)
from synapse.rd_meeting.room_skill import meeting_skill_preview
from synapse.rd_meeting.user_context import (
    append_user_context_pending,
    is_hitl_form_submission,
)
from synapse.rd_meeting.userwork_sync import build_title_index, patch_userwork_summary
from synapse.rd_sop.manifest import list_manifest_stages
from synapse.rd_sop.nodes import (
    node_display_name,
    resolve_sop_raw_to_node_id,
    stage_id_for_node_id,
    stage_name_for_id,
)

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]


class MeetingRoomService:
    def get_meeting_room_config(self) -> dict[str, Any]:
        cfg = load_meeting_room_config()
        skill_id = str(cfg.get("meeting_skill_id") or DEFAULT_MEETING_SKILL_ID)
        return {
            **cfg,
            "manifest_version": "1.0.0",
            "stages": list_manifest_stages(),
            "bindings": list_resolved_bindings(),
            "meeting_skill": meeting_skill_preview(skill_id),
        }

    def put_meeting_room_config(self, body: dict[str, Any]) -> dict[str, Any]:
        allowed: dict[str, Any] = {}
        if "version" in body:
            allowed["version"] = body["version"]
        for key in (
            "host_llm_endpoint_key",
            "worker_llm_endpoint_key",
            "meeting_skill_id",
        ):
            if key in body:
                value = body.get(key)
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise ValueError(f"{key} must be string")
                value = value.strip()
                if not value:
                    continue
                allowed[key] = value
        if "node_overrides" in body:
            overrides = body["node_overrides"]
            if not isinstance(overrides, dict):
                raise ValueError("node_overrides must be object")
            cleaned: dict[str, Any] = {}
            for node_id, ov in overrides.items():
                if not isinstance(ov, dict):
                    continue
                entry: dict[str, Any] = {}
                for key in (
                    "enabled",
                    "human_confirm",
                    "prompt_supplement",
                    "host_profile_id",
                    "worker_profile_ids",
                    "llm_endpoint_key",
                    "node_intent",
                    "hitl_form_schema",
                ):
                    if key in ov:
                        entry[key] = ov[key]
                if entry:
                    cleaned[str(node_id)] = entry
            allowed["node_overrides"] = cleaned
        if allowed:
            save_meeting_room_config(allowed)
        return self.get_meeting_room_config()

    def resolve_binding(self, node_id: str) -> dict[str, Any]:
        return resolve_node_binding(node_id)

    def start_run_current_node(
        self,
        room_id: str,
        *,
        agent_pool: Any | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        ctx = self._room_context(room_id)
        if ctx is None:
            raise ValueError("meeting_room_not_found")
        if is_room_run_in_progress(room_id):
            return {**ctx, "run_status": "already_running"}

        schedule_run_node(
            scope_type=ctx["scope_type"],
            scope_id=ctx["scope_id"],
            room_id=room_id,
            ticket_title=str(ctx.get("ticket_title") or ""),
            agent_pool=agent_pool,
            dry_run=dry_run,
        )
        return {**ctx, "run_status": "started"}

    async def run_current_node_sync(
        self,
        room_id: str,
        *,
        agent_pool: Any | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        ctx = self._room_context(room_id)
        if ctx is None:
            raise ValueError("meeting_room_not_found")
        orch = MeetingRoomOrchestrator()
        result = await orch.run_current_node(
            scope_type=ctx["scope_type"],
            scope_id=ctx["scope_id"],
            room_id=room_id,
            ticket_title=str(ctx.get("ticket_title") or ""),
            agent_pool=agent_pool,
            dry_run=dry_run,
        )
        detail = self.get_room_detail(room_id)
        return {"result": result, "room": detail}

    def _room_context(self, room_id: str) -> dict[str, Any] | None:
        detail = self.get_room_detail(room_id)
        if detail is None:
            return None
        return {
            "room_id": room_id,
            "scope_type": detail.get("scope_type"),
            "scope_id": detail.get("scope_id"),
            "ticket_title": detail.get("ticket_title"),
        }

    def list_meeting_rooms(self) -> list[dict[str, Any]]:
        titles = build_title_index()
        items: list[dict[str, Any]] = []
        for order_dir in iter_work_order_directories():
            scope_id = order_dir.name
            data = read_dev_status_file(order_dir / "dev.status")
            if data is None or not should_list_in_meeting_rooms(data):
                continue
            items.append(self._to_list_item(data, scope_id, titles))
        items.sort(key=lambda x: (x.get("updated_at") or ""), reverse=True)
        return items

    def get_by_room_id(self, room_id: str) -> dict[str, Any] | None:
        return self.get_room_detail(room_id)

    def get_room_live(
        self,
        room_id: str,
        *,
        agent_pool: Any | None = None,
        history_limit: int = 40,
    ) -> dict[str, Any] | None:
        """轻量 live 快照：phase、委派进度、子 Agent 状态、近期 history（供 UI 轮询）。"""
        detail = self.get_room_detail(room_id)
        if detail is None:
            return None
        scope_id = str(detail.get("scope_id") or "")
        room_state = detail.get("room_state") if isinstance(detail.get("room_state"), dict) else {}
        history = read_history(scope_id, limit=history_limit) if scope_id else []

        orchestrator = None
        try:
            from synapse.main import _orchestrator

            orchestrator = _orchestrator
        except (ImportError, AttributeError):
            pass
        if orchestrator is None and agent_pool is not None:
            orchestrator = getattr(agent_pool, "orchestrator", None)

        host_session_id = f"rd_meeting:{room_id.strip()}:host"
        sub_agents: list[dict[str, Any]] = []
        if orchestrator is not None:
            getter = getattr(orchestrator, "get_sub_agent_states", None)
            if callable(getter):
                sub_agents = list(getter(host_session_id) or [])
            if not sub_agents:
                sub_agents = collect_live_sub_agents(orchestrator, host_session_id)

        agents_active = (
            room_state.get("agents_active")
            if isinstance(room_state.get("agents_active"), list)
            else []
        )
        scope_type = str(detail.get("scope_type") or "demand")
        node_id = str(detail.get("current_node_id") or "pending")
        binding = resolve_node_binding(
            node_id,
            scope_type=scope_type,
            scope_id=scope_id,
            ticket_title=str(detail.get("ticket_title") or ""),
        )
        binding["node_id"] = node_id
        participants = (
            room_state.get("participants")
            if isinstance(room_state.get("participants"), list)
            else build_meeting_participants(binding)
        )

        return {
            "room_id": room_id,
            "scope_id": scope_id,
            "scope_type": detail.get("scope_type"),
            "status": detail.get("status") or room_state.get("status"),
            "phase": get_phase(scope_id) if scope_id else "idle",
            "pipeline": (
                MeetingPipeline.load(scope_id).snapshot_for_api()
                if scope_id and MeetingPipeline.load(scope_id)
                else None
            ),
            "run_in_progress": is_room_run_in_progress(room_id),
            "current_node_id": detail.get("current_node_id"),
            "current_node_name": detail.get("current_node_name"),
            "tokenConsumed": detail.get("tokenConsumed"),
            "tokenBudget": detail.get("tokenBudget"),
            "stageDuration": detail.get("stageDuration"),
            "agents_active": agents_active,
            "participants": participants,
            "sub_agents": sub_agents,
            "recent_history": history,
            "recent_chat": history_to_chat_logs(history),
            "intervention_kind": room_state.get("intervention_kind"),
            "hitl_form_schema": room_state.get("hitl_form_schema"),
            "pending_delivery": room_state.get("pending_delivery"),
        }

    def get_room_detail(self, room_id: str) -> dict[str, Any] | None:
        rid = (room_id or "").strip()
        if not rid:
            return None
        for order_dir in iter_work_order_directories():
            scope_id = order_dir.name
            data = read_dev_status_file(order_dir / "dev.status")
            if not data:
                continue
            data = ensure_room_id(data)
            mr = data.get("meeting_room")
            if isinstance(mr, dict) and str(mr.get("room_id") or "").strip() == rid:
                return self._room_detail_payload(data, scope_id, build_title_index())
        return None

    def get_dev_status(self, scope_type: ScopeType, scope_id: str) -> dict[str, Any] | None:
        sid = (scope_id or "").strip()
        if not sid:
            return None
        data = load_dev_status(sid)
        if data is None:
            return None
        return ensure_room_id(data)

    def put_dev_status(
        self,
        scope_type: ScopeType,
        scope_id: str,
        body: dict[str, Any],
        *,
        sync_userwork: bool = True,
    ) -> dict[str, Any]:
        sid = (scope_id or "").strip()
        if not sid:
            raise ValueError("scope_id required")

        existing = load_dev_status(sid)
        if existing is None:
            merged = load_or_create_dev_status(sid, scope_type=scope_type)
        else:
            merged = dict(existing)

        scope = merged.get("scope")
        if not isinstance(scope, dict):
            merged["scope"] = {"type": scope_type, "id": sid}
        else:
            merged["scope"] = {"type": scope_type, "id": sid}

        for key in (
            "local_process_state",
            "stage_id",
            "current_node_id",
            "sop_node_display",
            "pipeline_enabled",
            "meeting_room",
        ):
            if key in body:
                merged[key] = body[key]

        merged = ensure_room_id(merged)
        save_dev_status(sid, merged)

        if sync_userwork:
            self._sync_userwork_from_dev_status(scope_type, sid, merged)

        room_id = str(merged.get("meeting_room", {}).get("room_id") or "")
        if room_id and isinstance(merged.get("meeting_room"), dict) and merged["meeting_room"].get("active"):
            sync_room_state_from_dev(
                sid,
                room_id=room_id,
                scope_type=scope_type,
                stage_id=int(merged.get("stage_id") or 0),
                current_node_id=str(merged.get("current_node_id") or "pending"),
                local_process_state=str(merged.get("local_process_state") or ""),
            )

        return merged

    def list_pending_human_intervention(self) -> list[dict[str, Any]]:
        """扫描 room_state.status=human_intervention 的会议室（Phase 3 通知看板）。"""
        pending: list[dict[str, Any]] = []
        titles = build_title_index()
        for order_dir in iter_work_order_directories():
            scope_id = order_dir.name
            rs = load_room_state(scope_id)
            if not rs or str(rs.get("status") or "") != "human_intervention":
                continue
            dev = read_dev_status_file(order_dir / "dev.status")
            if dev is None:
                continue
            item = self._to_list_item(dev, scope_id, titles)
            item["status"] = "human_intervention"
            pending.append(item)
        pending.sort(key=lambda x: (x.get("updated_at") or ""), reverse=True)
        return pending

    def open_meeting(
        self,
        scope_type: ScopeType,
        scope_id: str,
        *,
        sync_userwork: bool = True,
        promote_to_processing: bool = True,
        auto_run_first_node: bool = False,
    ) -> dict[str, Any]:
        sid = (scope_id or "").strip()
        if not sid:
            raise ValueError("scope_id required")

        from synapse.rd_meeting.pipeline import (
            STEP_OPEN_MEETING,
            PipelineRunContext,
            run_pipeline_until_waiting,
        )

        ctx = PipelineRunContext(
            scope_type=scope_type,
            scope_id=sid,
            sync_userwork=sync_userwork,
            promote_to_processing=promote_to_processing,
            auto_run_first_node=auto_run_first_node,
        )
        run_pipeline_until_waiting(ctx, initial_flow_step=STEP_OPEN_MEETING)
        if ctx.auto_run_started:
            ctx.detail["auto_run_started"] = True
        return ctx.detail

    def intervene(
        self,
        room_id: str,
        *,
        text: str,
        message_type: str = "instruction",
        resume_run: bool = False,
        agent_pool: Any | None = None,
    ) -> dict[str, Any]:
        rid = (room_id or "").strip()
        text = (text or "").strip()
        if not rid:
            raise ValueError("room_id required")
        if not text:
            raise ValueError("text required")

        detail = self.get_room_detail(rid)
        if detail is None:
            raise ValueError("meeting_room_not_found")

        scope_id = str(detail.get("scope_id") or "")
        scope_type = str(detail.get("scope_type") or "demand")
        ticket_title = str(detail.get("ticket_title") or "")

        room_state = load_room_state(scope_id)
        append_user_context_pending(scope_id, text)

        pending = (
            room_state.get("pending_delivery")
            if isinstance(room_state, dict)
            else None
        )
        is_result_confirm_gate = (
            isinstance(pending, dict)
            and pending.get("report_body")
            and pending.get("await_confirm", True)
            and message_type == "instruction"
            and is_hitl_form_submission(text)
        )
        if is_result_confirm_gate:
            approved, comment = self._parse_hitl_decision(text, resume_run=resume_run)
            orch = MeetingRoomOrchestrator()
            orch.confirm_node_delivery(
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id=scope_id,
                room_id=rid,
                approved=approved,
                comment=comment,
                ticket_title=ticket_title,
            )
            append_history_event(
                scope_id,
                {
                    "event": "human_intervene",
                    "room_id": rid,
                    "text": text,
                    "message_type": message_type,
                    "log_type": "user",
                    "agent_id": "user",
                    "id": uuid.uuid4().hex[:12],
                },
            )
            return self.get_room_detail(rid) or detail

        append_history_event(
            scope_id,
            {
                "event": "human_intervene",
                "room_id": rid,
                "text": text,
                "message_type": message_type,
                "log_type": "user",
                "agent_id": "user",
                "id": uuid.uuid4().hex[:12],
            },
        )

        effective_resume = resume_run
        if message_type == "instruction":
            rs = dict(room_state) if isinstance(room_state, dict) else {}
            if is_hitl_form_submission(text) or str(rs.get("status") or "") == "human_intervention":
                effective_resume = True
                rs["status"] = "processing"
                if not (
                    isinstance(pending, dict)
                    and pending.get("report_body")
                    and pending.get("await_confirm", True)
                ):
                    rs.pop("hitl_form_schema", None)
                save_room_state(scope_id, rs)
        elif message_type == "chat":
            effective_resume = False

        out = self.get_room_detail(rid) or detail
        if effective_resume and message_type == "instruction":
            schedule_run_node(
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id=scope_id,
                room_id=rid,
                ticket_title=ticket_title,
                agent_pool=agent_pool,
            )
            out["resume_run_started"] = True
        return out

    @staticmethod
    def _parse_hitl_decision(text: str, *, resume_run: bool = False) -> tuple[bool, str]:
        """解析人工确认表单或一键通过指令，返回 (是否通过, 补充说明)。"""
        lower = text.lower()
        comment = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("comment:") or stripped.startswith("补充说明:"):
                comment = stripped.split(":", 1)[-1].strip()

        if "decision: reject" in lower or "decision:reject" in lower:
            return False, comment or text
        if "decision: approve" in lower or "decision:approve" in lower:
            return True, comment
        if "不通过" in text or "需返工" in text or "reject" in lower:
            return False, comment or text
        if resume_run or "人工确认通过" in text or "approve" in lower:
            return True, comment
        return True, comment or text

    def meeting_summary(self, scope_type: ScopeType, scope_id: str) -> dict[str, Any]:
        """工单侧只读聚合：dev.status + room_state + archive + 节点 metrics。"""
        sid = (scope_id or "").strip()
        dev = load_dev_status(sid)
        room_state = load_room_state(sid)
        history = read_history(sid, limit=100)
        archive_index = list_archive_index(sid)
        nodes = build_meeting_summary_nodes(dev, room_state)

        metrics = room_state.get("metrics") if isinstance(room_state, dict) else {}
        if not isinstance(metrics, dict):
            metrics = {}

        return {
            "scope_type": scope_type,
            "scope_id": sid,
            "dev_status": dev,
            "room_state": room_state,
            "room_id": self._extract_room_id(dev, room_state),
            "summary_metrics": {
                "stage_seconds": int(metrics.get("stage_seconds") or 0),
                "tokens": int(metrics.get("tokens") or 0),
                "token_budget": int(metrics.get("token_budget") or 150_000),
                "human_interventions": sum(
                    1 for h in history if str(h.get("event") or "") == "human_intervene"
                ),
            },
            "nodes": nodes,
            "archive_index": archive_index,
            "recent_history": history[-20:],
            "recent_chat": history_to_chat_logs(history),
        }

    @staticmethod
    def _extract_room_id(
        dev: dict[str, Any] | None,
        room_state: dict[str, Any] | None,
    ) -> str:
        if isinstance(dev, dict):
            mr = dev.get("meeting_room")
            if isinstance(mr, dict):
                rid = str(mr.get("room_id") or "").strip()
                if rid:
                    return rid
        if isinstance(room_state, dict):
            return str(room_state.get("room_id") or "").strip()
        return ""

    def _room_detail_payload(
        self,
        data: dict[str, Any],
        scope_id: str,
        titles: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        item = self._to_list_item(data, scope_id, titles)
        room_state = load_room_state(scope_id)
        history = read_history(scope_id, limit=500)
        archive_index = list_archive_index(scope_id)

        if room_state and isinstance(room_state.get("metrics"), dict):
            m = room_state["metrics"]
            item["stageDuration"] = self._format_duration(int(m.get("stage_seconds") or 0))
            item["tokenConsumed"] = int(m.get("tokens") or 0)
            item["tokenBudget"] = int(m.get("token_budget") or 150_000)
            rs = str(room_state.get("status") or "")
            if rs in ("processing", "human_intervention", "completed"):
                item["status"] = rs

        scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
        scope_type = str(scope.get("type") or "demand")
        node_id = str(data.get("current_node_id") or "pending")
        ticket_title = str(item.get("ticket_title") or "")
        binding = resolve_node_binding(
            node_id,
            scope_type=scope_type,
            scope_id=scope_id,
            ticket_title=ticket_title,
        )
        binding["node_id"] = node_id
        participants = build_meeting_participants(binding)
        if isinstance(room_state, dict) and isinstance(room_state.get("participants"), list):
            participants = room_state["participants"]

        item["room_state"] = room_state
        item["history"] = history
        item["archive_index"] = archive_index
        item["chat_logs"] = history_to_chat_logs(history)
        item["current_node_binding"] = binding
        item["participants"] = participants
        pipe = MeetingPipeline.load(scope_id)
        if pipe is not None:
            item["pipeline"] = pipe.snapshot_for_api()
        return item

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

    def _userwork_row_for_scope(self, scope_type: ScopeType, scope_id: str) -> dict[str, Any] | None:
        from synapse.api.routes.dev_iwhalecloud import _snapshot_norm_id
        from synapse.rd_meeting.userwork_sync import _load_userwork_list

        sid = _snapshot_norm_id(scope_id)
        for demand in _load_userwork_list():
            if scope_type == "demand":
                if _snapshot_norm_id(demand.get("demand_no")) == sid:
                    return demand
                continue
            owned = demand.get("owned_work_items")
            if not isinstance(owned, list):
                continue
            for task in owned:
                if isinstance(task, dict) and _snapshot_norm_id(task.get("task_no")) == sid:
                    return task
        return None

    def _sync_userwork_from_dev_status(
        self, scope_type: ScopeType, scope_id: str, data: dict[str, Any]
    ) -> None:
        node_id = str(data.get("current_node_id") or "")
        display = str(data.get("sop_node_display") or "").strip() or node_display_name(node_id)
        local = str(data.get("local_process_state") or "").strip()
        patch_userwork_summary(
            scope_type=scope_type,
            scope_id=scope_id,
            sop_node=display,
            local_process_state=local or None,
        )

    def _to_list_item(
        self,
        data: dict[str, Any],
        scope_id: str,
        titles: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        data = ensure_room_id(data)
        scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
        scope_type = str(scope.get("type") or titles.get(scope_id, {}).get("scope_type") or "demand")
        stage_id = int(data.get("stage_id") or 0)
        node_id = str(data.get("current_node_id") or "pending")
        mr = data.get("meeting_room") if isinstance(data.get("meeting_room"), dict) else {}
        meta = titles.get(scope_id, {})
        local = str(data.get("local_process_state") or "")

        room_state = load_room_state(scope_id)
        ui_status: str = "processing"
        if room_state and str(room_state.get("status") or "") in (
            "processing",
            "human_intervention",
            "completed",
            "failed",
        ):
            ui_status = str(room_state["status"])
        elif local not in ("处理中",):
            ui_status = "completed" if local == "已完成" else "human_intervention"

        token_consumed = 0
        token_budget = 150_000
        stage_duration = "—"
        if room_state and isinstance(room_state.get("metrics"), dict):
            m = room_state["metrics"]
            token_consumed = int(m.get("tokens") or 0)
            token_budget = int(m.get("token_budget") or 150_000)
            stage_duration = self._format_duration(int(m.get("stage_seconds") or 0))

        return {
            "room_id": str(mr.get("room_id") or ""),
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ticket_id": scope_id,
            "ticket_title": meta.get("title") or scope_id,
            "branch": meta.get("branch") or "",
            "stage_id": stage_id,
            "stage_name": stage_name_for_id(stage_id),
            "current_node_id": node_id,
            "current_node_name": node_display_name(node_id),
            "local_process_state": local,
            "status": ui_status,
            "pipeline_enabled": bool(data.get("pipeline_enabled")),
            "meeting_room_active": bool(mr.get("active")),
            "updated_at": data.get("updated_at"),
            "dev_status": data,
            "tokenConsumed": token_consumed,
            "tokenBudget": token_budget,
            "stageDuration": stage_duration,
        }
