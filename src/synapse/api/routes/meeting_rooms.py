"""研发会议室 API（Phase 0/1）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from synapse.api.schemas import error_response, success_response
from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.live import scope_id_for_room_id
from synapse.rd_meeting.node_review import (
    build_node_review_payload,
    load_node_review,
    read_artifact_file,
    save_node_review,
)
from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator
from synapse.rd_meeting.participants import build_meeting_participants
from synapse.rd_meeting.paths import agent_node_dir, agent_sop_profile_dir
from synapse.rd_meeting.room_runtime import load_room_state
from synapse.rd_meeting.service import MeetingRoomService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["研发会议室"])
_service = MeetingRoomService()


class OpenMeetingBody(BaseModel):
    scope_type: Literal["demand", "task"] = Field(..., description="demand 或 task")
    scope_id: str = Field(..., description="需求单号或研发单号")
    prod: str = Field(..., min_length=1, description="统一服务产品标识（get_prod_info.prod）")
    sync_userwork: bool = Field(True, description="是否回写 userwork 摘要")
    promote_to_processing: bool = Field(
        True, description="待处理工单开会时推进为处理中并定位首节点"
    )
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
    node_overrides: dict[str, Any] | None = None


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


@router.get("/api/dev/meeting-rooms/{room_id}/agent-contexts")
async def get_meeting_agent_contexts(
    room_id: str,
    request: Request,
    dump: bool = False,
    message_char_limit: int = 12_000,
    node_id: str = "",
) -> dict:
    """临时探测各参会 Agent 的 system prompt / messages（调试用；dump=true 写入工单 debug 目录）。"""
    pool = getattr(request.app.state, "agent_pool", None)
    try:
        item = _service.get_agent_contexts(
            room_id,
            agent_pool=pool,
            dump=dump,
            message_char_limit=message_char_limit,
            node_id=(node_id or "").strip() or None,
        )
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        logger.exception("get_meeting_agent_contexts failed: %s", exc)
        return error_response(500, "get_meeting_agent_contexts_failed", str(exc))
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


@router.post("/api/dev/meeting-rooms/{room_id}/reprocess")
async def reprocess_meeting_room(room_id: str, request: Request) -> dict:
    """重新处理当前 SOP 节点：清理过程数据并从 node_init 重跑。"""
    pool = getattr(request.app.state, "agent_pool", None)
    try:
        item = _service.reprocess_current_node(room_id, agent_pool=pool)
        return success_response(item)
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not_found" in msg else 400
        return error_response(code, msg)
    except Exception as exc:
        logger.exception("reprocess_meeting_room failed: %s", exc)
        return error_response(500, "reprocess_meeting_room_failed", str(exc))


@router.post("/api/dev/meeting-rooms/open")
async def open_meeting(body: OpenMeetingBody, request: Request) -> dict:
    pool = getattr(request.app.state, "agent_pool", None)
    try:
        item = _service.open_meeting(
            body.scope_type,
            body.scope_id,
            prod=body.prod.strip(),
            sync_userwork=body.sync_userwork,
            promote_to_processing=body.promote_to_processing,
            agent_pool=pool,
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


# ─── PR3：NodeReviewPanel 配套路由 ───────────────────────────────────


class ReviewDecisionBody(BaseModel):
    mode: Literal["approve", "reject", "escalate"] = Field(
        ..., description="人工裁决：通过 / 打回返工 / 异常介入"
    )
    comment: str = Field("", description="人工备注（打回原因、异常说明等）")


def _resolve_scope_for_room(room_id: str) -> tuple[str, str] | None:
    """room_id → (scope_id, scope_type)；找不到返回 ``None``。"""
    sid = scope_id_for_room_id(room_id)
    if not sid:
        return None
    dev = load_dev_status(sid) or {}
    scope_type = str(dev.get("scope_type") or "demand").strip() or "demand"
    if scope_type not in ("demand", "task"):
        scope_type = "demand"
    return sid, scope_type


@router.get("/api/dev/meeting-rooms/{room_id}/nodes/{node_id}/participants")
async def get_node_participants(room_id: str, node_id: str) -> dict:
    """按 SOP 节点 binding 返回参会智能体阵容（切换议题时前端刷新头像栏）。"""
    resolved = _resolve_scope_for_room(room_id)
    if resolved is None:
        return error_response(404, "meeting_room_not_found")
    sid, scope_type = resolved
    nid = (node_id or "").strip()
    if not nid:
        return error_response(400, "node_id_required")
    from synapse.rd_meeting.binding import resolve_node_binding

    binding = resolve_node_binding(nid, scope_type=scope_type, scope_id=sid)  # type: ignore[arg-type]
    binding["node_id"] = nid
    participants = build_meeting_participants(binding)
    return success_response(
        {
            "room_id": room_id,
            "scope_id": sid,
            "node_id": nid,
            "participants": participants,
        }
    )


@router.get("/api/dev/meeting-rooms/{room_id}/node-review")
async def get_node_review(
    room_id: str,
    request: Request,
    node_id: str | None = None,
    refresh: bool = False,
) -> dict:
    """读取节点确认总结 payload（PR2 NODE_REVIEW 步骤的结果）。

    - 默认从 ``meeting_pipeline.json.context.node_review[node_id]`` 拿；
    - ``refresh=true`` 时基于当前 pending_delivery + agent_pool 重新装配（不走 LLM 摘要，
      仅刷新 metrics / artifacts，便于前端在审阅期间手动刷新统计数据）。
    """
    resolved = _resolve_scope_for_room(room_id)
    if resolved is None:
        return error_response(404, "meeting_room_not_found")
    sid, scope_type = resolved

    room_state = load_room_state(sid) or {}
    pending = room_state.get("pending_delivery") if isinstance(room_state.get("pending_delivery"), dict) else {}
    current_node = str(room_state.get("current_node_id") or "").strip()
    dev = load_dev_status(sid) or {}
    if not current_node:
        current_node = str(dev.get("current_node_id") or "").strip()
    target_node = (node_id or "").strip() or str(pending.get("node_id") or current_node or "")
    if not target_node:
        return error_response(400, "node_id_required")

    pending_node = str(pending.get("node_id") or "").strip()
    pending_matches = pending_node == target_node or (not pending_node and target_node == current_node)
    is_historical = bool(current_node) and target_node != current_node

    cached = load_node_review(sid, target_node)

    def _summaries_all_fallback(payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        rows = payload.get("summaries")
        if not isinstance(rows, list) or not rows:
            return False
        return all(
            isinstance(s, dict) and str(s.get("source") or "fallback") == "fallback"
            for s in rows
        )

    if not refresh:
        if cached is not None and not _summaries_all_fallback(cached):
            return success_response(cached)
        # 回退：仅 pending 对应该节点时才用 review_payload，避免历史节点串数据
        inline = pending.get("review_payload") if isinstance(pending, dict) else None
        if isinstance(inline, dict) and pending_matches and not _summaries_all_fallback(inline):
            return success_response(inline)

    # refresh=true：仅刷新 metrics/artifacts，保留已有 LLM 摘要
    # 缓存缺失（历史节点回看）：尝试 LLM 重新生成摘要（activity 可能仍在 agents/<node>/）
    use_llm_summary = not refresh

    try:
        from synapse.rd_meeting.agent_session import resolve_meeting_orchestrator
        from synapse.rd_meeting.binding import resolve_node_binding
        from synapse.rd_sop.nodes import stage_id_for_node_id

        binding = resolve_node_binding(target_node, scope_type=scope_type, scope_id=sid)  # type: ignore[arg-type]
        binding["node_id"] = target_node
        pool = getattr(request.app.state, "agent_pool", None)

        report_body = ""
        tokens_used = 0
        duration_seconds = 0
        stage_id_val = stage_id_for_node_id(target_node)
        if isinstance(pending, dict) and pending_matches:
            report_body = str(pending.get("report_body") or "")
            tokens_used = int(pending.get("tokens_used") or 0)
            duration_seconds = int(pending.get("duration_seconds") or 0)
            stage_id_val = int(pending.get("stage_id") or stage_id_val)
        elif cached is not None:
            report_body = str(cached.get("report_body") or "")
            metrics = cached.get("metrics") if isinstance(cached.get("metrics"), dict) else {}
            tokens_used = int(metrics.get("node_token_total") or 0)
            duration_seconds = int(metrics.get("node_duration_seconds") or 0)
            stage_id_val = int(cached.get("stage_id") or stage_id_val)

        payload = await build_node_review_payload(
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_id=sid,
            room_id=room_id,
            node_id=target_node,
            binding=binding,
            report_body=report_body,
            tokens_used=tokens_used,
            duration_seconds=duration_seconds,
            stage_id=stage_id_val,
            agent_pool=pool,
            orchestrator=resolve_meeting_orchestrator(pool),
            use_llm_summary=use_llm_summary,
        )

        if refresh and cached is not None:
            old_summaries = cached.get("summaries")
            if isinstance(old_summaries, list) and old_summaries:
                payload["summaries"] = old_summaries

        save_node_review(
            sid,
            target_node,
            payload,
            sync_pending=pending_matches and target_node == current_node and not is_historical,
        )
        return success_response(payload)
    except Exception as exc:
        logger.exception("refresh node_review failed: %s", exc)
        return error_response(500, "node_review_refresh_failed", str(exc))


@router.get("/api/dev/meeting-rooms/{room_id}/agent-trace")
async def get_agent_trace(
    room_id: str,
    profile_id: str,
    node_id: str,
    tail_messages: int = 200,
) -> dict:
    """读取智能体节点级 trace（PR1 落盘的 conversation/tools/skills/usage/events）。

    返回结构：
    ``{ meta, conversation: [...], tools: {...}, skills: {...}, usage: {...}, events: [...] }``
    """
    resolved = _resolve_scope_for_room(room_id)
    if resolved is None:
        return error_response(404, "meeting_room_not_found")
    sid, _ = resolved

    pid = (profile_id or "").strip()
    nid = (node_id or "").strip()
    if not pid or not nid:
        return error_response(400, "profile_id_and_node_id_required")

    import json as _json

    base = agent_node_dir(sid, pid, nid)
    meta_path = agent_sop_profile_dir(sid, nid, pid) / "meta.json"

    def _read_json(path) -> Any:
        if not path.is_file():
            return None
        try:
            return _json.loads(path.read_text("utf-8"))
        except (OSError, _json.JSONDecodeError):
            return None

    def _read_jsonl(path, *, limit: int = 0) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        try:
            lines = path.read_text("utf-8").splitlines()
        except OSError:
            return []
        if limit and len(lines) > limit:
            lines = lines[-limit:]
        out: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    payload = {
        "scope_id": sid,
        "room_id": room_id,
        "profile_id": pid,
        "node_id": nid,
        "meta": _read_json(meta_path),
        "conversation": _read_jsonl(base / "conversation.jsonl", limit=max(0, int(tail_messages or 0))),
        "tools": _read_json(base / "tools.json"),
        "skills": _read_json(base / "skills.json"),
        "usage": _read_json(base / "usage.json"),
        "events": _read_jsonl(base / "events.jsonl"),
    }
    return success_response(payload)


@router.get("/api/dev/meeting-rooms/{room_id}/artifact-file")
async def get_artifact_file(room_id: str, path: str) -> dict:
    """读取归档文件原文（前端 .md 内联展开用）。

    ``path`` 必须是 scope_dir 下的相对路径（如
    ``archive/2/req_clarify/需求澄清.md``），含 ``..`` 越权访问会被拒绝。
    """
    resolved = _resolve_scope_for_room(room_id)
    if resolved is None:
        return error_response(404, "meeting_room_not_found")
    sid, _ = resolved
    res = read_artifact_file(sid, path)
    if res is None:
        return error_response(404, "artifact_not_found_or_forbidden")
    content, ext = res
    return success_response({"path": path, "ext": ext, "content": content, "size": len(content)})


@router.post("/api/dev/meeting-rooms/{room_id}/review-decision")
async def submit_review_decision(
    room_id: str,
    body: ReviewDecisionBody,
    request: Request,
) -> dict:
    """NodeReviewPanel 三按钮入口：approve / reject / escalate。"""
    resolved = _resolve_scope_for_room(room_id)
    if resolved is None:
        return error_response(404, "meeting_room_not_found")
    sid, scope_type = resolved

    pool = getattr(request.app.state, "agent_pool", None)
    detail = _service.get_room_detail(room_id) or {}
    ticket_title = str(detail.get("ticket_title") or "")

    orch = MeetingRoomOrchestrator()
    try:
        result = orch.confirm_node_delivery(
            scope_type=scope_type,
            scope_id=sid,
            room_id=room_id,
            approved=body.mode == "approve",
            comment=body.comment or "",
            ticket_title=ticket_title,
            agent_pool=pool,
            mode=body.mode,
        )
    except ValueError as exc:
        return error_response(400, str(exc))
    except Exception as exc:
        logger.exception("submit_review_decision failed: %s", exc)
        return error_response(500, "review_decision_failed", str(exc))
    return success_response(result)

