"""主控提示词 room_state 缓存与第四步复用。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from synapse.rd_meeting.host_prompt import assemble_host_prompt_bundle
from synapse.rd_meeting.host_prompt_cache import (
    clear_host_prompt_cache,
    get_host_prompt_cache,
    resolve_cached_host_meeting_prompt,
    save_host_prompt_cache,
)
from synapse.rd_meeting.orchestrator import MeetingRoomOrchestrator


@pytest.fixture
def host_binding() -> dict:
    return {
        "node_id": "req_clarify",
        "node_name": "需求澄清",
        "stage_id": 1,
        "host_profile_id": "default",
        "worker_profile_ids": [],
        "host_llm_endpoint_key": "default",
        "worker_llm_endpoint_key": "default",
    }


def test_save_and_resolve_cache(host_binding, monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_code": "ok", "prod": "p1", "repos": [], "docs": []},
            {"synapse_url": "http://127.0.0.1:10001"},
        ),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context._scope_row",
        lambda *_a, **_k: {"demand_no": "C1", "demand_title": "T", "prod": "p1"},
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync.load_scope_work_order_context",
        lambda *_a, **_k: {"demand_no": "C1", "prod": "p1"},
    )
    rs: dict = {}

    def _load(_sid: str):
        return dict(rs)

    def _save(_sid: str, payload: dict):
        rs.clear()
        rs.update(payload)

    monkeypatch.setattr("synapse.rd_meeting.host_prompt_cache.load_room_state", _load)
    monkeypatch.setattr("synapse.rd_meeting.host_prompt_cache.save_room_state", _save)

    bundle = assemble_host_prompt_bundle(
        scope_type="demand",
        scope_id="C1",
        node_id="req_clarify",
        binding=host_binding,
    )
    save_host_prompt_cache("C1", bundle)

    cached, reused = resolve_cached_host_meeting_prompt("C1", host_binding)
    assert reused is True
    assert (cached or "").strip() == str(bundle["meeting_prompt"]).strip()

    wrong_node = {**host_binding, "node_id": "other"}
    assert get_host_prompt_cache("C1", wrong_node) is None

    clear_host_prompt_cache("C1")
    assert get_host_prompt_cache("C1", host_binding) is None


def test_configure_host_reuses_cache(host_binding, monkeypatch):
    prompt_body = "CACHED-MEETING-PROMPT-BODY"
    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.resolve_cached_host_meeting_prompt",
        lambda *_a, **_k: (prompt_body, True),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.build_room_skill_prompt",
        lambda *_a, **_k: pytest.fail("should not rebuild when cache hit"),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.build_node_init_log_data",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr("synapse.rd_meeting.orchestrator.load_dev_status", lambda *_a: {})

    agent = MagicMock()
    agent._context = MagicMock()
    agent._build_system_prompt = MagicMock(return_value="sys")

    reused = MeetingRoomOrchestrator._configure_meeting_agent(
        agent,
        role="host",
        binding=host_binding,
        scope_type="demand",
        scope_id="C1",
        ticket_title="",
        scope_path="/tmp/work/C1",
    )
    assert reused is True
    assert prompt_body in (getattr(agent._context, "system", None) or "")
