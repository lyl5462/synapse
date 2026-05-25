"""agent_activity：四类埋点落盘与聚合。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.agent_activity import (
    aggregate_tools_and_skills,
    read_activity_log,
    record_input,
    record_output,
    record_skill,
    record_tool,
    resolve_binding_for_profile,
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
    assert cats == ["input", "output", "tool", "skill"]

    tools, skills = aggregate_tools_and_skills(rows)
    assert "read_file" in tools
    assert any(s["skill"] == "whalecloud-dev-tool-doc-generate" for s in skills)


def test_activity_jsonl_on_disk(activity_work):
    binding = resolve_binding_for_profile("s", "n1", "worker_1")
    record_tool(binding, tool_name="run_shell", result_preview="exit 0")
    path = activity_work / "n1" / "worker_1" / "activity.jsonl"
    assert path.is_file()
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["category"] == "tool"
    assert line["tool_name"] == "run_shell"
    assert line["seq"] == 1
