"""human_confirm 双阶段门控：会中问卷 (hitl_form) → 完成确认 (node_review)。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.hitl_form import HUMAN_SUPPLEMENT_QUESTION_ID
from synapse.rd_meeting.room_runtime import load_room_state, save_room_state

READY_FOR_NODE_REVIEW_KEY = "ready_for_node_review"
HITL_CLARIFY_ROUND_KEY = "hitl_clarify_round"
MAX_HOST_QUESTIONNAIRE_ATTEMPTS = 5

_PROMPT_REQUIRE_INTERACTIVE = """
## ⚠️ 系统提示：必须提交会中问卷（kind=interactive）

你尚未通过 ``submit_hitl_questionnaire`` 工具提交 **interactive** 会中问卷，系统无法进入人工确认总结。

**本次要求**：
1. 直接调用 ``submit_hitl_questionnaire(kind="interactive", ...)``，题目覆盖本节点待用户确认的决策点；
2. **禁止**使用 ``kind=result_confirm``（节点完成总结由系统在用户确认问卷后自动进入 NodeReview）；
3. 调用工具后立即停止，不要重复总结正文。
4. 问卷末尾系统会自动追加「请问您还有什么需要补充的吗？」；用户在该题留空才表示可进入完成总结。
"""


def is_ready_for_node_review(room_state: dict[str, Any] | None) -> bool:
    if not isinstance(room_state, dict):
        return False
    return bool(room_state.get(READY_FOR_NODE_REVIEW_KEY))


def set_ready_for_node_review(scope_id: str, ready: bool) -> None:
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = dict(load_room_state(sid) or {})
    if ready:
        rs[READY_FOR_NODE_REVIEW_KEY] = True
    else:
        rs.pop(READY_FOR_NODE_REVIEW_KEY, None)
    save_room_state(sid, rs)


def reset_human_confirm_lifecycle(scope_id: str) -> None:
    """新节点开始或节点推进后重置会中澄清 / 完成确认状态。"""
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = dict(load_room_state(sid) or {})
    rs.pop(READY_FOR_NODE_REVIEW_KEY, None)
    rs.pop(HITL_CLARIFY_ROUND_KEY, None)
    save_room_state(sid, rs)


def get_clarify_round(scope_id: str) -> int:
    rs = load_room_state(scope_id) or {}
    try:
        return max(0, int(rs.get(HITL_CLARIFY_ROUND_KEY) or 0))
    except (TypeError, ValueError):
        return 0


def bump_clarify_round(scope_id: str) -> int:
    sid = (scope_id or "").strip()
    if not sid:
        return 0
    rs = dict(load_room_state(sid) or {})
    n = get_clarify_round(sid) + 1
    rs[HITL_CLARIFY_ROUND_KEY] = n
    save_room_state(sid, rs)
    return n


def prompt_require_interactive_questionnaire() -> str:
    return _PROMPT_REQUIRE_INTERACTIVE.strip()


def extract_human_supplement(values: dict[str, Any], *, comment: str = "") -> str:
    """用户是否还有补充：优先 human_supplement 题，其次 comment / 补充说明。"""
    parts: list[str] = []
    raw = values.get(HUMAN_SUPPLEMENT_QUESTION_ID)
    if raw is not None:
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text:
            parts.append(text)
    c = (comment or "").strip()
    if c:
        parts.append(c)
    return "\n".join(parts).strip()


def user_has_supplement_input(values: dict[str, Any], *, comment: str = "") -> bool:
    return bool(extract_human_supplement(values, comment=comment))
