"""NODE_REVIEW payload 装配 + 落盘 + 安全读文件。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from synapse.rd_meeting.node_review import (
    _extract_llm_text,
    _is_invalid_summary_response,
    build_activity_summary_context,
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
    stage_name = "需求设计"
    node_id = "req_clarify"
    base = archive_root(scope) / stage_name / node_id
    base.mkdir(parents=True)
    (base / "需求澄清.md").write_text("# Hello", encoding="utf-8")
    (base / "data.json").write_text('{"k": 1}', encoding="utf-8")

    files = collect_artifact_files(scope, stage_name, node_id)
    names = sorted(f.name for f in files)
    assert names == ["data.json", "需求澄清.md"]
    md = next(f for f in files if f.name == "需求澄清.md")
    assert md.ext == ".md"
    assert md.relative_path.endswith(f"archive/{stage_name}/{node_id}/需求澄清.md")
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
    base = archive_root(scope) / "需求设计" / "req_clarify"
    base.mkdir(parents=True)
    (base / "x.md").write_text("# X", encoding="utf-8")
    res = read_artifact_file(scope, "archive/需求设计/req_clarify/x.md")
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

    # 1) host activity（无 activity 则不生成摘要）
    host_dir = agent_node_dir(scope, "default", node_id)
    host_dir.mkdir(parents=True)
    (host_dir / "activity.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "category": "tool",
                "tool_name": "delegate_to_agent",
                "tool_input": {"to": "doc-gen", "message": "整理需求"},
                "success": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
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
    base = archive_root(scope) / "需求设计" / node_id
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


@pytest.mark.asyncio
async def test_aggregate_activity_summary_host_and_worker(tmp_path):
    scope = "scope-act"
    node_id = "req_clarify"
    node_name = "需求澄清"
    host_dir = agent_node_dir(scope, "default", node_id)
    host_dir.mkdir(parents=True)

    activity_lines = [
        {
            "seq": 1,
            "category": "input",
            "source": "human",
            "input_kind": "questionnaire_feedback",
            "title": "人类问卷反馈",
            "summary": "请补充边界条件",
        },
        {
            "seq": 2,
            "category": "tool",
            "tool_name": "delegate_to_agent",
            "tool_input": {"to": "doc-gen", "message": "整理需求澄清文档"},
            "success": True,
        },
        {
            "seq": 3,
            "category": "tool",
            "tool_name": "run_shell",
            "success": True,
        },
        {
            "seq": 4,
            "category": "skill_load",
            "skill_name": "whalecloud-dev-tool-requirement-clarify",
            "skill_tool": "get_skill_info",
            "success": True,
        },
    ]
    (host_dir / "activity.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in activity_lines),
        encoding="utf-8",
    )

    ctx = build_activity_summary_context(
        scope, "default", node_id, role="host", node_name=node_name
    )
    assert ctx is not None
    assert "需求澄清" in ctx
    assert "与研发人员（人类）交互：1 次" in ctx
    assert "委派协作智能体：共 1 次" in ctx
    assert "doc-gen" in ctx
    assert "`run_shell`：1 次" in ctx
    assert "whalecloud-dev-tool-requirement-clarify" in ctx
    assert "activity.jsonl" not in ctx
    assert "conversation.jsonl" not in ctx

    worker_dir = agent_node_dir(scope, "doc-gen", node_id)
    worker_dir.mkdir(parents=True)
    (worker_dir / "activity.jsonl").write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in [
                {
                    "seq": 1,
                    "category": "input",
                    "input_kind": "delegation",
                    "title": "收到委派请求",
                    "summary": "整理需求澄清文档",
                },
                {
                    "seq": 2,
                    "category": "output",
                    "output_kind": "delegation_feedback",
                    "title": "协作反馈",
                    "summary": "已完成文档整理",
                    "success": True,
                },
                {
                    "seq": 3,
                    "category": "tool",
                    "tool_name": "grep",
                    "success": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    worker_ctx = build_activity_summary_context(
        scope, "doc-gen", node_id, role="worker", node_name=node_name
    )
    assert worker_ctx is not None
    assert "收到委派工作：1 次" in worker_ctx
    assert "已完成文档整理" in worker_ctx
    assert "`grep`：1 次" in worker_ctx


@pytest.mark.asyncio
async def test_build_payload_skips_worker_without_activity(tmp_path):
    scope = "scope-skip"
    room = "room-skip"
    node_id = "req_clarify"
    host_dir = agent_node_dir(scope, "default", node_id)
    host_dir.mkdir(parents=True)
    (host_dir / "activity.jsonl").write_text(
        json.dumps({"seq": 1, "category": "output", "title": "节点产出", "summary": "OK"}, ensure_ascii=False),
        encoding="utf-8",
    )

    pipe_path = meeting_pipeline_path(scope)
    pipe_path.parent.mkdir(parents=True, exist_ok=True)
    pipe_path.write_text(
        json.dumps({"schema_version": 1, "scope_id": scope, "context": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = await build_node_review_payload(
        scope_type="demand",
        scope_id=scope,
        room_id=room,
        node_id=node_id,
        binding={
            "host_profile_id": "default",
            "worker_profile_ids": ["doc-gen", "code-explorer"],
            "node_name": "需求澄清",
        },
        report_body="# OK",
        tokens_used=10,
        duration_seconds=1,
        stage_id=2,
        agent_pool=None,
        orchestrator=None,
        use_llm_summary=False,
    )
    assert len(payload["summaries"]) == 1
    assert payload["summaries"][0]["role"] == "host"


@pytest.mark.asyncio
async def test_build_payload_fallback_uses_activity_when_no_conversation(tmp_path):
    scope = "scope-act2"
    room = "room-act2"
    node_id = "req_clarify"
    host_dir = agent_node_dir(scope, "default", node_id)
    host_dir.mkdir(parents=True)
    (host_dir / "activity.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "category": "output",
                "title": "反馈",
                "display_title": "反馈",
                "summary": "已完成需求澄清要点整理",
                "success": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    base = archive_root(scope) / "需求设计" / node_id
    base.mkdir(parents=True)
    (base / "需求澄清.md").write_text("# OK", encoding="utf-8")

    pipe_path = meeting_pipeline_path(scope)
    pipe_path.parent.mkdir(parents=True, exist_ok=True)
    pipe_path.write_text(
        json.dumps({"schema_version": 1, "scope_id": scope, "context": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = await build_node_review_payload(
        scope_type="demand",
        scope_id=scope,
        room_id=room,
        node_id=node_id,
        binding={
            "host_profile_id": "default",
            "worker_profile_ids": [],
            "node_name": "需求澄清",
            "node_intent": "澄清需求",
            "stage_name": "需求设计",
        },
        report_body="# OK",
        tokens_used=100,
        duration_seconds=10,
        stage_id=2,
        agent_pool=None,
        orchestrator=None,
        use_llm_summary=False,
    )
    summary_md = payload["summaries"][0]["summary_markdown"]
    assert "需求澄清" in summary_md or "节点产出" in summary_md or "反馈" in summary_md


def test_invalid_summary_response_detection():
    assert _is_invalid_summary_response(
        "已收到您的提示。本次任务（撰写需求澄清工作总结摘要）已在上一轮完成输出，无需进一步调用工具。"
    )
    assert _is_invalid_summary_response("太短")
    assert not _is_invalid_summary_response(
        "在需求澄清环节中，分别委派给浩鲸需求分析专家与产品研发专家各一次，"
        "与研发人员交互一次，最终完成需求澄清文档编写并提交问卷确认。"
    )


@pytest.mark.asyncio
async def test_summarize_via_host_agent_uses_isolated_brain_call():
    from synapse.rd_meeting.node_review import _summarize_via_host_agent

    class _FakeBlock:
        text = (
            "在需求澄清环节中，分别委派给浩鲸需求分析专家与产品研发专家各一次，"
            "与研发人员交互一次，最终完成需求澄清文档编写并提交问卷确认。"
        )

    class _FakeResponse:
        content = [_FakeBlock()]

    class _FakeBrain:
        max_tokens = 2048

        async def messages_create_async(self, **kwargs):
            assert kwargs.get("tools") == []
            assert len(kwargs.get("messages") or []) == 1
            assert kwargs.get("usage_scene") == "rd_meeting_scope-llm_node_review"
            return _FakeResponse()

    out = await _summarize_via_host_agent(
        scope_id="scope-llm",
        room_id="room-llm",
        host_agent=SimpleNamespace(brain=_FakeBrain()),
        host_profile_id="default",
        target_profile_id="default",
        target_role="host",
        target_display="小鲸",
        prompt="【独立审阅任务】请撰写摘要",
    )
    assert "需求澄清" in out
