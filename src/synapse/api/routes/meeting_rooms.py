"""研发会议室 API（Phase 0/1）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
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
    promote_to_processing: bool = Field(
        True, description="待处理工单开会时推进为处理中并定位首节点"
    )
    auto_run_first_node: bool = Field(False, description="开会后是否后台执行当前节点（默认仅开启+初始化）")


class InterveneBody(BaseModel):
    text: str = Field(..., description="人工指令或聊天内容")
    message_type: str = Field("instruction", description="instruction 或 chat")
    resume_run: bool = Field(False, description="干预后继续执行当前节点")


class PutMeetingRoomConfigBody(BaseModel):
    version: str | None = None
    host_llm_endpoint_key: str | None = Field(
        None, description="小鲸（Host）专属 LLM 端点 key（会议室级）"
    )
    worker_llm_endpoint_key: str | None = Field(
        None, description="协作智能体（Worker）统一 LLM 端点 key（会议室级）"
    )
    meeting_skill_id: str | None = Field(
        None, description="会议室专属 SKILL ID（host / worker 均加载）"
    )
    node_overrides: dict[str, Any] | None = None


class RunNodeBody(BaseModel):
    dry_run: bool | None = Field(None, description="强制 dry-run，不调用 LLM")
    sync: bool = Field(False, description="为 true 时同步执行并等待结束")


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


@router.get("/api/dev/meeting-rooms/pending/human-intervention")
async def list_pending_human_intervention() -> dict:
    """待人工介入的会议室列表（room_state + dev.status）。"""
    items = _service.list_pending_human_intervention()
    return success_response({"list": items, "count": len(items)})


@router.get("/api/dev/meeting-rooms/{room_id}")
async def get_meeting_room(room_id: str) -> dict:
    """返回列表项字段 + room_state + history + archive_index。"""
    item = _service.get_room_detail(room_id)
    if item is None:
        return error_response(404, "meeting_room_not_found")
    return success_response(item)


@router.get("/api/dev/meeting-rooms/{room_id}/live")
async def get_meeting_room_live(room_id: str, request: Request) -> dict:
    """会议室 live 快照：委派进度、子 Agent、phase、近期聊天事件（轮询）。"""
    pool = getattr(request.app.state, "agent_pool", None)
    item = _service.get_room_live(room_id, agent_pool=pool)
    if item is None:
        return error_response(404, "meeting_room_not_found")
    return success_response(item)


@router.post("/api/dev/meeting-rooms/{room_id}/intervene")
async def intervene_meeting(room_id: str, body: InterveneBody, request: Request) -> dict:
    pool = getattr(request.app.state, "agent_pool", None)
    try:
        item = _service.intervene(
            room_id,
            text=body.text,
            message_type=body.message_type,
            resume_run=body.resume_run,
            agent_pool=pool,
        )
        return success_response(item)
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not_found" in msg else 400
        return error_response(code, msg)
    except Exception as exc:
        logger.exception("intervene_meeting failed: %s", exc)
        return error_response(500, "intervene_meeting_failed", str(exc))


@router.post("/api/dev/meeting-rooms/open")
async def open_meeting(body: OpenMeetingBody) -> dict:
    try:
        item = _service.open_meeting(
            body.scope_type,
            body.scope_id,
            sync_userwork=body.sync_userwork,
            promote_to_processing=body.promote_to_processing,
            auto_run_first_node=body.auto_run_first_node,
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
    """工单侧只读：dev.status + room_state + 节点 metrics + archive 索引。"""
    return success_response(_service.meeting_summary(scope_type, scope_id))


@router.get("/api/dev/meeting-room-config")
async def get_meeting_room_config() -> dict:
    try:
        return success_response(_service.get_meeting_room_config())
    except Exception as exc:
        logger.exception("get_meeting_room_config failed: %s", exc)
        return error_response(500, "get_meeting_room_config_failed", str(exc))


@router.put("/api/dev/meeting-room-config")
async def put_meeting_room_config(body: PutMeetingRoomConfigBody) -> dict:
    try:
        payload = body.model_dump(exclude_none=True)
        data = _service.put_meeting_room_config(payload)
        return success_response(data)
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        logger.exception("put_meeting_room_config failed: %s", exc)
        return error_response(500, "put_meeting_room_config_failed", str(exc))


@router.get("/api/dev/meeting-room-config/bindings/{node_id}")
async def get_node_binding(node_id: str) -> dict:
    return success_response(_service.resolve_binding(node_id))


@router.post("/api/dev/meeting-rooms/{room_id}/run-node")
async def run_meeting_node(room_id: str, body: RunNodeBody, request: Request) -> dict:
    """执行当前 SOP 节点（默认后台；body.sync=true 时同步等待）。"""
    pool = getattr(request.app.state, "agent_pool", None)
    try:
        if body.sync:
            data = await _service.run_current_node_sync(
                room_id,
                agent_pool=pool,
                dry_run=body.dry_run,
            )
            return success_response(data)
        data = _service.start_run_current_node(
            room_id,
            agent_pool=pool,
            dry_run=body.dry_run,
        )
        return success_response(data)
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not_found" in msg else 400
        return error_response(code, msg)
    except Exception as exc:
        logger.exception("run_meeting_node failed: %s", exc)
        return error_response(500, "run_meeting_node_failed", str(exc))
