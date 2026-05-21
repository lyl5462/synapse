"""会议室异常门控：委派失败等场景自动进入 human_intervention（P3）。"""

from __future__ import annotations

import asyncio
import logging

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.hitl_form import resolve_hitl_schema_for_gate
from synapse.rd_meeting.live import parse_rd_meeting_session, scope_id_for_room_id
from synapse.rd_meeting.phase import set_phase
from synapse.rd_sop.nodes import stage_id_for_node_id

logger = logging.getLogger(__name__)


def schedule_delegation_failure_gate(
    session_id: str,
    *,
    to_agent: str,
    error_text: str,
    scope_type: str = "demand",
) -> None:
    """委派失败时异步标记人工门控（仅 rd_meeting host 会话）。"""
    parsed = parse_rd_meeting_session(session_id)
    if not parsed or parsed.get("role") != "host":
        return

    async def _run() -> None:
        try:
            from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator

            scope_id = scope_id_for_room_id(parsed["room_id"])
            if not scope_id:
                return
            dev = load_dev_status(scope_id)
            node_id = str(dev.get("current_node_id") or "pending") if dev else "pending"
            binding = resolve_node_binding(
                node_id,
                scope_type=scope_type,
                scope_id=scope_id,
            )
            schema = resolve_hitl_schema_for_gate(
                binding,
                dynamic_schema=None,
                reason=f"委派 {to_agent} 失败：{(error_text or '')[:300]}",
                intervention_kind="exception",
            )
            stage_id = int(binding.get("stage_id") or stage_id_for_node_id(node_id))
            orch = MeetingRoomOrchestrator()
            orch.mark_human_gate(
                scope_type=scope_type,
                scope_id=scope_id,
                room_id=parsed["room_id"],
                node_id=node_id,
                reason=f"委派 {to_agent} 失败，需人工介入",
                hitl_form_schema=schema,
                pending_delivery={
                    "node_id": node_id,
                    "report_body": f"# 委派异常\n\n{(error_text or '')[:2000]}\n",
                    "await_confirm": False,
                    "stage_id": stage_id,
                },
                intervention_kind="exception",
            )
            set_phase(scope_id, "exception_gate")
        except Exception as exc:
            logger.warning("delegation failure gate failed: %s", exc)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        logger.debug("no event loop for delegation failure gate")
