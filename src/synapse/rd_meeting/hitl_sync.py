"""会议室人工门控 → sop_trajectories（对齐 human-in-loop-flags）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from synapse.rd_meeting.paths import scope_dir
from synapse.rd_sop.nodes import stage_id_for_node_id

logger = logging.getLogger(__name__)


def _now_sql_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def _get_db():
    try:
        from synapse.storage.database import Database

        db = Database()
        await db.connect()
        if db._connection is None:
            return None
        return db
    except Exception as exc:
        logger.debug("hitl_sync db unavailable: %s", exc)
        return None


async def record_hitl_trajectory(*, order_id: str, stage_id: str, node_id: str) -> bool:
    """写入/更新 sop_trajectories，使 human-in-loop-flags 可读到 HITL。"""
    oid = (order_id or "").strip()
    nid = (node_id or "").strip()
    if not oid or not nid:
        return False

    step_id = str(stage_id_for_node_id(nid))
    now = _now_sql_ts()

    db = await _get_db()
    if db is not None and db._connection is not None:
        try:
            await db._connection.execute(
                """
                INSERT INTO sop_trajectories (
                    order_id, sop_step_id, sop_node_id, sop_node_status,
                    sop_node_start_time, sop_node_end_time, sop_node_use_model,
                    sop_node_use_tokens, sop_node_output_list, sop_node_human_in_the_loop
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id, sop_step_id, sop_node_id) DO UPDATE SET
                    sop_node_status = excluded.sop_node_status,
                    sop_node_end_time = excluded.sop_node_end_time,
                    sop_node_human_in_the_loop = 1
                """,
                (
                    oid,
                    step_id,
                    nid,
                    "human_intervention",
                    now,
                    now,
                    "rd_meeting",
                    0,
                    "[]",
                    1,
                ),
            )
            await db._connection.commit()
            return True
        except Exception as exc:
            logger.warning("insert sop_trajectories hitl failed: %s", exc)

    # 文件兜底：工单目录标记（不进入 userwork）
    try:
        flag_path = scope_dir(oid) / "hitl.flag.json"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(
            json.dumps(
                {
                    "order_id": oid,
                    "node_id": nid,
                    "stage_id": step_id,
                    "updated_at": now,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.warning("write hitl.flag failed: %s", exc)
        return False
