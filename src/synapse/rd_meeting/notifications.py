"""Phase 3：人工介入桌面通知与 HITL 轨迹对齐。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from synapse.rd_sop.nodes import node_display_name

logger = logging.getLogger(__name__)


def schedule_human_intervention_notify(
    *,
    scope_id: str,
    room_id: str,
    node_id: str,
    ticket_title: str = "",
    reason: str = "",
) -> None:
    """从同步上下文调度异步通知（不阻塞会议室主流程）。"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            notify_human_intervention(
                scope_id=scope_id,
                room_id=room_id,
                node_id=node_id,
                ticket_title=ticket_title,
                reason=reason,
            )
        )
    except RuntimeError:
        try:
            asyncio.run(
                notify_human_intervention(
                    scope_id=scope_id,
                    room_id=room_id,
                    node_id=node_id,
                    ticket_title=ticket_title,
                    reason=reason,
                )
            )
        except Exception as exc:
            logger.warning("sync hitl notify failed: %s", exc)


def _notify_desktop_sync(title: str, body: str) -> bool:
    try:
        from synapse.config import settings
        from synapse.core.desktop_notify import send_desktop_notification

        if not settings.desktop_notify_enabled:
            return False
        return send_desktop_notification(
            title,
            body,
            sound=settings.desktop_notify_sound,
        )
    except Exception as exc:
        logger.warning("meeting room desktop notify failed: %s", exc)
        return False


async def notify_human_intervention(
    *,
    scope_id: str,
    room_id: str,
    node_id: str,
    ticket_title: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """桌面通知 + 写入 sop_trajectories（供 human-in-loop-flags 只读）。"""
    node_name = node_display_name(node_id)
    title = "研发会议室 · 待人工介入"
    body = f"{ticket_title or scope_id} · {node_name}"
    if reason:
        body = f"{body}\n{reason[:200]}"

    desktop_ok = await asyncio.to_thread(_notify_desktop_sync, title, body)

    hitl_db_ok = False
    try:
        from synapse.rd_meeting.hitl_sync import record_hitl_trajectory
        from synapse.rd_sop.nodes import stage_id_for_node_id

        hitl_db_ok = await record_hitl_trajectory(
            order_id=scope_id,
            stage_id=str(stage_id_for_node_id(node_id)),
            node_id=node_id,
        )
    except Exception as exc:
        logger.warning("record_hitl_trajectory failed: %s", exc)

    return {
        "desktop_sent": desktop_ok,
        "hitl_recorded": hitl_db_ok,
        "scope_id": scope_id,
        "room_id": room_id,
        "node_id": node_id,
    }
