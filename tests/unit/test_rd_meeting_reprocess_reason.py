"""重处理原因：一次性注入 room_skill 与 room_state 生命周期。"""

from __future__ import annotations

from synapse.rd_meeting.pipeline import _clear_reprocess_context_if_done
from synapse.rd_meeting.room_skill import format_reprocess_instruction


def test_format_reprocess_instruction_empty_without_reason(monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.load_room_state",
        lambda _sid: {},
    )
    assert format_reprocess_instruction("scope-1", "req_clarify") == ""


def test_format_reprocess_instruction_renders_block(monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.load_room_state",
        lambda _sid: {
            "reprocess_reason": "请补充接口边界说明",
            "reprocess_until_node_id": "acceptance",
        },
    )
    text = format_reprocess_instruction("scope-1", "req_clarify")
    assert "重新处理" in text
    assert "请补充接口边界说明" in text
    assert "`req_clarify`" in text
    assert "必须遵循" in text


def test_clear_reprocess_context_if_done_only_at_anchor(monkeypatch):
    store: dict[str, dict] = {}

    def _load(sid: str):
        return dict(store.get(sid, {}))

    def _save(sid: str, rs: dict):
        store[sid] = dict(rs)

    monkeypatch.setattr("synapse.rd_meeting.pipeline.load_room_state", _load)
    monkeypatch.setattr("synapse.rd_meeting.pipeline.save_room_state", _save)

    scope = "rs-reason"
    store[scope] = {
        "reprocess_reason": "按用户意见重做",
        "reprocess_until_node_id": "acceptance",
    }

    _clear_reprocess_context_if_done(scope, "req_clarify")
    assert store[scope]["reprocess_reason"] == "按用户意见重做"

    _clear_reprocess_context_if_done(scope, "acceptance")
    assert "reprocess_reason" not in store[scope]
    assert "reprocess_until_node_id" not in store[scope]
