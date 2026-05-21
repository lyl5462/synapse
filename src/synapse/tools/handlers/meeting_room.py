"""研发会议室工具 handler。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...core.agent import Agent

logger = logging.getLogger(__name__)


class MeetingRoomToolHandler:
    TOOLS = ["submit_meeting_work_plan"]

    def __init__(self, agent: Agent):
        self.agent = agent

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name != "submit_meeting_work_plan":
            return f"❌ Unknown meeting room tool: {tool_name}"
        return await self._submit_work_plan(params)

    async def _submit_work_plan(self, params: dict[str, Any]) -> str:
        from synapse.rd_meeting.work_plan import format_plan_summary_text, submit_work_plan

        goal_summary = str(params.get("goal_summary") or "").strip()
        items = params.get("items")
        if not goal_summary:
            return "❌ goal_summary 不能为空"
        if not isinstance(items, list) or not items:
            return "❌ items 必须为非空数组"

        session = getattr(self.agent, "_current_session", None)
        session_id = (
            getattr(session, "id", None)
            or getattr(session, "session_id", None)
            or getattr(self.agent, "_current_session_id", None)
            or ""
        )
        try:
            plan = submit_work_plan(
                session_id=str(session_id),
                goal_summary=goal_summary,
                items=items,
            )
        except ValueError as exc:
            return f"❌ {exc}"
        except Exception as exc:
            logger.exception("submit_meeting_work_plan failed: %s", exc)
            return f"❌ 提交工作安排计划失败: {exc}"

        n = len(plan.get("items") or [])
        preview = format_plan_summary_text(plan)
        return (
            f"✅ 工作安排计划已提交（plan_id={plan.get('plan_id')}，共 {n} 项）。"
            f"请按 items 使用 delegate_to_agent / delegate_parallel 执行。\n\n{preview}"
        )


def create_meeting_room_handler(agent: "Agent") -> MeetingRoomToolHandler:
    return MeetingRoomToolHandler(agent)
