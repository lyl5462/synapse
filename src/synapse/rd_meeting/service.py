"""研发会议室 Phase 0：扫描 work/<scope_id>/ 与 dev.status。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from synapse.rd_meeting.dev_status import (
    ensure_room_id,
    load_dev_status,
    load_or_create_dev_status,
    read_dev_status_file,
    save_dev_status,
    should_list_in_meeting_rooms,
)
from synapse.rd_meeting.paths import iter_work_order_directories, scope_dir
from synapse.rd_meeting.userwork_sync import build_title_index, patch_userwork_summary
from synapse.rd_sop.nodes import (
    node_display_name,
    resolve_sop_raw_to_node_id,
    stage_id_for_node_id,
    stage_name_for_id,
)

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]


class MeetingRoomService:
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
        rid = (room_id or "").strip()
        if not rid:
            return None
        for order_dir in iter_work_order_directories():
            data = read_dev_status_file(order_dir / "dev.status")
            if not data:
                continue
            data = ensure_room_id(data)
            mr = data.get("meeting_room")
            if isinstance(mr, dict) and str(mr.get("room_id") or "").strip() == rid:
                return self._to_list_item(data, order_dir.name, build_title_index())
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

        return merged

    def open_meeting(
        self,
        scope_type: ScopeType,
        scope_id: str,
        *,
        sync_userwork: bool = True,
    ) -> dict[str, Any]:
        sid = (scope_id or "").strip()
        if not sid:
            raise ValueError("scope_id required")

        titles = build_title_index()
        local = "处理中"
        sop_display = ""
        node_id = "pending"
        stage_id = 0

        snap = self._userwork_row_for_scope(scope_type, sid)
        if snap:
            sop_raw = str(snap.get("sop_node") or "").strip()
            sop_display = sop_raw
            resolved = resolve_sop_raw_to_node_id(sop_raw)
            if resolved:
                node_id = resolved
                stage_id = stage_id_for_node_id(node_id)
            local = str(snap.get("local_process_state") or local).strip() or local

        data = load_or_create_dev_status(
            sid,
            scope_type=scope_type,
            local_process_state=local,
            stage_id=stage_id,
            current_node_id=node_id,
            sop_node_display=sop_display or node_display_name(node_id),
            pipeline_enabled=local in {"处理中"},
        )
        data["local_process_state"] = local
        data["pipeline_enabled"] = local in {"处理中"}
        mr = data.get("meeting_room")
        if not isinstance(mr, dict):
            mr = {}
        data["meeting_room"] = {**mr, "active": True}
        data = ensure_room_id(data)
        save_dev_status(sid, data)
        scope_dir(sid).mkdir(parents=True, exist_ok=True)

        if sync_userwork:
            self._sync_userwork_from_dev_status(scope_type, sid, data)

        return self._to_list_item(data, sid, titles)

    def meeting_summary(self, scope_type: ScopeType, scope_id: str) -> dict[str, Any]:
        """工单侧只读聚合（Phase 0：dev.status + 占位节点列表）。"""
        sid = (scope_id or "").strip()
        data = load_dev_status(sid)
        return {
            "scope_type": scope_type,
            "scope_id": sid,
            "dev_status": data,
            "nodes": [],
            "note": "Phase 0: room_history/archive 未接入，节点 metrics 为空",
        }

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
        ui_status = "processing"
        if local not in ("处理中",):
            ui_status = "completed" if local == "已完成" else "human_intervention"

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
        }
