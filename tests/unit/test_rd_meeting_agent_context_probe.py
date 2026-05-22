"""研发会议室 Agent 上下文探测。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from synapse.rd_meeting.agent_context_probe import (
    collect_meeting_agent_contexts,
    dump_meeting_agent_contexts,
    probe_pooled_agent,
)


class _FakeTask:
    task_id = "abcd1234"
    status = SimpleNamespace(value="reasoning")
    iteration = 2
    tools_executed = ["read_file"]
    description = "test task"
    usage_scene = "rd_meeting_demo"


class _FakeAgentState:
    current_task = _FakeTask()

    def get_task_for_session(self, _session_id: str):
        return self.current_task


class _FakeContext:
    system = "cached system"
    messages = [{"role": "user", "content": "hello"}]


class _FakeAgent:
    _context = _FakeContext()
    _custom_prompt_suffix = "meeting suffix"
    _preferred_endpoint = "default"
    default_cwd = "/tmp/work"
    agent_state = _FakeAgentState()
    last_usage = {"total_tokens": 42}


class _FakePoolEntry:
    def __init__(self, session_id: str, profile_id: str, agent: object):
        self.session_id = session_id
        self.profile_id = profile_id
        self.agent = agent


class _FakePool:
    def __init__(self, entries: list[_FakePoolEntry]):
        self._pool = {f"{e.session_id}::{e.profile_id}": e for e in entries}

    def get_stats(self):
        sessions: dict[str, list[dict]] = {}
        for e in self._pool.values():
            sessions.setdefault(e.session_id, []).append({"profile_id": e.profile_id})
        return {
            "sessions": [
                {"session_id": sid, "agents": agents} for sid, agents in sessions.items()
            ]
        }

    def get_existing(self, session_id: str, profile_id: str):
        entry = self._pool.get(f"{session_id}::{profile_id}")
        return entry.agent if entry else None


def test_probe_pooled_agent_extracts_context():
    agent = _FakeAgent()
    out = probe_pooled_agent(
        agent,
        session_id="rd_meeting:mr_abc:host",
        profile_id="default",
    )
    assert out["role"] == "host"
    assert out["system_prompt"] == "cached system"
    assert out["custom_prompt_suffix"] == "meeting suffix"
    assert out["messages_count"] == 1
    assert out["task"]["status"] == "reasoning"


def test_collect_meeting_agent_contexts_filters_by_room():
    pool = _FakePool(
        [
            _FakePoolEntry("rd_meeting:mr_1:host", "default", _FakeAgent()),
            _FakePoolEntry("rd_meeting:mr_1:worker-a", "worker-a", _FakeAgent()),
            _FakePoolEntry("rd_meeting:mr_2:host", "default", _FakeAgent()),
        ]
    )
    payload = collect_meeting_agent_contexts("mr_1", pool)
    assert payload["scope_id"] is None
    assert len(payload["agents"]) == 2
    roles = {a["role"] for a in payload["agents"]}
    assert roles == {"host", "worker"}


@pytest.fixture
def synapse_work_home(monkeypatch: pytest.MonkeyPatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()

    def _work_root():
        return work

    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", _work_root)
    monkeypatch.setattr("synapse.rd_meeting.agent_context_probe.scope_dir", lambda sid: work / sid)
    return work


def test_dump_meeting_agent_contexts_writes_file(synapse_work_home):
    payload = {
        "room_id": "mr_x",
        "agents": [
            {
                "profile_id": "default",
                "role": "host",
                "messages_count": 1,
                "task": {"status": "reasoning", "iteration": 1, "tools_executed": []},
            }
        ],
    }
    path = dump_meeting_agent_contexts(payload, scope_id="21880001")
    assert path.endswith(".json")
    assert (synapse_work_home / "21880001" / "debug" / "agent_contexts").is_dir()
