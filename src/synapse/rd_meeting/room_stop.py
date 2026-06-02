"""会议室停止：服务重启批量标 stopped、用户终止节点运行。"""

from __future__ import annotations

import logging
from typing import Literal

from synapse.rd_meeting.paths import iter_work_order_directories
from synapse.rd_meeting.room_runtime import (
    append_history_event,
    load_room_state,
    mark_room_stopped,
)

logger = logging.getLogger(__name__)

StoppedReason = Literal["server_restart", "user_stop"]

# 重启时改为 stopped；failed / completed 不动
_STATUSES_STOP_ON_SERVER_RESTART = frozenset({"processing", "human_intervention"})


def mark_active_rooms_stopped_on_server_restart() -> int:
    """进程启动时：将仍在自动/待介入态的会议室标为 stopped（failed 不改）。"""
    count = 0
    for scope_dir in iter_work_order_directories():
        sid = scope_dir.name
        rs = load_room_state(sid)
        if not rs:
            continue
        st = str(rs.get("status") or "").strip()
        if st not in _STATUSES_STOP_ON_SERVER_RESTART:
            continue
        room_id = str(rs.get("room_id") or "").strip()
        node_id = str(rs.get("current_node_id") or "pending")
        mark_room_stopped(sid, reason="server_restart")
        append_history_event(
            sid,
            {
                "event": "room_stopped",
                "room_id": room_id,
                "node_id": node_id,
                "text": "后端服务重启，会议室已停止；可重新处理当前节点后继续",
                "stopped_reason": "server_restart",
                "log_type": "warning",
                "agent_id": "system",
            },
        )
        count += 1
        logger.info(
            "meeting room marked stopped after server restart scope=%s prev_status=%s",
            sid,
            st,
        )
    if count:
        logger.warning(
            "Server restart: marked %s meeting room(s) as stopped (processing/human_intervention only)",
            count,
        )
    return count
