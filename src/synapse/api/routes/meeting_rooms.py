"""研发会议室 API（Phase 0）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from synapse.api.schemas import error_response, success_response
from synapse.rd_meeting.service import MeetingRoomService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["研发会议室"])
_service = MeetingRoomService()


class OpenMeetingBody(BaseModel):
    scope_type: Literal["demand", "task"] = Field(..., description="demand 或 task")
    scope_id: str = Field(..., description="需求单号或研发单号")
    sync_userwork: bool = Field(True, description="是否回写 userwork 摘要")


class PutDevStatusBody(BaseModel):
    local_process_state: str | None = None
    stage_id: int | None = None
    current_node_id: str | None = None
    sop_node_display: str | None = None
    pipeline_enabled: bool | None = None
    meeting_room: dict[str, Any] | None = None
    sync_userwork: bool = Field(True, description="是否回写 userwork 摘要")


@router.get("/api/dev/meeting-rooms")
async def list_meeting_rooms() -> dict:
    """扫描 work/<scope_id>/ 子目录，读取各目录 dev.status 生成会议室列表。"""
    try:
        items = _service.list_meeting_rooms()
        return success_response({"list": items, "count": len(items)})
    except Exception as exc:
        logger.exception("list_meeting_rooms failed: %s", exc)
        return error_response(500, "list_meeting_rooms_failed", str(exc))


@router.get("/api/dev/meeting-rooms/{room_id}")
async def get_meeting_room(room_id: str) -> dict:
    item = _service.get_by_room_id(room_id)
    if item is None:
        return error_response(404, "meeting_room_not_found")
    return success_response(item)


@router.post("/api/dev/meeting-rooms/open")
async def open_meeting(body: OpenMeetingBody) -> dict:
    try:
        item = _service.open_meeting(
            body.scope_type,
            body.scope_id,
            sync_userwork=body.sync_userwork,
        )
        return success_response(item)
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        logger.exception("open_meeting failed: %s", exc)
        return error_response(500, "open_meeting_failed", str(exc))


@router.get("/api/dev/work/{scope_type}/{scope_id}/dev.status")
async def get_dev_status(scope_type: Literal["demand", "task"], scope_id: str) -> dict:
    data = _service.get_dev_status(scope_type, scope_id)
    if data is None:
        return error_response(404, "dev_status_not_found")
    return success_response(data)


@router.put("/api/dev/work/{scope_type}/{scope_id}/dev.status")
async def put_dev_status(
    scope_type: Literal["demand", "task"],
    scope_id: str,
    body: PutDevStatusBody,
) -> dict:
    try:
        payload = body.model_dump(exclude={"sync_userwork"}, exclude_none=True)
        sync = body.sync_userwork
        data = _service.put_dev_status(
            scope_type,
            scope_id,
            payload,
            sync_userwork=sync,
        )
        return success_response(data)
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        logger.exception("put_dev_status failed: %s", exc)
        return error_response(500, "put_dev_status_failed", str(exc))


@router.get("/api/dev/work-orders/{scope_type}/{scope_id}/meeting-summary")
async def meeting_summary(scope_type: Literal["demand", "task"], scope_id: str) -> dict:
    """工单侧只读：Phase 0 返回 dev.status，节点 metrics 后续 Phase 1 接入。"""
    return success_response(_service.meeting_summary(scope_type, scope_id))
