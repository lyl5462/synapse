"""human_confirm 双阶段门控：会中问卷 → node_review。"""

from __future__ import annotations

from synapse.rd_meeting.hitl_form import HUMAN_SUPPLEMENT_QUESTION_ID
from synapse.rd_meeting.hitl_lifecycle import (
    READY_FOR_NODE_REVIEW_KEY,
    extract_human_supplement,
    is_ready_for_node_review,
    reset_human_confirm_lifecycle,
    set_ready_for_node_review,
    user_has_supplement_input,
)


def test_extract_human_supplement_empty():
    assert extract_human_supplement({HUMAN_SUPPLEMENT_QUESTION_ID: "  "}) == ""
    assert not user_has_supplement_input({HUMAN_SUPPLEMENT_QUESTION_ID: ""})


def test_extract_human_supplement_with_text():
    vals = {HUMAN_SUPPLEMENT_QUESTION_ID: "还需要补充风险说明"}
    assert extract_human_supplement(vals) == "还需要补充风险说明"
    assert user_has_supplement_input(vals)


def test_ready_for_node_review_room_state(monkeypatch):
    store: dict[str, dict] = {}

    def _load(sid: str):
        return dict(store.get(sid, {}))

    def _save(sid: str, rs: dict):
        store[sid] = dict(rs)

    monkeypatch.setattr("synapse.rd_meeting.hitl_lifecycle.load_room_state", _load)
    monkeypatch.setattr("synapse.rd_meeting.hitl_lifecycle.save_room_state", _save)

    scope = "lifecycle_test_scope"
    store[scope] = {"room_id": "r1", "status": "processing"}

    assert not is_ready_for_node_review(_load(scope))
    set_ready_for_node_review(scope, True)
    assert is_ready_for_node_review(_load(scope))

    reset_human_confirm_lifecycle(scope)
    assert READY_FOR_NODE_REVIEW_KEY not in _load(scope)
