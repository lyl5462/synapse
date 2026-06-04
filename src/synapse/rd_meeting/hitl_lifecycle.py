"""human_confirm 双阶段门控：会中问卷 (hitl_form) → 完成确认 (node_review)。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.hitl_feedback import (
    HitlFeedbackMode,
    user_has_free_text_input,
)
from synapse.rd_meeting.room_runtime import load_room_state, save_room_state

READY_FOR_NODE_REVIEW_KEY = "ready_for_node_review"
HITL_CLARIFY_ROUND_KEY = "hitl_clarify_round"
HITL_FEEDBACK_MODE_KEY = "hitl_feedback_mode"
MAX_HOST_QUESTIONNAIRE_ATTEMPTS = 5

_PROMPT_REQUIRE_INTERACTIVE = """
## ⚠️ 系统提示：必须提交会中问卷（kind=interactive）

你尚未通过 ``submit_hitl_questionnaire`` 工具提交 **interactive** 会中问卷，系统无法进入人工确认总结。

**本次要求**：
1. 直接调用 ``submit_hitl_questionnaire(kind="interactive", ...)``，题目覆盖本节点待用户确认的决策点；
2. **禁止**使用 ``kind=result_confirm``（节点完成总结由系统在用户确认问卷后自动进入 NodeReview）；
3. **summary** 会渲染在表单顶部；每题 **context** 须含用户可独立审阅的完整正文（签收题禁止只写维度关键词）；
4. 调用工具后立即停止，不要重复总结正文。
"""


def is_ready_for_node_review(room_state: dict[str, Any] | None) -> bool:
    if not isinstance(room_state, dict):
        return False
    return bool(room_state.get(READY_FOR_NODE_REVIEW_KEY))


def should_enter_node_review_after_hitl_locked(
    scope_id: str,
    node_id: str,
    room_state: dict[str, Any] | None,
) -> bool:
    """会中问卷已提交并锁定，且约定归档 Markdown 已落盘 → 应进入结果确认门控。

    弥补 ``ready_for_node_review`` 仅在问卷提交瞬间置位、委派会清标等问题。
    """
    if not isinstance(room_state, dict):
        return False
    if not room_state.get("hitl_locked"):
        return False
    # 仍有待填问卷 schema 时不应跳过会中门控（防御性；主路径在 orchestrator 优先消费 tool_questionnaire）
    if isinstance(room_state.get("hitl_form_schema"), dict):
        return False
    submission = room_state.get("hitl_submission")
    kind = ""
    if isinstance(submission, dict):
        kind = str(submission.get("kind") or "").strip().lower()
    if not kind:
        kind = str(room_state.get("intervention_kind") or "").strip().lower()
    if kind and kind not in ("interactive", ""):
        return False
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid or nid == "pending":
        return False
    return node_archive_ready_for_review(sid, nid)


def should_enter_node_review_gate(
    scope_id: str,
    node_id: str,
    room_state: dict[str, Any] | None,
) -> bool:
    """节点收尾是否应进入 NodeReview（``enter_node_review_gate``）。"""
    if is_ready_for_node_review(room_state):
        return True
    return should_enter_node_review_after_hitl_locked(scope_id, node_id, room_state)


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


def clear_ready_for_node_review(scope_id: str) -> None:
    """节点仍在进行中（如再次委派 Worker）时撤销 NodeReview 就绪标记。"""
    set_ready_for_node_review(scope_id, False)


def node_archive_ready_for_review(scope_id: str, node_id: str) -> bool:
    """约定归档 Markdown 已落盘时才允许进入 NodeReview。"""
    from synapse.rd_meeting.validation import validate_node_archive_files
    from synapse.rd_sop.nodes import stage_id_for_node_id, stage_name_for_id

    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid or nid == "pending":
        return False
    stage_name = stage_name_for_id(stage_id_for_node_id(nid))
    return validate_node_archive_files(sid, stage_name, nid).ok


def resolve_ready_for_node_review_after_hitl(
    scope_id: str,
    node_id: str,
    feedback_mode: HitlFeedbackMode,
) -> bool:
    """会中问卷提交后：仅「仅选项」且归档文件已存在时才标记 NodeReview 就绪。"""
    from synapse.rd_meeting.solution_review import uses_solution_review_gate

    if uses_solution_review_gate(node_id):
        return False
    if feedback_mode != "options_only":
        return False
    return node_archive_ready_for_review(scope_id, node_id)


def set_hitl_feedback_mode(scope_id: str, mode: HitlFeedbackMode | None) -> None:
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = dict(load_room_state(sid) or {})
    if mode:
        rs[HITL_FEEDBACK_MODE_KEY] = mode
    else:
        rs.pop(HITL_FEEDBACK_MODE_KEY, None)
    save_room_state(sid, rs)


def reset_human_confirm_lifecycle(scope_id: str) -> None:
    """新节点开始或节点推进后重置会中澄清 / 完成确认状态。"""
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = dict(load_room_state(sid) or {})
    rs.pop(READY_FOR_NODE_REVIEW_KEY, None)
    rs.pop(HITL_CLARIFY_ROUND_KEY, None)
    rs.pop(HITL_FEEDBACK_MODE_KEY, None)
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


def user_has_supplement_input(
    values: dict[str, Any],
    *,
    comment: str = "",
    schema: dict[str, Any] | None = None,
) -> bool:
    """兼容旧名：是否含任意自由输入（见 ``user_has_free_text_input``）。"""
    return user_has_free_text_input(values, schema, comment=comment)
