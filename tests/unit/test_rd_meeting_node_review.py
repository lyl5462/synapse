"""NODE_REVIEW payload 装配 + 落盘 + 安全读文件。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from synapse.rd_meeting.node_review import (
    aggregate_node_metrics,
    build_node_review_payload,
    collect_artifact_files,
    load_node_review,
    read_artifact_file,
    save_node_review,
)
from synapse.rd_meeting.paths import (
    agent_node_dir,
    archive_root,
    meeting_pipeline_path,
    scope_dir,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    # 稳定的 display_name
    names = {"default": "小鲸", "doc-gen": "文档专家", "code-explorer": "代码侦探"}

    def _fake(pid):
        if pid in names:
            return SimpleNamespace(
                id=pid,
                name=names[pid],
                get_display_name=lambda lang="zh": names[pid],
                skills=[],
            )
        return None

    monkeypatch.setattr("synapse.rd_meeting.room_skill.resolve_agent_profile", _fake)
    # room_history 路径锁定到 tmp，避免污染 ~/.synapse
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda sid: scope_dir(sid) / "room_history.jsonl",
    )
    return tmp_path


def _fake_host_agent(messages, *, tokens=300, tools=("shell",), skills=()):
    ctx = SimpleNamespace(messages=list(messages))
    task = SimpleNamespace(tools_executed=list(tools), skills_executed=list(skills))
    state = SimpleNamespace(current_task=task)
    return SimpleNamespace(_context=ctx, agent_state=state, last_usage={"total_tokens": tokens})


class _FakePool:
    def __init__(self, mapping):
        self._m = mapping

    def get_existing(self, sid, profile_id=None):
        if profile_id is not None:
            return self._m.get(f"{sid}::{profile_id}")
        return self._m.get(sid)


class _FakeOrch:
    def __init__(self, sub_states):
        self._states = sub_states

    def get_sub_agent_states(self, sid):
        return list(self._states)


def test_aggregate_metrics_counts_delegations_and_workers(tmp_path):
    scope = "scope-A"
    room = "room-A"
    host_messages = [
        {"role": "user", "content": "请开始"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "delegate_to_agent", "input": {"to": "doc-gen"}},
                {"type": "tool_use", "name": "delegate_to_agent", "input": {"to": "code-explorer"}},
                {
                    "type": "tool_use",
                    "name": "delegate_parallel",
                    "input": {"tasks": [{"to": "doc-gen"}, {"to": "code-explorer"}]},
                },
            ],
        },
    ]
    host_agent = _fake_host_agent(host_messages, tokens=500, tools=["shell", "shell", "read_file"])
    pool = _FakePool({f"rd_meeting:{room}:host": host_agent})
    orch = _FakeOrch(
        [
            {"profile_id": "doc-gen", "tools_executed": ["run_skill_script"], "skills_executed": [{"skill": "doc-generate"}], "tokens_used": 800},
            {"profile_id": "doc-gen", "tools_executed": ["shell"], "tokens_used": 200},
            {"profile_id": "code-explorer", "tools_executed": ["grep", "read_file"], "tokens_used": 400},
        ]
    )

    metrics = aggregate_node_metrics(
        scope_id=scope,
        room_id=room,
        node_id="req_clarify",
        binding={
            "host_profile_id": "default",
            "worker_profile_ids": ["doc-gen", "code-explorer"],
        },
        agent_pool=pool,
        orchestrator=orch,
        tokens_used=1500,
        duration_seconds=45,
    )

    assert metrics.host.profile_id == "default"
    assert metrics.host.display_name == "小鲸"
    # 2 个 delegate_to_agent + 2 个 delegate_parallel.tasks
    assert metrics.host.delegations == 4
    assert metrics.host.tool_calls == 3
    # tools 聚合并按降序
    assert metrics.host.tools[0]["name"] == "shell"
    assert metrics.host.tools[0]["count"] == 2

    pids = [w.profile_id for w in metrics.workers]
    assert pids == ["doc-gen", "code-explorer"]
    doc = metrics.workers[0]
    assert doc.delegations == 2  # 两条 sub_agent_state
    assert doc.tokens == 1000
    assert doc.tool_calls == 2

    assert metrics.delegation_total == 4
    assert metrics.tool_call_total == metrics.host.tool_calls + sum(w.tool_calls for w in metrics.workers)
    assert metrics.node_duration_seconds == 45


def test_aggregate_worker_tools_from_pool_with_host_session_fallback(tmp_path):
    """Worker 委派任务注册在 host session；sub_agent_states 截断时仍应从池化实例读全量 tools。"""
    scope = "scope-pool"
    room = "room-pool"
    host_sid = f"rd_meeting:{room}:host"
    worker_sid = f"rd_meeting:{room}:doc-gen"

    # Task 挂在 host session（与 orchestrator._call_agent 一致）
    worker_task = SimpleNamespace(
        tools_executed=["grep", "read_file", "run_skill_script", "grep", "write_file"],
        skills_executed=[{"skill": "doc-generate", "tool": "run_skill_script"}],
        status=SimpleNamespace(value="completed"),
        iteration=3,
        session_id=host_sid,
        task_id="abc12345",
        description="",
        usage_scene="",
    )
    worker_state = SimpleNamespace(
        current_task=worker_task,
        get_task_for_session=lambda sid: worker_task if sid == host_sid else None,
    )
    worker_agent = SimpleNamespace(
        _context=SimpleNamespace(messages=[]),
        agent_state=worker_state,
        last_usage={"total_tokens": 1200},
    )

    pool = _FakePool({worker_sid: worker_agent})
    # orchestrator 只有截断的 2 条工具名
    orch = _FakeOrch(
        [{"profile_id": "doc-gen", "tools_executed": ["write_file"], "tools_total": 5, "tokens_used": 100}]
    )

    metrics = aggregate_node_metrics(
        scope_id=scope,
        room_id=room,
        node_id="req_clarify",
        binding={"host_profile_id": "default", "worker_profile_ids": ["doc-gen"]},
        agent_pool=pool,
        orchestrator=orch,
    )

    doc = metrics.workers[0]
    assert doc.tool_calls == 5
    assert doc.tokens == 1200
    names = {b["name"]: b["count"] for b in doc.tools}
    assert names.get("grep") == 2
    assert names.get("write_file") == 1


def test_collect_artifact_files_lists_md_and_others(tmp_path):
    scope = "scope-B"
    stage_id = 2
    node_id = "req_clarify"
    base = archive_root(scope) / str(stage_id) / node_id
    base.mkdir(parents=True)
    (base / "需求澄清.md").write_text("# Hello", encoding="utf-8")
    (base / "data.json").write_text('{"k": 1}', encoding="utf-8")

    files = collect_artifact_files(scope, stage_id, node_id)
    names = sorted(f.name for f in files)
    assert names == ["data.json", "需求澄清.md"]
    md = next(f for f in files if f.name == "需求澄清.md")
    assert md.ext == ".md"
    assert md.relative_path.endswith(f"archive/{stage_id}/{node_id}/需求澄清.md")
    assert md.size > 0


def test_read_artifact_file_blocks_path_escape(tmp_path):
    scope = "scope-C"
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")
    # 越权路径：跳出 scope_dir
    rel = "../../../secret.txt"
    assert read_artifact_file(scope, rel) is None


def test_read_artifact_file_reads_md(tmp_path):
    scope = "scope-D"
    base = archive_root(scope) / "2" / "req_clarify"
    base.mkdir(parents=True)
    (base / "x.md").write_text("# X", encoding="utf-8")
    res = read_artifact_file(scope, "archive/2/req_clarify/x.md")
    assert res is not None
    content, ext = res
    assert content == "# X"
    assert ext == ".md"


@pytest.mark.asyncio
async def test_build_and_save_payload_without_llm(tmp_path):
    scope = "scope-E"
    room = "room-E"
    stage_id = 2
    node_id = "req_clarify"

    # 1) host conversation 文件（让 fallback 摘要有内容）
    host_dir = agent_node_dir(scope, "default", node_id)
    host_dir.mkdir(parents=True)
    (host_dir / "conversation.jsonl").write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in [
                {"index": 0, "role": "user", "speaker": {"kind": "user", "display_name": "用户"}, "text": "请澄清需求"},
                {"index": 1, "role": "assistant", "speaker": {"kind": "host", "display_name": "小鲸"}, "text": "我来收集事实"},
            ]
        ),
        encoding="utf-8",
    )

    # 2) 归档文件
    base = archive_root(scope) / str(stage_id) / node_id
    base.mkdir(parents=True)
    (base / "需求澄清.md").write_text("# 交付结论\nOK", encoding="utf-8")

    # 3) 初始化 pipeline.json
    pipe_path = meeting_pipeline_path(scope)
    pipe_path.parent.mkdir(parents=True, exist_ok=True)
    pipe_path.write_text(
        json.dumps(
            {"schema_version": 1, "scope_id": scope, "context": {}, "flow_step": "waiting"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    host_agent = _fake_host_agent(
        [
            {"role": "user", "content": "x"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "delegate_to_agent", "input": {}}],
            },
        ],
        tokens=600,
        tools=("shell",),
    )
    pool = _FakePool({f"rd_meeting:{room}:host": host_agent})

    payload = await build_node_review_payload(
        scope_type="demand",
        scope_id=scope,
        room_id=room,
        node_id=node_id,
        binding={
            "host_profile_id": "default",
            "worker_profile_ids": [],
            "node_name": "需求澄清",
            "node_intent": "把需求拆清楚",
        },
        report_body="# 交付结论\nDone",
        tokens_used=600,
        duration_seconds=30,
        stage_id=stage_id,
        agent_pool=pool,
        orchestrator=None,
        use_llm_summary=False,  # 强制走 fallback，避免触发真实 LLM
    )

    assert payload["node_id"] == node_id
    assert payload["node_name"] == "需求澄清"
    assert payload["stage_id"] == stage_id
    assert payload["metrics"]["host"]["delegations"] == 1
    assert payload["metrics"]["node_duration_seconds"] == 30
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["name"] == "需求澄清.md"
    # fallback 摘要不会调用 LLM
    summaries = payload["summaries"]
    assert len(summaries) == 1  # 仅 host（没有 worker）
    assert summaries[0]["role"] == "host"
    assert summaries[0]["source"] == "fallback"
    assert "小鲸" in summaries[0]["display_name"]

    # 落盘
    save_node_review(scope, node_id, payload)
    loaded = load_node_review(scope, node_id)
    assert loaded is not None
    assert loaded["node_id"] == node_id
    assert loaded["metrics"]["host"]["delegations"] == 1
