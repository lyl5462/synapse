"""会议室：用户输入/表单反馈队列，供下一轮 host 任务注入 prompt。"""

from __future__ import annotations

from synapse.rd_meeting.host_prompt_cache import clear_host_prompt_cache
from synapse.rd_meeting.room_runtime import load_room_state, save_room_state

_MAX_PENDING = 32
_HITL_FORM_PREFIX = "[人工确认表单]"


def is_hitl_form_submission(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith(_HITL_FORM_PREFIX) or "decision:" in t.lower()


def append_user_context_pending(scope_id: str, text: str) -> None:
    """记录用户输入，下次 ``run_current_node`` 时注入 host prompt 并清空。"""
    msg = (text or "").strip()
    if not msg:
        return
    sid = scope_id.strip()
    rs = dict(load_room_state(sid) or {})
    pending = rs.get("user_context_pending")
    if not isinstance(pending, list):
        pending = []
    pending = [*pending, msg]
    if len(pending) > _MAX_PENDING:
        pending = pending[-_MAX_PENDING :]
    rs["user_context_pending"] = pending
    save_room_state(sid, rs)
    clear_host_prompt_cache(sid)


def drain_user_context_for_prompt(scope_id: str) -> str:
    """取出并清空队列，格式化为 Markdown 段落（无内容则返回空串）。"""
    sid = scope_id.strip()
    rs = dict(load_room_state(sid) or {})
    pending = rs.get("user_context_pending")
    if not isinstance(pending, list) or not pending:
        return ""
    rs.pop("user_context_pending", None)
    save_room_state(sid, rs)
    blocks = [str(x).strip() for x in pending if str(x).strip()]
    if not blocks:
        return ""
    body = "\n\n---\n\n".join(blocks)
    return f"## 用户输入与表单反馈（自上次节点运行以来，含本轮 HITL）\n\n{body}\n"
