"""研发会议室：节点确认总结（NODE_REVIEW）payload 装配。

设计要点（对齐方案 §2）：

四段式 payload，由 pipeline ``_step_node_review`` 在 ``human_confirm`` 节点
LLM 跑完后组装并落盘到 ``meeting_pipeline.json.context.node_review[node_id]``
同时写入 ``room_state.pending_delivery.review_payload`` 供前端拉取：

1. **metrics**：节点 token / 时长 / 各 agent 委派 / 工具 / 技能 / token 聚合
2. **summaries**：主持人 + 各协作智能体的工作摘要（由 LLM 在 NODE_REVIEW 阶段
   基于 ``agents/<pid>/nodes/<node_id>/conversation.jsonl`` 总结一次）
3. **artifacts**：本节点 ``archive/<stage>/<node>/`` 下所有文件（含 mtime / size）
4. **report_body**：兼容字段，保留 LLM 终稿，前端可不显示

LLM 摘要走 host agent 的 ``execute_task_from_message``（与 run_current_node
共用 host 实例），不重新创建 agent，token 也算在 host 头上。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from synapse.rd_meeting.agent_session import (
    bind_meeting_agent_session,
    clear_meeting_agent_session,
    ensure_host_session,
)
from synapse.rd_meeting.paths import agent_node_dir, archive_root, meeting_pipeline_path
from synapse.rd_meeting.room_runtime import (
    load_room_state,
    read_json_file,
    save_room_state,
    write_json_file,
)
from synapse.rd_sop.nodes import node_display_name

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]

REVIEW_SCHEMA_VERSION = 1
_SUMMARY_PROMPT_BUDGET_CHARS = 6000  # 单 agent 摘要 prompt 上下文最大字符数


# ─── 数据结构 ─────────────────────────────────────────────────────────


@dataclass
class AgentMetricsRow:
    profile_id: str
    display_name: str
    role: str  # host / worker
    delegations: int = 0  # host：派单次数；worker：被派单次数
    tool_calls: int = 0
    skill_calls: int = 0
    tokens: int = 0
    tools: list[dict[str, Any]] = field(default_factory=list)  # [{name, count}]
    skills: list[dict[str, Any]] = field(default_factory=list)  # [{skill, count}]


@dataclass
class NodeReviewMetrics:
    node_token_total: int = 0
    node_duration_seconds: int = 0
    delegation_total: int = 0
    tool_call_total: int = 0
    skill_call_total: int = 0
    host: AgentMetricsRow | None = None
    workers: list[AgentMetricsRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_token_total": self.node_token_total,
            "node_duration_seconds": self.node_duration_seconds,
            "delegation_total": self.delegation_total,
            "tool_call_total": self.tool_call_total,
            "skill_call_total": self.skill_call_total,
            "host": asdict(self.host) if self.host else None,
            "workers": [asdict(w) for w in self.workers],
        }


@dataclass
class ArtifactFile:
    name: str
    relative_path: str  # 相对 scope_dir，例如 ``archive/2/req_clarify/需求澄清.md``
    size: int
    mtime: str
    ext: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentSummary:
    profile_id: str
    display_name: str
    role: str
    summary_markdown: str
    source: str  # llm / rule / fallback
    conversation_path: str = ""  # 相对 scope_dir 的路径，便于前端深入


# ─── 时间工具 ─────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── 指标聚合 ─────────────────────────────────────────────────────────


def _count_buckets(items: Iterable[str]) -> list[dict[str, Any]]:
    counter: dict[str, int] = {}
    for it in items:
        key = str(it or "").strip()
        if not key:
            continue
        counter[key] = counter.get(key, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda kv: -kv[1])
    ]


def _count_skill_buckets(items: Iterable[Any]) -> list[dict[str, Any]]:
    counter: dict[str, int] = {}
    for it in items:
        if isinstance(it, dict):
            key = str(it.get("skill") or it.get("script") or it.get("tool") or "").strip()
        else:
            key = str(it or "").strip()
        if not key:
            continue
        counter[key] = counter.get(key, 0) + 1
    return [
        {"skill": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda kv: -kv[1])
    ]


def _resolve_display_name(profile_id: str, fallback: str = "") -> str:
    try:
        from synapse.rd_meeting.room_skill import resolve_agent_profile

        p = resolve_agent_profile(profile_id)
        if p is not None:
            return p.get_display_name() or p.name or profile_id
    except Exception as exc:  # pragma: no cover
        logger.debug("resolve display_name failed pid=%s: %s", profile_id, exc)
    return fallback or profile_id


def _count_delegations(host_messages: list[Any]) -> int:
    """从 host messages 中数 ``delegate_to_agent`` / ``delegate_parallel`` 工具调用次数。"""
    count = 0
    for msg in host_messages or []:
        content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "") != "tool_use":
                continue
            name = str(part.get("name") or "")
            if name in ("delegate_to_agent", "delegate_parallel"):
                # delegate_parallel 一次可派 N 个，input.tasks 是数组
                if name == "delegate_parallel":
                    tasks = part.get("input", {}).get("tasks") if isinstance(part.get("input"), dict) else None
                    count += len(tasks) if isinstance(tasks, list) and tasks else 1
                else:
                    count += 1
    return count


def aggregate_node_metrics(
    *,
    scope_id: str,
    room_id: str,
    node_id: str,
    binding: dict[str, Any],
    agent_pool: Any | None,
    orchestrator: Any | None = None,
    tokens_used: int = 0,
    duration_seconds: int = 0,
) -> NodeReviewMetrics:
    """从 agent_pool + orchestrator.sub_agent_states 聚合节点级指标。

    指标来源：
    - **host**：从 pool 中的 host agent 取 ``_context.messages``、``last_usage``、``agent_state.current_task``
    - **workers**：优先从 ``orchestrator.get_sub_agent_states`` 拿（覆盖了 tokens / tools_total / skills_total），
      失败时回退到 pool 中 worker agent 的 task 快照
    """
    from synapse.rd_meeting.agent_session import host_session_id

    host_pid = str(binding.get("host_profile_id") or "default").strip() or "default"
    worker_pids = [
        str(w).strip()
        for w in (binding.get("worker_profile_ids") or [])
        if str(w).strip() and str(w).strip() != host_pid
    ]

    metrics = NodeReviewMetrics(
        node_token_total=int(tokens_used or 0),
        node_duration_seconds=int(duration_seconds or 0),
    )

    # ─── host ───
    host_messages: list[Any] = []
    host_tokens = 0
    host_tools_executed: list[str] = []
    host_skills_executed: list[Any] = []
    if agent_pool is not None and room_id:
        host_sid = host_session_id(room_id)
        host_agent = None
        try:
            host_agent = agent_pool.get_existing(host_sid) if hasattr(agent_pool, "get_existing") else None
        except Exception:
            host_agent = None
        if host_agent is not None:
            ctx = getattr(host_agent, "_context", None)
            host_messages = list(getattr(ctx, "messages", None) or [])
            usage = getattr(host_agent, "last_usage", None) or {}
            if isinstance(usage, dict):
                host_tokens = int(usage.get("total_tokens") or usage.get("tokens") or 0)
            state = getattr(host_agent, "agent_state", None)
            task = getattr(state, "current_task", None) if state is not None else None
            if task is not None:
                host_tools_executed = list(getattr(task, "tools_executed", None) or [])
                host_skills_executed = list(getattr(task, "skills_executed", None) or [])

    host_tool_buckets = _count_buckets(host_tools_executed)
    host_skill_buckets = _count_skill_buckets(host_skills_executed)
    delegations = _count_delegations(host_messages)
    metrics.host = AgentMetricsRow(
        profile_id=host_pid,
        display_name=_resolve_display_name(host_pid, fallback="小鲸"),
        role="host",
        delegations=delegations,
        tool_calls=sum(b["count"] for b in host_tool_buckets),
        skill_calls=sum(b["count"] for b in host_skill_buckets),
        tokens=host_tokens,
        tools=host_tool_buckets,
        skills=host_skill_buckets,
    )

    # ─── workers ───
    sub_rows_by_pid: dict[str, list[dict[str, Any]]] = {}
    if orchestrator is not None:
        try:
            from synapse.rd_meeting.agent_session import host_session_id as _hs

            host_sid = _hs(room_id)
            sub_rows = orchestrator.get_sub_agent_states(host_sid) if hasattr(orchestrator, "get_sub_agent_states") else []
            for row in sub_rows or []:
                if not isinstance(row, dict):
                    continue
                pid = str(row.get("profile_id") or row.get("agent_id") or "").strip()
                if not pid:
                    continue
                sub_rows_by_pid.setdefault(pid, []).append(row)
        except Exception as exc:  # pragma: no cover
            logger.debug("get_sub_agent_states failed scope=%s: %s", scope_id, exc)

    for wid in worker_pids:
        rows = sub_rows_by_pid.get(wid, [])
        tools_acc: list[str] = []
        skills_acc: list[Any] = []
        tokens_acc = 0
        invocations = len(rows)
        for r in rows:
            tools_acc.extend(list(r.get("tools_executed") or []))
            skills_acc.extend(list(r.get("skills_executed") or []))
            tokens_acc += int(r.get("tokens_used") or 0)
        if not rows and agent_pool is not None and room_id:
            worker_sid = f"rd_meeting:{room_id}:{wid}"
            try:
                w_agent = agent_pool.get_existing(worker_sid) if hasattr(agent_pool, "get_existing") else None
            except Exception:
                w_agent = None
            if w_agent is not None:
                state = getattr(w_agent, "agent_state", None)
                task = getattr(state, "current_task", None) if state is not None else None
                if task is not None:
                    tools_acc = list(getattr(task, "tools_executed", None) or [])
                    skills_acc = list(getattr(task, "skills_executed", None) or [])
                usage = getattr(w_agent, "last_usage", None) or {}
                if isinstance(usage, dict):
                    tokens_acc = int(usage.get("total_tokens") or usage.get("tokens") or 0)

        tool_buckets = _count_buckets(tools_acc)
        skill_buckets = _count_skill_buckets(skills_acc)
        metrics.workers.append(
            AgentMetricsRow(
                profile_id=wid,
                display_name=_resolve_display_name(wid, fallback=wid),
                role="worker",
                delegations=invocations,
                tool_calls=sum(b["count"] for b in tool_buckets),
                skill_calls=sum(b["count"] for b in skill_buckets),
                tokens=tokens_acc,
                tools=tool_buckets,
                skills=skill_buckets,
            )
        )

    metrics.delegation_total = (metrics.host.delegations if metrics.host else 0)
    metrics.tool_call_total = (metrics.host.tool_calls if metrics.host else 0) + sum(
        w.tool_calls for w in metrics.workers
    )
    metrics.skill_call_total = (metrics.host.skill_calls if metrics.host else 0) + sum(
        w.skill_calls for w in metrics.workers
    )
    if metrics.host and metrics.host.tokens > metrics.node_token_total:
        # 兜底：若调用方未给 tokens_used，使用 host last_usage
        metrics.node_token_total = metrics.host.tokens + sum(w.tokens for w in metrics.workers)
    return metrics


# ─── 产出物 ───────────────────────────────────────────────────────────


def collect_artifact_files(scope_id: str, stage_id: int, node_id: str) -> list[ArtifactFile]:
    """扫 ``archive/<stage_id>/<node_id>/`` 下所有文件（递归一层即可，归档很少嵌套）。"""
    sid = (scope_id or "").strip()
    if not sid:
        return []
    base = archive_root(sid) / str(stage_id) / node_id
    if not base.is_dir():
        return []
    from synapse.rd_meeting.paths import scope_dir

    scope_root = scope_dir(sid).resolve()
    out: list[ArtifactFile] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(scope_root).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            st = path.stat()
        except OSError:
            continue
        out.append(
            ArtifactFile(
                name=path.name,
                relative_path=rel,
                size=int(st.st_size),
                mtime=datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                ext=path.suffix.lower(),
            )
        )
    return out


# ─── 工作摘要（LLM 生成） ─────────────────────────────────────────────


def _read_conversation_excerpt(scope_id: str, profile_id: str, node_id: str) -> str:
    """读取 agent 节点 conversation.jsonl 并裁剪到 prompt 预算内。"""
    path = agent_node_dir(scope_id, profile_id, node_id) / "conversation.jsonl"
    if not path.is_file():
        return ""
    try:
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("read conversation %s failed: %s", path, exc)
        return ""
    lines: list[str] = []
    for r in rows:
        speaker = r.get("speaker", {})
        kind = speaker.get("kind") or r.get("role") or "?"
        name = speaker.get("display_name") or speaker.get("profile_id") or "-"
        text = str(r.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{kind}|{name}] {text}")
    body = "\n".join(lines)
    if len(body) <= _SUMMARY_PROMPT_BUDGET_CHARS:
        return body
    head = body[: _SUMMARY_PROMPT_BUDGET_CHARS // 2]
    tail = body[-_SUMMARY_PROMPT_BUDGET_CHARS // 2 :]
    return f"{head}\n\n…（节略 {len(body) - _SUMMARY_PROMPT_BUDGET_CHARS} 字符）…\n\n{tail}"


def _build_summary_prompt(
    *,
    role: str,
    profile_display_name: str,
    node_name: str,
    node_intent: str,
    excerpt: str,
) -> str:
    role_label = "主持人小鲸" if role == "host" else f"协作智能体「{profile_display_name}」"
    return (
        f"# 任务：为 SOP 节点「{node_name}」生成 {role_label} 的本节点工作摘要\n\n"
        f"## 节点目标\n{node_intent or '（未配置）'}\n\n"
        f"## 你需要总结的对话上下文\n"
        f"```\n{excerpt or '（本节点没有可读的对话记录）'}\n```\n\n"
        "## 输出要求\n"
        "- 用 Markdown，2-6 段，第一行是一个 H3 标题（含 agent 名称 + 本节点要点）。\n"
        f"- 视角始终是 **{role_label}**：用第一人称 / 第三人称都可，但不要混。\n"
        "- 必须包含：**做了什么**、**关键决策/结论**、**遗留问题（若有）**。\n"
        "- 如果有调用其他 agent / 工具 / 技能的关键节点，简要点名（用反引号包裹）。\n"
        "- 不要复述完整对话，不要列举每一条消息；只挑能让审阅者 30 秒理解全貌的要点。\n"
        "- 严禁编造未在上下文出现的事实。\n"
        "- 直接输出 Markdown 摘要正文，不要任何前后缀说明。\n"
    )


async def _summarize_via_host_agent(
    *,
    scope_id: str,
    room_id: str,
    host_agent: Any,
    host_profile_id: str,
    prompt: str,
) -> str:
    """复用 host agent 跑一次 LLM 总结。失败时返回空串。"""
    if host_agent is None:
        return ""
    meeting_session = ensure_host_session(room_id, host_profile_id)
    bind_meeting_agent_session(host_agent, meeting_session)
    try:
        result = await host_agent.execute_task_from_message(
            prompt,
            usage_scene=f"rd_meeting_{scope_id}_node_review",
        )
        if getattr(result, "success", False):
            return str(getattr(result, "data", "") or "").strip()
        logger.info(
            "node_review summary llm not success scope=%s err=%s",
            scope_id,
            getattr(result, "error", ""),
        )
        return ""
    except Exception as exc:  # pragma: no cover - LLM 调用本身可能抛
        logger.warning("node_review summary llm failed scope=%s: %s", scope_id, exc)
        return ""
    finally:
        clear_meeting_agent_session(host_agent)


def _fallback_summary(
    *,
    role: str,
    display_name: str,
    excerpt: str,
) -> str:
    """LLM 不可用时的兜底：从 excerpt 拿前 4 段 + 角色信息。"""
    chunks = [c.strip() for c in (excerpt or "").splitlines() if c.strip()]
    preview = "\n".join(chunks[:6]) if chunks else "（无对话记录可供总结）"
    head = "### 主持人工作摘要" if role == "host" else f"### {display_name} 工作摘要"
    return f"{head}\n\n_（LLM 摘要不可用，以下为对话前若干条原文回放）_\n\n```\n{preview}\n```\n"


async def generate_agent_summaries(
    *,
    scope_id: str,
    room_id: str,
    node_id: str,
    node_name: str,
    node_intent: str,
    host_profile_id: str,
    worker_profile_ids: list[str],
    agent_pool: Any | None,
    use_llm: bool = True,
) -> list[AgentSummary]:
    """逐 agent 调用 host LLM 总结；失败回落到 fallback。"""
    summaries: list[AgentSummary] = []

    host_agent = None
    if agent_pool is not None and room_id and use_llm:
        try:
            from synapse.rd_meeting.agent_session import host_session_id

            host_agent = agent_pool.get_existing(host_session_id(room_id)) if hasattr(agent_pool, "get_existing") else None
        except Exception:
            host_agent = None

    def _conv_relpath(pid: str) -> str:
        path = agent_node_dir(scope_id, pid, node_id) / "conversation.jsonl"
        try:
            from synapse.rd_meeting.paths import scope_dir

            return path.resolve().relative_to(scope_dir(scope_id).resolve()).as_posix()
        except (OSError, ValueError):
            return path.as_posix()

    targets: list[tuple[str, str]] = [(host_profile_id, "host")] + [
        (pid, "worker") for pid in worker_profile_ids if pid and pid != host_profile_id
    ]
    for pid, role in targets:
        display = _resolve_display_name(pid, fallback="小鲸" if role == "host" else pid)
        excerpt = _read_conversation_excerpt(scope_id, pid, node_id)
        prompt = _build_summary_prompt(
            role=role,
            profile_display_name=display,
            node_name=node_name,
            node_intent=node_intent,
            excerpt=excerpt,
        )
        markdown = ""
        source = "fallback"
        if use_llm and host_agent is not None:
            markdown = await _summarize_via_host_agent(
                scope_id=scope_id,
                room_id=room_id,
                host_agent=host_agent,
                host_profile_id=host_profile_id,
                prompt=prompt,
            )
            if markdown:
                source = "llm"
        if not markdown:
            markdown = _fallback_summary(role=role, display_name=display, excerpt=excerpt)
        summaries.append(
            AgentSummary(
                profile_id=pid,
                display_name=display,
                role=role,
                summary_markdown=markdown,
                source=source,
                conversation_path=_conv_relpath(pid),
            )
        )
    return summaries


# ─── payload 组装 + 落盘 ──────────────────────────────────────────────


async def build_node_review_payload(
    *,
    scope_type: ScopeType,
    scope_id: str,
    room_id: str,
    node_id: str,
    binding: dict[str, Any],
    report_body: str,
    tokens_used: int,
    duration_seconds: int,
    stage_id: int,
    agent_pool: Any | None,
    orchestrator: Any | None,
    use_llm_summary: bool = True,
) -> dict[str, Any]:
    """组装节点确认总结 payload。"""
    host_pid = str(binding.get("host_profile_id") or "default").strip() or "default"
    worker_pids = [
        str(w).strip()
        for w in (binding.get("worker_profile_ids") or [])
        if str(w).strip() and str(w).strip() != host_pid
    ]
    node_name = str(binding.get("node_name") or node_display_name(node_id))
    node_intent = str(binding.get("node_intent") or binding.get("intent") or "")

    metrics = aggregate_node_metrics(
        scope_id=scope_id,
        room_id=room_id,
        node_id=node_id,
        binding=binding,
        agent_pool=agent_pool,
        orchestrator=orchestrator,
        tokens_used=tokens_used,
        duration_seconds=duration_seconds,
    )

    summaries = await generate_agent_summaries(
        scope_id=scope_id,
        room_id=room_id,
        node_id=node_id,
        node_name=node_name,
        node_intent=node_intent,
        host_profile_id=host_pid,
        worker_profile_ids=worker_pids,
        agent_pool=agent_pool,
        use_llm=use_llm_summary,
    )

    artifacts = collect_artifact_files(scope_id, stage_id, node_id)

    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "room_id": room_id,
        "node_id": node_id,
        "node_name": node_name,
        "node_intent": node_intent,
        "stage_id": stage_id,
        "metrics": metrics.to_dict(),
        "summaries": [asdict(s) for s in summaries],
        "artifacts": [a.to_dict() for a in artifacts],
        "report_body": report_body or "",
        "generated_at": _now_iso(),
    }


def save_node_review(scope_id: str, node_id: str, payload: dict[str, Any]) -> None:
    """写 ``meeting_pipeline.json.context.node_review[node_id]`` + room_state.pending_delivery.review_payload。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid:
        return

    pipeline_path = meeting_pipeline_path(sid)
    raw = read_json_file(pipeline_path)
    if isinstance(raw, dict):
        ctx = raw.get("context") if isinstance(raw.get("context"), dict) else {}
        node_review = ctx.get("node_review") if isinstance(ctx.get("node_review"), dict) else {}
        node_review[nid] = payload
        ctx["node_review"] = node_review
        raw["context"] = ctx
        raw["updated_at"] = _now_iso()
        write_json_file(pipeline_path, raw)

    room_state = dict(load_room_state(sid) or {})
    pending = room_state.get("pending_delivery") if isinstance(room_state.get("pending_delivery"), dict) else {}
    pending = dict(pending)
    pending["review_payload"] = payload
    pending.setdefault("node_id", nid)
    pending.setdefault("report_body", payload.get("report_body") or "")
    pending.setdefault("await_confirm", True)
    pending.setdefault("tokens_used", int(payload.get("metrics", {}).get("node_token_total") or 0))
    pending.setdefault("duration_seconds", int(payload.get("metrics", {}).get("node_duration_seconds") or 0))
    pending.setdefault("stage_id", int(payload.get("stage_id") or 0))
    room_state["pending_delivery"] = pending
    save_room_state(sid, room_state)


def load_node_review(scope_id: str, node_id: str) -> dict[str, Any] | None:
    """读 pipeline.context.node_review[node_id]，供 API 路由返回前端。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid:
        return None
    raw = read_json_file(meeting_pipeline_path(sid))
    if not isinstance(raw, dict):
        return None
    ctx = raw.get("context") if isinstance(raw.get("context"), dict) else None
    if not isinstance(ctx, dict):
        return None
    node_review = ctx.get("node_review")
    if not isinstance(node_review, dict):
        return None
    payload = node_review.get(nid)
    return payload if isinstance(payload, dict) else None


def read_artifact_file(scope_id: str, relative_path: str) -> tuple[str, str] | None:
    """读取归档文件原文。返回 ``(content, ext)``，路径越权时返回 ``None``。

    安全约束：``relative_path`` 必须落在 ``scope_dir(scope_id)`` 之下。
    """
    sid = (scope_id or "").strip()
    rel = (relative_path or "").strip().lstrip("/").lstrip("\\")
    if not sid or not rel:
        return None
    from synapse.rd_meeting.paths import scope_dir

    base = scope_dir(sid).resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        logger.warning("read_artifact_file rejected escape: scope=%s rel=%s", sid, rel)
        return None
    if not target.is_file():
        return None
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return content, target.suffix.lower()


__all__ = [
    "REVIEW_SCHEMA_VERSION",
    "AgentMetricsRow",
    "AgentSummary",
    "ArtifactFile",
    "NodeReviewMetrics",
    "aggregate_node_metrics",
    "build_node_review_payload",
    "collect_artifact_files",
    "generate_agent_summaries",
    "load_node_review",
    "read_artifact_file",
    "save_node_review",
]
