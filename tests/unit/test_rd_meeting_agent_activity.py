"""agent_activity：四类埋点落盘与聚合。"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from types import SimpleNamespace

from synapse.rd_meeting.agent_activity import (
    aggregate_tools_and_skills,
    enrich_display,
    infer_tool_success,
    is_todo_block_preview,
    read_activity_log,
    record_input,
    record_output,
    record_skill,
    record_skill_load_blocked,
    record_tool,
    resolve_agent_billable_tokens,
    resolve_binding_for_profile,
    set_agent_activity_binding,
    try_record_tool_from_agent,
)
from synapse.rd_meeting.paths import agent_sop_profile_dir


@pytest.fixture
def activity_work(tmp_path, monkeypatch):
    monkeypatch.setattr("synapse.rd_meeting.agent_activity.agent_sop_profile_dir", lambda s, n, p: tmp_path / n / p)
    monkeypatch.setattr("synapse.rd_meeting.paths.agent_sop_profile_dir", lambda s, n, p: tmp_path / n / p)
    return tmp_path


def test_record_four_categories_and_read(activity_work):
    binding = resolve_binding_for_profile("scope1", "node_a", "host_pid", host_profile_id="host_pid")
    record_input(binding, source="system", input_kind="node_task", title="节点任务", summary="do work")
    record_output(binding, output_kind="llm_response", title="反馈", summary="done")
    record_tool(binding, tool_name="read_file", tool_input={"path": "x.md"}, result_preview="ok", success=True)
    record_skill(
        binding,
        skill_name="whalecloud-dev-tool-doc-generate",
        skill_tool="get_skill_info",
        result_preview="loaded",
    )

    rows = read_activity_log("scope1", "node_a", "host_pid")
    assert len(rows) == 4
    cats = [r["category"] for r in rows]
    assert cats == ["input", "output", "tool", "skill_load"]

    tools, skills = aggregate_tools_and_skills(rows)
    assert "read_file" in tools
    assert any(s["skill"] == "whalecloud-dev-tool-doc-generate" and s["kind"] == "load" for s in skills)


def test_skill_exec_category_and_labels(activity_work):
    binding = resolve_binding_for_profile("scope1", "node_a", "host_pid")
    record_skill(
        binding,
        skill_name="my-skill",
        skill_tool="run_skill_script",
        script_name="generate.py",
        result_preview="ok",
    )
    row = read_activity_log("scope1", "node_a", "host_pid")[0]
    assert row["category"] == "skill_exec"
    assert row["category_label"] == "执行技能脚本"
    enriched = enrich_display(row)
    assert enriched["category_label"] == "执行技能脚本"


def test_enrich_display_legacy_skill_category(activity_work):
    legacy = {
        "category": "skill",
        "skill_tool": "get_skill_info",
        "skill_name": "doc-skill",
    }
    enriched = enrich_display(legacy)
    assert enriched["category"] == "skill_load"
    assert enriched["category_label"] == "加载技能说明"


def test_enrich_display_legacy_todo_blocked_skill_load():
    legacy = {
        "category": "skill_load",
        "skill_tool": "get_skill_info",
        "skill_name": "doc-skill",
        "result_preview": "⚠️ 建议先创建 Todo！\n请先调用 create_todo",
        "success": True,
    }
    enriched = enrich_display(legacy)
    assert enriched["category"] == "skill_load_blocked"
    assert enriched["category_label"] == "技能加载被拦截"
    assert enriched["success"] is False


def test_infer_tool_success_run_skill_script_failure():
    assert infer_tool_success(
        "run_skill_script",
        "❌ 脚本执行失败:\nno executable scripts",
        True,
    ) is False
    assert infer_tool_success("run_skill_script", "✅ 脚本执行成功:\nok", True) is True


def test_try_record_skill_tool_skips_duplicate_tool_row(activity_work, monkeypatch):
    agent = MagicMock()
    agent._org_context = True
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    try_record_tool_from_agent(
        agent,
        tool_name="get_skill_info",
        tool_input={"skill_name": "whalecloud-dev-tool-doc-generate"},
        result_preview="**脚本**: instruction-only (no executable scripts)\nbody",
        success=True,
        duration_ms=10,
    )
    rows = read_activity_log("scope1", "node_a", "host_pid")
    assert len(rows) == 1
    assert rows[0]["category"] == "skill_load"
    assert rows[0]["skill_name"] == "whalecloud-dev-tool-doc-generate"
    assert rows[0]["category_label"] == "加载技能说明"


def test_executing_skill_id_on_context_tools(activity_work):
    agent = MagicMock()
    agent._org_context = True
    agent._rd_meeting_executing_skill = "whalecloud-dev-tool-doc-generate"
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    try_record_tool_from_agent(
        agent,
        tool_name="run_shell",
        tool_input={"command": "python gen.py"},
        result_preview="exit 0",
        success=True,
        duration_ms=50,
    )
    rows = read_activity_log("scope1", "node_a", "host_pid")
    assert len(rows) == 1
    assert rows[0]["category"] == "tool"
    assert rows[0]["executing_skill_id"] == "whalecloud-dev-tool-doc-generate"

    tools, skills = aggregate_tools_and_skills(rows)
    assert skills[0]["kind"] == "instruction"
    assert skills[0]["skill"] == "whalecloud-dev-tool-doc-generate"


def test_run_skill_script_failure_records_success_false(activity_work):
    agent = MagicMock()
    agent._org_context = True
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    try_record_tool_from_agent(
        agent,
        tool_name="run_skill_script",
        tool_input={"skill_name": "doc-skill", "script_name": "generate.py"},
        result_preview="❌ 脚本执行失败:\ninstruction-only",
        success=True,
        duration_ms=20,
    )
    row = read_activity_log("scope1", "node_a", "host_pid")[0]
    assert row["category"] == "skill_exec"
    assert row["success"] is False


def test_instruction_only_load_sets_executing_skill(activity_work):
    agent = MagicMock()
    agent._org_context = True
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    try_record_tool_from_agent(
        agent,
        tool_name="get_skill_info",
        tool_input={"skill_name": "doc-skill"},
        result_preview="instruction-only (no executable scripts)",
        success=True,
        duration_ms=5,
    )
    assert agent._rd_meeting_executing_skill == "doc-skill"

    try_record_tool_from_agent(
        agent,
        tool_name="run_shell",
        tool_input={"command": "echo hi"},
        result_preview="hi",
        success=True,
        duration_ms=5,
    )
    row = read_activity_log("scope1", "node_a", "host_pid")[-1]
    assert row.get("executing_skill_id") == "doc-skill"


def test_run_skill_script_clears_executing_skill(activity_work):
    agent = MagicMock()
    agent._org_context = True
    agent._rd_meeting_executing_skill = "doc-skill"
    agent._rd_meeting_executing_script = "instruction-only"
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    try_record_tool_from_agent(
        agent,
        tool_name="run_skill_script",
        tool_input={"skill_name": "doc-skill", "script_name": "x.py"},
        result_preview="❌ fail",
        success=True,
        duration_ms=5,
    )
    assert agent._rd_meeting_executing_skill == ""
    assert agent._rd_meeting_executing_script == ""


def test_todo_block_records_skill_load_blocked(activity_work):
    agent = MagicMock()
    agent._org_context = True
    agent._rd_meeting_executing_skill = ""
    agent._rd_meeting_executing_script = ""
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    preview = (
        "⚠️ **这是一个多步骤任务，建议先创建 Todo！**\n\n"
        "请先调用 `create_todo` 工具创建任务计划，然后再执行具体操作。"
    )
    try_record_tool_from_agent(
        agent,
        tool_name="get_skill_info",
        tool_input={"skill_name": "whalecloud-dev-tool-requirement-clarify"},
        result_preview=preview,
        success=True,
        duration_ms=2,
    )
    rows = read_activity_log("scope1", "node_a", "host_pid")
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "skill_load_blocked"
    assert row["success"] is False
    assert row["skill_name"] == "whalecloud-dev-tool-requirement-clarify"
    assert row["category_label"] == "技能加载被拦截"
    assert agent._rd_meeting_executing_skill == ""
    assert agent._rd_meeting_executing_script == ""
    enriched = enrich_display(row)
    assert enriched["category_label"] == "技能加载被拦截"
    assert enriched["category_label"] != "加载技能说明"


def test_is_todo_block_preview_and_infer_failure():
    preview = "请先调用 create_todo\n建议先创建 Todo"
    assert is_todo_block_preview(preview) is True
    assert infer_tool_success("get_skill_info", preview, True) is False


def test_skill_exec_display_title(activity_work):
    binding = resolve_binding_for_profile("scope1", "node_a", "host_pid")
    record_skill(
        binding,
        skill_name="doc-skill",
        skill_tool="run_skill_script",
        script_name="generate.py",
        result_preview="ok",
    )
    row = enrich_display(read_activity_log("scope1", "node_a", "host_pid")[0])
    assert row["display_title"] == "doc-skill"
    assert "chain_label" not in row
    assert row["category_label"] == "执行技能脚本"


def test_instruction_only_chain_on_context_tools(activity_work):
    agent = MagicMock()
    agent._org_context = True
    set_agent_activity_binding(
        agent,
        scope_id="scope1",
        node_id="node_a",
        profile_id="host_pid",
        host_profile_id="host_pid",
        role="host",
        room_id="room1",
    )
    try_record_tool_from_agent(
        agent,
        tool_name="get_skill_info",
        tool_input={"skill_name": "doc-skill"},
        result_preview="instruction-only (no executable scripts)",
        success=True,
        duration_ms=5,
    )
    assert agent._rd_meeting_executing_script == "instruction-only"

    try_record_tool_from_agent(
        agent,
        tool_name="run_shell",
        tool_input={"command": "echo hi"},
        result_preview="hi",
        success=True,
        duration_ms=5,
    )
    row = read_activity_log("scope1", "node_a", "host_pid")[-1]
    assert row.get("executing_skill_id") == "doc-skill"
    assert row.get("executing_script_name") == "instruction-only"
    assert row.get("display_title") == "doc-skill"
    assert "chain_label" not in row

    tools, skills = aggregate_tools_and_skills(read_activity_log("scope1", "node_a", "host_pid"))
    instruction = [s for s in skills if s["kind"] == "instruction"]
    assert instruction
    assert instruction[0]["script"] == "instruction-only"


def test_record_skill_load_blocked_direct(activity_work):
    binding = resolve_binding_for_profile("scope1", "node_a", "host_pid")
    record_skill_load_blocked(
        binding,
        skill_name="my-skill",
        skill_tool="get_skill_info",
        result_preview="建议先创建 Todo",
    )
    row = read_activity_log("scope1", "node_a", "host_pid")[0]
    assert row["category"] == "skill_load_blocked"
    assert row["success"] is False


def test_activity_jsonl_on_disk(activity_work):
    binding = resolve_binding_for_profile("s", "n1", "worker_1")
    record_tool(binding, tool_name="run_shell", result_preview="exit 0")
    path = activity_work / "n1" / "worker_1" / "activity.jsonl"
    assert path.is_file()
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["category"] == "tool"
    assert line["tool_name"] == "run_shell"
    assert line["seq"] == 1


def test_record_llm_usage_and_aggregate(activity_work):
    from synapse.rd_meeting.agent_activity import (
        aggregate_llm_tokens,
        compute_activity_duration_seconds,
        record_llm_usage,
        resolve_binding_for_profile,
    )

    binding = resolve_binding_for_profile("scope1", "node_a", "host_pid", host_profile_id="host_pid")
    record_llm_usage(
        binding,
        input_tokens=100,
        output_tokens=40,
        usage_scene="rd_meeting_scope1_req",
        ts="2026-05-26T10:00:00",
    )
    record_llm_usage(
        binding,
        input_tokens=50,
        output_tokens=10,
        usage_scene="rd_meeting_scope1_node_review",
        ts="2026-05-26T10:05:00",
    )
    rows = read_activity_log("scope1", "node_a", "host_pid")
    assert aggregate_llm_tokens(rows) == 140
    assert compute_activity_duration_seconds(rows) == 300


def test_mark_llm_call_start_records_duration(activity_work):
    from synapse.rd_meeting.agent_activity import (
        enrich_display,
        mark_llm_call_start,
        resolve_binding_for_profile,
        try_record_llm_usage_from_agent,
    )

    agent = MagicMock()
    agent._org_context = True
    agent._rd_meeting_activity = {
        "scope_id": "scope1",
        "node_id": "node_a",
        "profile_id": "host_pid",
        "host_profile_id": "host_pid",
        "role": "host",
        "room_id": "room1",
    }

    mark_llm_call_start(agent)
    time.sleep(0.02)
    try_record_llm_usage_from_agent(
        agent,
        input_tokens=120,
        output_tokens=30,
        usage_scene="rd_meeting_scope1_req",
        model="test-model",
    )

    row = enrich_display(read_activity_log("scope1", "node_a", "host_pid")[0])
    assert row["category"] == "llm_usage"
    assert row["input_tokens"] == 120
    assert row["output_tokens"] == 30
    assert row["total_tokens"] == 150
    assert row.get("duration_ms", 0) >= 10
    assert row["presentation_tier"] == "secondary"
    assert "输入 120 token" in row["summary"]

    tool_row = enrich_display(
        {
            "category": "tool",
            "tool_name": "grep",
            "success": True,
        }
    )
    assert tool_row["presentation_tier"] == "primary"


def test_resolve_agent_billable_tokens_prefers_last_usage_summary():
    agent = SimpleNamespace(
        _last_usage_summary={"total_tokens": 420, "input_tokens": 100, "output_tokens": 320},
        last_usage={"total_tokens": 999},
    )
    assert resolve_agent_billable_tokens(agent) == 420


def test_resolve_agent_billable_tokens_falls_back_to_last_usage_for_tests():
    agent = SimpleNamespace(last_usage={"total_tokens": 88})
    assert resolve_agent_billable_tokens(agent) == 88


def test_resolve_agent_billable_tokens_returns_zero_when_missing():
    assert resolve_agent_billable_tokens(SimpleNamespace()) == 0
    assert resolve_agent_billable_tokens(SimpleNamespace(_last_usage_summary={})) == 0


def test_reasoning_engine_records_worker_llm_usage_to_activity(activity_work):
    """子智能体走 ReasoningEngine 时也应写入 activity.jsonl（节点确认总结依赖此数据）。"""
    from synapse.core.reasoning_engine import ReasoningEngine

    agent = MagicMock()
    agent._org_context = True
    agent._rd_meeting_activity = {
        "scope_id": "scope1",
        "node_id": "node_a",
        "profile_id": "worker_1",
        "host_profile_id": "host_pid",
        "role": "worker",
        "room_id": "room1",
    }
    tool_executor = MagicMock()
    tool_executor._agent_ref = agent

    engine = ReasoningEngine(
        brain=MagicMock(),
        tool_executor=tool_executor,
        context_manager=MagicMock(),
        response_handler=MagicMock(),
        agent_state=MagicMock(),
    )
    engine._record_meeting_llm_usage(
        input_tokens=200,
        output_tokens=50,
        model="worker-model",
    )

    rows = read_activity_log("scope1", "node_a", "worker_1")
    assert len(rows) == 1
    assert rows[0]["category"] == "llm_usage"
    assert rows[0]["total_tokens"] == 250
    assert rows[0]["usage_scene"] == "rd_meeting_scope1_node_a"
