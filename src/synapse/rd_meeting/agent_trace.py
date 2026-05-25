"""研发会议室：智能体节点级 trace 沉淀。

设计要点（对齐 NODE_REVIEW 方案 §3）：

- 每个智能体在工单内有自己的目录 ``work/<scope>/agents/<profile_id>/``。
- 节点级 trace 按 ``nodes/<node_id>/`` 分桶，包含：
  * ``conversation.jsonl``：归一化后的对话记录（user/host/coworker/system/tool）。
  * ``tools.jsonl``：工具调用快照（来自 ``agent_state.tools_executed``）。
  * ``skills.jsonl``：技能调用快照（来自 ``agent_state.skills_executed``）。
  * ``usage.json``：本节点 token 累计（来自 ``agent.last_usage``）。
  * ``events.jsonl``：生命周期事件（spawn / cleared / dumped）。
- 写入策略采取"节点收尾 dump + 关键节点点对点 append"双轨：
  * `dump_agent_node_trace`：在 ``_step_node_finish`` 清 messages **之前**整段写盘，
    保证最完整的对话快照不会因清理丢失。
  * `append_event`：用于显式打点（spawn、清理、强制 dump 等），辅助排查。

本模块不依赖 LLM，纯结构化写盘；写入失败仅打 warning 日志，不抛异常，
避免影响主流程（节点推进、HITL 等）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from synapse.rd_meeting.paths import agent_dir, agent_node_dir

logger = logging.getLogger(__name__)

SpeakerKind = Literal["user", "host", "coworker", "system", "tool", "unknown"]


# ─── Speaker 归一化 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Speaker:
    """对话发言人归一化描述。

    - ``kind``：粗粒度角色（user / host / coworker / system / tool / unknown）。
    - ``profile_id``：协作智能体或主持人对应的 Profile ID；user / system 为空。
    - ``display_name``：用户可读名称；coworker 必须解析为「具体的智能体名」。
    """

    kind: SpeakerKind
    profile_id: str = ""
    display_name: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
        }


def _resolve_display_name(profile_id: str) -> str:
    """根据 profile_id 查 AgentProfile 的 display_name；找不到返回 profile_id 本身。"""
    pid = (profile_id or "").strip()
    if not pid:
        return ""
    try:
        from synapse.rd_meeting.room_skill import resolve_agent_profile

        profile = resolve_agent_profile(pid)
        if profile is not None:
            name = profile.get_display_name() or profile.name or pid
            return str(name)
    except Exception as exc:  # pragma: no cover - profile 模块异常仅做兜底
        logger.debug("resolve display_name failed for %s: %s", pid, exc)
    return pid


def normalize_speaker(
    *,
    role: str,
    self_profile_id: str,
    host_profile_id: str,
    worker_profile_ids: Iterable[str] = (),
    hint_profile_id: str = "",
) -> Speaker:
    """根据消息 role + 当前 agent 身份推断 Speaker。

    规则：
    - ``role == "user"``：来自用户的消息（包括 host 视角下用户输入、worker 视角下
      Host 派单（被路由为 user 消息））。Worker 侧的 user 消息真实来源是 host，
      因此 worker 视角统一为 ``kind=host``，``display_name`` 标注「小鲸（派单）」。
    - ``role == "assistant"``：消息出自当前 agent 自己。host agent → kind=host；
      worker agent → kind=coworker，display_name 用 self profile。
    - ``role == "tool"``：工具结果回灌，kind=tool。
    - ``role == "system"``：kind=system。
    - 其余：kind=unknown。
    """
    r = (role or "").strip().lower()
    spid = (self_profile_id or "").strip()
    hpid = (host_profile_id or "").strip()
    worker_set = {str(w).strip() for w in worker_profile_ids if str(w).strip()}
    is_self_host = bool(spid) and spid == hpid

    if r == "system":
        return Speaker(kind="system", display_name="系统")

    if r == "tool":
        return Speaker(kind="tool", display_name="工具")

    if r == "user":
        if is_self_host:
            # host 视角：user = 真实用户
            return Speaker(kind="user", display_name="用户")
        # worker 视角：user = host 委派输入
        return Speaker(
            kind="host",
            profile_id=hpid,
            display_name=f"{_resolve_display_name(hpid) or '小鲸'}（派单）",
        )

    if r == "assistant":
        if is_self_host:
            return Speaker(
                kind="host",
                profile_id=hpid,
                display_name=_resolve_display_name(hpid) or "小鲸",
            )
        target_pid = spid or hint_profile_id
        if target_pid in worker_set or target_pid:
            return Speaker(
                kind="coworker",
                profile_id=target_pid,
                display_name=_resolve_display_name(target_pid) or target_pid,
            )

    return Speaker(kind="unknown", profile_id=spid, display_name=spid or r)


# ─── jsonl 工具 ────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
    except OSError as exc:  # pragma: no cover - 写盘失败仅警告
        logger.warning("agent_trace append %s failed: %s", path, exc)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        logger.warning("agent_trace write %s failed: %s", path, exc)


# ─── 消息归一化 ────────────────────────────────────────────────────────


def _stringify_content(content: Any) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """将 brain ``messages`` 中复合 content 拆成 (text, tool_uses, tool_results)。

    - ``text``：人类可读片段（包括 tool_use 的简要 JSON dump）。
    - ``tool_uses``：``[{"id","name","input"}]``。
    - ``tool_results``：``[{"tool_use_id","content"}]``。
    """
    if content is None:
        return "", [], []
    if isinstance(content, str):
        return content, [], []
    if not isinstance(content, list):
        return str(content), [], []

    parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    for raw in content:
        if not isinstance(raw, dict):
            parts.append(str(raw))
            continue
        ptype = str(raw.get("type") or "")
        if ptype == "text":
            parts.append(str(raw.get("text") or ""))
        elif ptype == "tool_use":
            name = str(raw.get("name") or "")
            tool_uses.append(
                {
                    "id": str(raw.get("id") or ""),
                    "name": name,
                    "input": raw.get("input"),
                }
            )
            parts.append(f"[tool_use] {name}")
        elif ptype == "tool_result":
            inner = raw.get("content")
            tool_results.append(
                {
                    "tool_use_id": str(raw.get("tool_use_id") or ""),
                    "content": inner,
                }
            )
            preview = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
            parts.append(f"[tool_result] {str(preview)[:200]}")
        else:
            try:
                parts.append(json.dumps(raw, ensure_ascii=False))
            except (TypeError, ValueError):
                parts.append(str(raw))
    return "\n".join(p for p in parts if p), tool_uses, tool_results


def _row_from_message(
    msg: Any,
    *,
    index: int,
    self_profile_id: str,
    host_profile_id: str,
    worker_profile_ids: Iterable[str],
) -> dict[str, Any]:
    if hasattr(msg, "to_dict"):
        try:
            data = msg.to_dict()  # type: ignore[union-attr]
        except Exception:
            data = {"role": getattr(msg, "role", "unknown"), "content": getattr(msg, "content", "")}
    elif isinstance(msg, dict):
        data = msg
    else:
        data = {"role": "unknown", "content": str(msg)}

    role = str(data.get("role") or "unknown").lower()
    text, tool_uses, tool_results = _stringify_content(data.get("content"))
    speaker = normalize_speaker(
        role=role,
        self_profile_id=self_profile_id,
        host_profile_id=host_profile_id,
        worker_profile_ids=worker_profile_ids,
    )
    row: dict[str, Any] = {
        "index": index,
        "role": role,
        "speaker": speaker.to_dict(),
        "text": text,
    }
    if tool_uses:
        row["tool_uses"] = tool_uses
    if tool_results:
        row["tool_results"] = tool_results
    return row


# ─── 对外 API ──────────────────────────────────────────────────────────


def append_event(
    scope_id: str,
    profile_id: str,
    node_id: str,
    *,
    event: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """记录 agent 生命周期事件（spawn / cleared / dumped 等）。"""
    sid = (scope_id or "").strip()
    if not sid or not (profile_id or "").strip():
        return
    row = {
        "ts": _now_iso(),
        "event": event,
        "node_id": node_id or "",
    }
    if detail:
        row["detail"] = detail
    _append_jsonl(agent_node_dir(sid, profile_id, node_id) / "events.jsonl", row)


def write_agent_meta(
    scope_id: str,
    profile_id: str,
    *,
    role: str,
    display_name: str = "",
    llm_endpoint: str = "",
    capabilities: dict[str, Any] | None = None,
) -> None:
    """写入 agent 维度的元数据 ``meta.json``（跨节点不变的身份信息）。"""
    sid = (scope_id or "").strip()
    pid = (profile_id or "").strip()
    if not sid or not pid:
        return
    name = display_name or _resolve_display_name(pid)
    payload: dict[str, Any] = {
        "profile_id": pid,
        "role": role,
        "display_name": name,
        "llm_endpoint": llm_endpoint or "",
        "updated_at": _now_iso(),
    }
    if capabilities:
        payload["capabilities"] = capabilities
    _write_json(agent_dir(sid, pid) / "meta.json", payload)


def dump_agent_node_trace(
    scope_id: str,
    profile_id: str,
    node_id: str,
    *,
    agent: Any,
    host_profile_id: str,
    worker_profile_ids: Iterable[str] = (),
    role: str = "worker",
) -> Path | None:
    """把当前 agent 节点上下文整段写盘（覆盖式 + tools/skills/usage 增量）。

    返回 ``conversation.jsonl`` 的路径；任何不可恢复错误时返回 ``None``。

    设计上**覆盖**写 conversation（保证一次节点最终一份完整快照），但
    tools / skills / events / usage 走追加，方便排查中间过程。
    """
    sid = (scope_id or "").strip()
    pid = (profile_id or "").strip()
    nid = (node_id or "").strip() or "pending"
    if not sid or not pid:
        return None

    base = agent_node_dir(sid, pid, nid)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover
        logger.warning("agent_trace mkdir %s failed: %s", base, exc)
        return None

    conv_path = base / "conversation.jsonl"
    ctx = getattr(agent, "_context", None)
    messages = list(getattr(ctx, "messages", None) or [])
    try:
        with conv_path.open("w", encoding="utf-8") as f:
            for idx, msg in enumerate(messages):
                row = _row_from_message(
                    msg,
                    index=idx,
                    self_profile_id=pid,
                    host_profile_id=host_profile_id,
                    worker_profile_ids=worker_profile_ids,
                )
                f.write(json.dumps(row, ensure_ascii=False))
                f.write("\n")
    except OSError as exc:  # pragma: no cover
        logger.warning("dump conversation %s failed: %s", conv_path, exc)
        return None

    state = getattr(agent, "agent_state", None)
    task = getattr(state, "current_task", None) if state is not None else None
    if task is not None:
        tools = list(getattr(task, "tools_executed", None) or [])
        skills = list(getattr(task, "skills_executed", None) or [])
        if tools:
            _write_json(
                base / "tools.json",
                {"tools_executed": tools, "updated_at": _now_iso()},
            )
        if skills:
            _write_json(
                base / "skills.json",
                {"skills_executed": skills, "updated_at": _now_iso()},
            )

    usage = getattr(agent, "last_usage", None) or {}
    if isinstance(usage, dict) and usage:
        _write_json(
            base / "usage.json",
            {
                "last_usage": usage,
                "updated_at": _now_iso(),
            },
        )

    append_event(
        sid,
        pid,
        nid,
        event="dumped",
        detail={
            "role": role,
            "messages": len(messages),
            "tools": len(list(getattr(task, "tools_executed", None) or [])) if task else 0,
            "skills": len(list(getattr(task, "skills_executed", None) or [])) if task else 0,
        },
    )
    return conv_path


def reset_agent_node_context(
    scope_id: str,
    profile_id: str,
    node_id: str,
    *,
    agent: Any,
    reason: str = "node_finish",
) -> None:
    """清空 agent 节点内对话上下文 + TaskState（"严格冷启动"）。

    调用方应**先** ``dump_agent_node_trace`` 再调本函数，避免上下文丢失。
    """
    sid = (scope_id or "").strip()
    pid = (profile_id or "").strip()
    if not sid or not pid:
        return
    cleared_msgs = 0
    cleared_task = False
    ctx = getattr(agent, "_context", None)
    msgs = getattr(ctx, "messages", None) if ctx is not None else None
    if isinstance(msgs, list):
        cleared_msgs = len(msgs)
        try:
            msgs.clear()
        except Exception as exc:  # pragma: no cover
            logger.debug("clear messages failed for %s/%s: %s", sid, pid, exc)
    state = getattr(agent, "agent_state", None)
    if state is not None:
        try:
            state.current_task = None  # type: ignore[assignment]
            cleared_task = True
        except Exception as exc:  # pragma: no cover
            logger.debug("reset current_task failed for %s/%s: %s", sid, pid, exc)
    append_event(
        sid,
        pid,
        node_id,
        event="cleared",
        detail={"reason": reason, "messages": cleared_msgs, "task_reset": cleared_task},
    )
