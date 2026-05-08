"""工单详情弹窗：聚合 sop_trajectories / token_usage（本地库）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from synapse.api.schemas import error_response, success_response
from synapse.storage.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev/work-order", tags=["work_order_metrics"])

_db_instance: Database | None = None
_db_lock = asyncio.Lock()


async def _get_db() -> Database | None:
    global _db_instance
    if _db_instance is not None and _db_instance._connection is not None:
        return _db_instance
    async with _db_lock:
        if _db_instance is not None and _db_instance._connection is not None:
            return _db_instance
        try:
            db = Database()
            await db.connect()
            if db._connection is None:
                logger.error("[WorkOrderMetrics] Database connect returned but _connection is None")
                return None
            _db_instance = db
        except Exception as e:
            logger.error("[WorkOrderMetrics] Failed to connect database: %s", e)
            return None
    return _db_instance


class WorkOrderDbMetricsBody(BaseModel):
    demand_no: str = Field(..., description="需求单号")
    task_nos: list[str] = Field(default_factory=list, description="研发单号列表，可空")


class WorkOrderHumanInLoopFlagBody(BaseModel):
    order_id: str = Field(..., description="单个工单 ID，对应 sop_trajectories.order_id")


def _usage_scenes(demand_no: str, task_nos: list[str]) -> list[str]:
    scenes: list[str] = []
    d = demand_no.strip()
    if d:
        scenes.append(f"dev_whalecloud_sop_{d}")
    for t in task_nos:
        tid = str(t).strip()
        if tid:
            scenes.append(f"dev_whalecloud_sop_{tid}")
    return scenes


def _order_ids(demand_no: str, task_nos: list[str]) -> list[str]:
    ids: list[str] = []
    d = demand_no.strip()
    if d:
        ids.append(d)
    for t in task_nos:
        tid = str(t).strip()
        if tid and tid not in ids:
            ids.append(tid)
    return ids


@router.post("/db-metrics")
async def work_order_db_metrics(body: WorkOrderDbMetricsBody) -> dict[str, Any]:
    """按需求单号 + 研发单号聚合轨迹耗时/人工/产出物，并按 usage_scene 汇总 token。"""
    db = await _get_db()
    if db is None:
        return error_response(503, "数据库不可用")

    demand_no = body.demand_no.strip()
    if not demand_no:
        return error_response(400, "demand_no 不能为空")

    task_nos = [str(x).strip() for x in body.task_nos if str(x).strip()]
    order_ids = _order_ids(demand_no, task_nos)
    scenes = _usage_scenes(demand_no, task_nos)

    try:
        per_order = await db.get_sop_trajectory_metrics_by_order_ids(order_ids)
        summary_sop = await db.get_sop_trajectory_summary_for_order_ids(order_ids)
        total_tokens = await db.get_token_usage_total_tokens_for_scenes(scenes)
    except Exception as e:
        logger.exception("[WorkOrderMetrics] query failed: %s", e)
        return error_response(500, "查询工单库指标失败", error=str(e))

    dm = per_order.get(demand_no, {"deal_seconds": 0, "deal_tokens": 0, "human_interventions": 0})
    task_metrics: dict[str, dict[str, int]] = {}
    for tid in task_nos:
        task_metrics[tid] = per_order.get(
            tid, {"deal_seconds": 0, "deal_tokens": 0, "human_interventions": 0}
        )

    data = {
        "summary": {
            "process_seconds": int(summary_sop.get("process_seconds") or 0),
            "total_tokens": int(total_tokens),
            "human_interventions": int(summary_sop.get("human_interventions") or 0),
            "artifacts": list(summary_sop.get("artifacts") or []),
        },
        "demand_metrics": {
            "deal_seconds": int(dm.get("deal_seconds") or 0),
            "deal_tokens": int(dm.get("deal_tokens") or 0),
        },
        "task_metrics": task_metrics,
    }
    return success_response(data)


@router.post("/human-in-loop-flags")
async def work_order_human_in_loop_flags(body: WorkOrderHumanInLoopFlagBody) -> dict[str, Any]:
    """按单个 order_id 查询 sop_trajectories：是否存在 sop_node_human_in_the_loop = 1 的行。"""
    db = await _get_db()
    if db is None:
        return error_response(503, "数据库不可用")

    oid = str(body.order_id or "").strip()
    if not oid:
        return error_response(400, "order_id 不能为空")

    try:
        flags = await db.get_sop_human_in_loop_flags_by_order_ids([oid])
    except Exception as e:
        logger.exception("[WorkOrderMetrics] human_in_loop_flag failed: %s", e)
        return error_response(500, "查询人工介入标记失败", error=str(e))

    hit = bool(flags.get(oid))
    return success_response({"human_in_the_loop": hit})
