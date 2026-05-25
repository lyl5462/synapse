"""研发会议室 agent_trace 沉淀 + 严格冷启动行为。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from synapse.rd_meeting.agent_trace import (
    Speaker,
    append_event,
    dump_agent_node_trace,
    normalize_speaker,
    reset_agent_node_context,
    write_agent_meta,
)
from synapse.rd_meeting.paths import agent_node_dir, agent_sop_profile_dir


@pytest.fixture(autouse=True)
def _patch_work_root(monkeypatch, tmp_path):
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    # display_name 默认查 profile 模块；这里给个稳定 stub
    fake_names = {
        "default": "小鲸",
        "doc-gen": "文档专家",
        "code-explorer": "代码侦探",
    }

    def _fake_resolve(pid):
        if pid in fake_names:
            return SimpleNamespace(
                id=pid,
                name=fake_names[pid],
                get_display_name=lambda lang="zh": fake_names[pid],
                skills=["s1", "s2"],
            )
        return None

    monkeypatch.setattr(
        "synapse.rd_meeting.room_skill.resolve_agent_profile",
        _fake_resolve,
    )
    return tmp_path


def test_normalize_speaker_host_user_is_real_user():
    sp = normalize_speaker(
        role="user",
        self_profile_id="default",
        host_profile_id="default",
        worker_profile_ids=["doc-gen"],
    )
    assert sp.kind == "user"
    assert sp.display_name == "用户"


def test_normalize_speaker_worker_user_is_host_delegation():
    sp = normalize_speaker(
        role="user",
        self_profile_id="doc-gen",
        host_profile_id="default",
        worker_profile_ids=["doc-gen"],
    )
    assert sp.kind == "host"
    assert sp.profile_id == "default"
    assert "派单" in sp.display_name
    assert "小鲸" in sp.display_name


def test_normalize_speaker_assistant_to_coworker():
    sp = normalize_speaker(
        role="assistant",
        self_profile_id="doc-gen",
        host_profile_id="default",
        worker_profile_ids=["doc-gen"],
    )
    assert sp.kind == "coworker"
    assert sp.profile_id == "doc-gen"
    assert sp.display_name == "文档专家"


def test_normalize_speaker_assistant_host_self():
    sp = normalize_speaker(
        role="assistant",
        self_profile_id="default",
        host_profile_id="default",
        worker_profile_ids=[],
    )
    assert sp.kind == "host"
    assert sp.display_name == "小鲸"


def test_normalize_speaker_system_and_tool():
    assert normalize_speaker(
        role="system", self_profile_id="x", host_profile_id="default"
    ) == Speaker(kind="system", display_name="系统")
    assert normalize_speaker(
        role="tool", self_profile_id="x", host_profile_id="default"
    ) == Speaker(kind="tool", display_name="工具")


def _fake_agent(messages, *, tools=None, skills=None, last_usage=None):
    ctx = SimpleNamespace(messages=list(messages))
    task = SimpleNamespace(
        tools_executed=list(tools or []),
        skills_executed=list(skills or []),
    )
    state = SimpleNamespace(current_task=task)
    return SimpleNamespace(
        _context=ctx,
        agent_state=state,
        last_usage=last_usage or {},
    )


def test_dump_agent_node_trace_writes_conversation_and_tools(tmp_path):
    scope = "scope-A"
    pid = "doc-gen"
    nid = "req_clarify"
    agent = _fake_agent(
        [
            {"role": "user", "content": "请按 SKILL 输出问卷"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "好的"},
                    {"type": "tool_use", "id": "t1", "name": "run_skill_script", "input": {"x": 1}},
                ],
            },
            {
                "role": "tool",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                ],
            },
        ],
        tools=["shell", "run_skill_script"],
        skills=[{"skill": "doc-generate", "tool": "run_skill_script", "script": "render.py"}],
        last_usage={"total_tokens": 1234},
    )

    out = dump_agent_node_trace(
        scope,
        pid,
        nid,
        agent=agent,
        host_profile_id="default",
        worker_profile_ids=["doc-gen"],
        role="worker",
    )

    assert out is not None and out.exists()
    base = agent_node_dir(scope, pid, nid)
    assert base.is_dir()

    rows = [json.loads(line) for line in (base / "conversation.jsonl").read_text("utf-8").splitlines()]
    assert len(rows) == 3
    # worker 视角下首条 user 实际来自 host
    assert rows[0]["speaker"]["kind"] == "host"
    assert rows[0]["speaker"]["profile_id"] == "default"
    # 自己 assistant 是 coworker
    assert rows[1]["speaker"]["kind"] == "coworker"
    assert rows[1]["speaker"]["profile_id"] == "doc-gen"
    assert rows[1]["tool_uses"][0]["name"] == "run_skill_script"
    # 工具结果
    assert rows[2]["speaker"]["kind"] == "tool"
    assert rows[2]["tool_results"][0]["tool_use_id"] == "t1"

    tools_payload = json.loads((base / "tools.json").read_text("utf-8"))
    assert tools_payload["tools_executed"] == ["shell", "run_skill_script"]
    skills_payload = json.loads((base / "skills.json").read_text("utf-8"))
    assert skills_payload["skills_executed"][0]["skill"] == "doc-generate"
    usage_payload = json.loads((base / "usage.json").read_text("utf-8"))
    assert usage_payload["last_usage"]["total_tokens"] == 1234

    events = [
        json.loads(line)
        for line in (base / "events.jsonl").read_text("utf-8").splitlines()
    ]
    assert any(e["event"] == "dumped" for e in events)


def test_reset_agent_node_context_clears_messages_and_task(tmp_path):
    scope = "scope-B"
    pid = "doc-gen"
    nid = "req_clarify"
    agent = _fake_agent(
        [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "y"},
        ],
        tools=["shell"],
    )

    reset_agent_node_context(scope, pid, nid, agent=agent, reason="unit_test")

    assert agent._context.messages == []
    assert agent.agent_state.current_task is None

    events = [
        json.loads(line)
        for line in (agent_node_dir(scope, pid, nid) / "events.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    cleared = [e for e in events if e["event"] == "cleared"]
    assert cleared and cleared[0]["detail"]["reason"] == "unit_test"


def test_write_agent_meta_persists_identity(tmp_path):
    scope = "scope-C"
    pid = "doc-gen"
    nid = "req_clarify"
    write_agent_meta(
        scope,
        pid,
        node_id=nid,
        role="worker",
        llm_endpoint="endpoint-a",
        capabilities={"skills": ["doc-generate"]},
    )
    meta = json.loads((agent_sop_profile_dir(scope, nid, pid) / "meta.json").read_text("utf-8"))
    assert meta["profile_id"] == "doc-gen"
    assert meta["display_name"] == "文档专家"
    assert meta["llm_endpoint"] == "endpoint-a"
    assert meta["capabilities"]["skills"] == ["doc-generate"]


def test_append_event_ignores_invalid_inputs(tmp_path):
    # 不应抛异常；返回 None 且不创建目录
    append_event("", "doc-gen", "n1", event="x")
    append_event("scope", "", "n1", event="x")
    # 当传入合法值时应写入
    append_event("scope-D", "doc-gen", "n1", event="spawn", detail={"k": 1})
    events_path = agent_node_dir("scope-D", "doc-gen", "n1") / "events.jsonl"
    assert events_path.is_file()
