"""pipeline._step_node_finish：dump trace + 严格冷启动 worker 上下文。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from synapse.rd_meeting import pipeline as pipeline_mod
from synapse.rd_meeting.paths import agent_node_dir


@pytest.fixture(autouse=True)
def _isolate_work_root(monkeypatch, tmp_path):
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    # display_name 解析回到 profile_id，避免依赖真实 profile 仓
    monkeypatch.setattr(
        "synapse.rd_meeting.room_skill.resolve_agent_profile",
        lambda pid: None,
    )
    return tmp_path


def _fake_agent(messages):
    ctx = SimpleNamespace(messages=list(messages))
    task = SimpleNamespace(tools_executed=["shell"], skills_executed=[])
    state = SimpleNamespace(current_task=task)
    return SimpleNamespace(_context=ctx, agent_state=state, last_usage={"total_tokens": 100})


class _FakePool:
    def __init__(self, mapping):
        self._m = mapping

    def get_existing(self, session_id, profile_id=None):
        # 兼容 (sid, pid) 调用与 (sid) 调用
        if profile_id is not None:
            key = f"{session_id}::{profile_id}"
            return self._m.get(key)
        return self._m.get(session_id)


def test_cleanup_dumps_and_clears_host_and_workers(tmp_path):
    scope = "scope-X"
    room = "room-X"
    last_node = "req_clarify"
    host_agent = _fake_agent(
        [
            {"role": "user", "content": "请开始本节点"},
            {"role": "assistant", "content": "好的，我来委派"},
        ]
    )
    worker_agent = _fake_agent(
        [
            {"role": "user", "content": "host 派单内容"},
            {"role": "assistant", "content": "我已经做完了"},
        ]
    )
    pool = _FakePool(
        {
            f"rd_meeting:{room}:host": host_agent,
            f"rd_meeting:{room}:doc-gen": worker_agent,
        }
    )

    pipeline_mod._cleanup_agents_for_finished_node(
        scope_id=scope,
        room_id=room,
        agent_pool=pool,
        last_node_id=last_node,
        last_binding={
            "host_profile_id": "default",
            "worker_profile_ids": ["doc-gen"],
        },
    )

    # 1) host + worker 上下文均清空
    assert host_agent._context.messages == []
    assert host_agent.agent_state.current_task is None
    assert worker_agent._context.messages == []
    assert worker_agent.agent_state.current_task is None

    # 2) trace 已落盘
    host_conv = agent_node_dir(scope, "default", last_node) / "conversation.jsonl"
    worker_conv = agent_node_dir(scope, "doc-gen", last_node) / "conversation.jsonl"
    assert host_conv.is_file() and host_conv.read_text("utf-8").strip()
    assert worker_conv.is_file() and worker_conv.read_text("utf-8").strip()
    worker_rows = [json.loads(line) for line in worker_conv.read_text("utf-8").splitlines()]
    # worker 视角下首条 user 标注为 host 派单
    assert worker_rows[0]["speaker"]["kind"] == "host"
    assert worker_rows[0]["speaker"]["profile_id"] == "default"


def test_cleanup_without_pool_is_noop():
    # 未提供 agent_pool / room_id 时直接返回，不抛异常
    pipeline_mod._cleanup_agents_for_finished_node(
        scope_id="s",
        room_id="",
        agent_pool=None,
        last_node_id="n",
        last_binding={"host_profile_id": "default", "worker_profile_ids": []},
    )


def test_cleanup_without_binding_only_clears_host(tmp_path):
    scope = "scope-Y"
    room = "room-Y"
    last_node = "req_clarify"
    host_agent = _fake_agent([{"role": "assistant", "content": "hello"}])
    other_worker = _fake_agent([{"role": "assistant", "content": "stale"}])
    pool = _FakePool(
        {
            f"rd_meeting:{room}:host": host_agent,
            f"rd_meeting:{room}:doc-gen": other_worker,
        }
    )

    # binding 缺失：仅按 host_pid="" 走 host 分支；worker 不被遍历
    pipeline_mod._cleanup_agents_for_finished_node(
        scope_id=scope,
        room_id=room,
        agent_pool=pool,
        last_node_id=last_node,
        last_binding=None,
    )
    # host_pid 为空时 dump 跳过；reset 仍以 'default' 为 fallback 写一次 event
    assert host_agent._context.messages == []
    # worker 未在 binding 列表里 → 不动
    assert other_worker._context.messages == [{"role": "assistant", "content": "stale"}]
