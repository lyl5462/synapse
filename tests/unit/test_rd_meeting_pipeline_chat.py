"""pipeline_chat：host_llm_begin 流程场景区分。"""

from __future__ import annotations

from synapse.rd_meeting.pipeline_chat import (
    STEP_HOST_FIRST_CALL_REUSED_SUMMARY,
    STEP_HOST_FIRST_CALL_SUMMARY,
    format_host_first_call_chat,
    resolve_host_llm_begin_kind,
)


def test_format_host_first_call_by_flow_kind():
    assert format_host_first_call_chat(kind="start_work") == STEP_HOST_FIRST_CALL_SUMMARY
    assert format_host_first_call_chat(kind="delivery_confirmed") == STEP_HOST_FIRST_CALL_REUSED_SUMMARY


def test_format_host_first_call_ignores_legacy_reused_prompt_flag():
    assert format_host_first_call_chat(reused_prompt=True) == STEP_HOST_FIRST_CALL_SUMMARY
    assert format_host_first_call_chat(reused_prompt=False) == STEP_HOST_FIRST_CALL_SUMMARY


def test_resolve_host_llm_begin_kind():
    assert resolve_host_llm_begin_kind({"llm_begin_kind": "delivery_confirmed"}) == "delivery_confirmed"
    assert resolve_host_llm_begin_kind({"reused_host_prompt_cache": True}) == "start_work"
    assert resolve_host_llm_begin_kind({}) == "start_work"
