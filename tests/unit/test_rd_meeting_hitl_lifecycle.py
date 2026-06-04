"""human_confirm 双阶段门控：会中问卷 → node_review。"""

from __future__ import annotations

from synapse.rd_meeting.hitl_form import HUMAN_SUPPLEMENT_QUESTION_ID
from synapse.rd_meeting.hitl_lifecycle import (
    READY_FOR_NODE_REVIEW_KEY,
    clear_ready_for_node_review,
    is_ready_for_node_review,
    node_archive_ready_for_review,
    reset_human_confirm_lifecycle,
    resolve_ready_for_node_review_after_hitl,
    set_ready_for_node_review,
    should_enter_node_review_after_hitl_locked,
    should_enter_node_review_gate,
    user_has_supplement_input,
)

_SCHEMA = {
    "questions": [{"id": "q1", "type": "single", "title": "Q", "options": [{"value": "daily", "label": "D"}]}],
}


def test_user_has_supplement_input_empty_supplement():
    assert not user_has_supplement_input({HUMAN_SUPPLEMENT_QUESTION_ID: ""})


def test_user_has_supplement_input_detects_per_question_other():
    vals = {"q1": ["daily", "OTHER:自定义"], HUMAN_SUPPLEMENT_QUESTION_ID: ""}
    assert user_has_supplement_input(vals, schema=_SCHEMA)


def test_user_has_supplement_input_detects_human_supplement():
    vals = {HUMAN_SUPPLEMENT_QUESTION_ID: "还需要补充风险说明"}
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


def test_resolve_ready_only_when_archive_exists(monkeypatch, tmp_path):
    scope = "arch_ready_scope"
    node_id = "req_clarify"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    monkeypatch.setattr(
        "synapse.rd_meeting.validation.validate_node_archive_files",
        lambda sid, stage, nid: __import__(
            "synapse.rd_meeting.validation", fromlist=["NodeOutputValidation"]
        ).NodeOutputValidation(ok=False, errors=["missing"]),
    )
    assert not resolve_ready_for_node_review_after_hitl(scope, node_id, "options_only")
    assert resolve_ready_for_node_review_after_hitl(scope, node_id, "with_free_text") is False

    monkeypatch.setattr(
        "synapse.rd_meeting.validation.validate_node_archive_files",
        lambda sid, stage, nid: __import__(
            "synapse.rd_meeting.validation", fromlist=["NodeOutputValidation"]
        ).NodeOutputValidation(ok=True, errors=[]),
    )
    assert resolve_ready_for_node_review_after_hitl(scope, node_id, "options_only")


def test_clear_ready_for_node_review(monkeypatch):
    store: dict[str, dict] = {}

    def _load(sid: str):
        return dict(store.get(sid, {}))

    def _save(sid: str, rs: dict):
        store[sid] = dict(rs)

    monkeypatch.setattr("synapse.rd_meeting.hitl_lifecycle.load_room_state", _load)
    monkeypatch.setattr("synapse.rd_meeting.hitl_lifecycle.save_room_state", _save)

    scope = "clear_ready_scope"
    store[scope] = {READY_FOR_NODE_REVIEW_KEY: True}
    clear_ready_for_node_review(scope)
    assert not is_ready_for_node_review(_load(scope))


def test_should_enter_node_review_after_hitl_locked(monkeypatch, tmp_path):
    scope = "locked_gate_scope"
    node_id = "req_clarify"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    monkeypatch.setattr(
        "synapse.rd_meeting.validation.validate_node_archive_files",
        lambda sid, stage, nid: __import__(
            "synapse.rd_meeting.validation", fromlist=["NodeOutputValidation"]
        ).NodeOutputValidation(ok=False, errors=["missing"]),
    )
    rs = {
        "hitl_locked": True,
        "hitl_submission": {"kind": "interactive", "locked": True},
        "intervention_kind": "interactive",
    }
    assert not should_enter_node_review_after_hitl_locked(scope, node_id, rs)
    assert not should_enter_node_review_gate(scope, node_id, rs)

    monkeypatch.setattr(
        "synapse.rd_meeting.validation.validate_node_archive_files",
        lambda sid, stage, nid: __import__(
            "synapse.rd_meeting.validation", fromlist=["NodeOutputValidation"]
        ).NodeOutputValidation(ok=True, errors=[]),
    )
    assert should_enter_node_review_after_hitl_locked(scope, node_id, rs)
    assert should_enter_node_review_gate(scope, node_id, rs)

    rs_pending_form = {**rs, "hitl_form_schema": {"questions": [{"id": "q1"}]}}
    assert not should_enter_node_review_after_hitl_locked(scope, node_id, rs_pending_form)

    rs_exception = {**rs, "hitl_submission": {"kind": "exception"}}
    assert not should_enter_node_review_after_hitl_locked(scope, node_id, rs_exception)

    rs_flag_only = {"room_id": "r1"}
    assert not should_enter_node_review_gate(scope, node_id, rs_flag_only)
    rs_flag_only[READY_FOR_NODE_REVIEW_KEY] = True
    assert should_enter_node_review_gate(scope, node_id, rs_flag_only)


def test_record_delegation_started_clears_ready(monkeypatch):
    store: dict[str, dict] = {"deleg_scope": {READY_FOR_NODE_REVIEW_KEY: True}}

    monkeypatch.setattr("synapse.rd_meeting.live.load_room_state", lambda sid: dict(store.get(sid, {})))
    monkeypatch.setattr(
        "synapse.rd_meeting.live.save_room_state",
        lambda sid, rs: store.__setitem__(sid, dict(rs)),
    )
    monkeypatch.setattr("synapse.rd_meeting.hitl_lifecycle.load_room_state", lambda sid: dict(store.get(sid, {})))
    monkeypatch.setattr(
        "synapse.rd_meeting.hitl_lifecycle.save_room_state",
        lambda sid, rs: store.__setitem__(sid, dict(rs)),
    )
    monkeypatch.setattr("synapse.rd_meeting.live.scope_id_for_room_id", lambda rid: "deleg_scope")
    monkeypatch.setattr("synapse.rd_meeting.live.append_history_event", lambda *a, **k: None)
    monkeypatch.setattr(
        "synapse.rd_meeting.live.resolve_history_node_id",
        lambda sid, row: "req_clarify",
    )

    from synapse.rd_meeting.live import record_delegation_started

    record_delegation_started(
        "rd_meeting:room-1:host",
        from_agent="default",
        to_agent="whalecloud-rd-expert",
        reason="看代码",
        task_preview="分析模块",
    )
    assert not store["deleg_scope"].get(READY_FOR_NODE_REVIEW_KEY)
