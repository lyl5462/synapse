"""研发会议室：从 Agent 池探测各参会智能体的运行时上下文（调试用）。"""



from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from synapse.rd_meeting.agent_activity import (
    aggregate_tools_and_skills,
    enrich_display,
    list_node_agent_profiles,
    read_activity_log,
)
from synapse.rd_meeting.agent_session import host_session_id
from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.live import scope_id_for_room_id
from synapse.rd_meeting.paths import scope_dir

logger = logging.getLogger(__name__)



_DEFAULT_MESSAGE_CHAR_LIMIT = 12_000





def _truncate_text(text: str, limit: int) -> tuple[str, bool]:

    if limit <= 0 or len(text) <= limit:

        return text, False

    return text[:limit] + f"\n\n…（已截断，原文 {len(text)} 字符）", True





def _serialize_messages(messages: list[Any], *, char_limit: int) -> tuple[list[dict[str, Any]], bool]:

    out: list[dict[str, Any]] = []

    truncated = False

    for msg in messages:

        if isinstance(msg, dict):

            row = dict(msg)

        elif hasattr(msg, "to_dict"):

            row = msg.to_dict()

        else:

            row = {"role": "unknown", "content": str(msg)}

        content = row.get("content")

        if isinstance(content, str):

            row["content"], cut = _truncate_text(content, char_limit)

            truncated = truncated or cut

        out.append(row)

    return out, truncated





def _task_snapshot_from_state(agent: Any, session_id: str) -> dict[str, Any] | None:

    state = getattr(agent, "agent_state", None)

    if state is None or not session_id:

        return None

    task = state.get_task_for_session(session_id)

    if task is None:

        return None

    status = task.status.value if hasattr(task.status, "value") else str(task.status)

    return {

        "task_id": str(getattr(task, "task_id", "") or "")[:8],

        "status": status,

        "iteration": int(getattr(task, "iteration", 0) or 0),

        "tools_executed": list(getattr(task, "tools_executed", None) or []),

        "skills_executed": list(getattr(task, "skills_executed", None) or []),

        "description_preview": str(getattr(task, "description", "") or "")[:500],

        "usage_scene": str(getattr(task, "usage_scene", "") or ""),

    }





def _task_snapshot(

    agent: Any,

    session_id: str,

    *,

    fallback_session_ids: list[str] | None = None,

) -> dict[str, Any] | None:

    """按 session 查 TaskState；Worker 委派任务注册在 host session，需 fallback。"""

    candidates = [session_id]

    for sid in fallback_session_ids or []:

        if sid and sid not in candidates:

            candidates.append(sid)



    best: dict[str, Any] | None = None

    best_score = -1

    for sid in candidates:

        snap = _task_snapshot_from_state(agent, sid)

        if snap is None:

            continue

        score = len(snap.get("tools_executed") or []) + len(snap.get("skills_executed") or [])

        if snap.get("status") not in ("idle", ""):

            score += 10

        if score > best_score:

            best = snap

            best_score = score



    if best is not None:

        return best



    state = getattr(agent, "agent_state", None)

    if state is None:

        return None

    task = state.current_task

    if task is None:

        return None

    status = task.status.value if hasattr(task.status, "value") else str(task.status)

    return {

        "task_id": str(getattr(task, "task_id", "") or "")[:8],

        "status": status,

        "iteration": int(getattr(task, "iteration", 0) or 0),

        "tools_executed": list(getattr(task, "tools_executed", None) or []),

        "skills_executed": list(getattr(task, "skills_executed", None) or []),

        "description_preview": str(getattr(task, "description", "") or "")[:500],

        "usage_scene": str(getattr(task, "usage_scene", "") or ""),

    }





def _skill_key(item: dict[str, Any]) -> str:

    return "|".join(

        [

            str(item.get("skill") or ""),

            str(item.get("tool") or ""),

            str(item.get("script") or ""),

        ]

    )





def _merge_task_with_sub_agents(

    task: dict[str, Any] | None,

    sub_rows: list[dict[str, Any]],

) -> dict[str, Any] | None:

    if not sub_rows:

        return task



    merged: dict[str, Any] = dict(task) if isinstance(task, dict) else {}

    tools: list[str] = list(merged.get("tools_executed") or [])

    skills: list[dict[str, Any]] = list(merged.get("skills_executed") or [])

    skill_seen = {_skill_key(s) for s in skills if isinstance(s, dict)}

    max_iter = int(merged.get("iteration") or 0)



    for row in sub_rows:

        max_iter = max(max_iter, int(row.get("iteration") or 0))

        for name in row.get("tools_executed") or []:

            tool = str(name or "").strip()

            if tool and tool not in tools:

                tools.append(tool)

        total = int(row.get("tools_total") or 0)

        if total > len(tools):

            merged["tools_total_hint"] = max(int(merged.get("tools_total_hint") or 0), total)

        for item in row.get("skills_executed") or []:

            if not isinstance(item, dict):

                continue

            key = _skill_key(item)

            if key in skill_seen:

                continue

            skill_seen.add(key)

            skills.append(dict(item))

        stotal = int(row.get("skills_total") or 0)

        if stotal > len(skills):

            merged["skills_total_hint"] = max(int(merged.get("skills_total_hint") or 0), stotal)

        status = str(row.get("status") or "").strip()

        if status and merged.get("status") in (None, "", "idle"):

            merged["status"] = status



    merged["tools_executed"] = tools

    merged["skills_executed"] = skills

    merged["iteration"] = max_iter

    return merged





def _delegation_runs_from_sub_rows(sub_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for row in sub_rows:
        runs.append(
            {
                "status": row.get("status"),
                "reason": row.get("reason") or "",
                "from_agent": row.get("from_agent") or "",
                "elapsed_s": row.get("elapsed_s"),
                "iteration": row.get("iteration"),
                "tools_total": row.get("tools_total"),
                "tools_executed": list(row.get("tools_executed") or []),
                "skills_total": row.get("skills_total"),
                "current_tool_summary": row.get("current_tool_summary") or "",
                "started_at": row.get("started_at"),
                "task_preview": row.get("task_preview") or "",
                "result_summary": row.get("result_summary") or "",
                "plan_item_id": row.get("plan_item_id") or "",
            }
        )
    return runs


def _delegation_runs_from_history(
    scope_id: str | None,
    profile_id: str,
    *,
    node_id: str | None = None,
) -> list[dict[str, Any]]:
    """从 room_history 还原委派记录（任务结束后 sub_agent_states 会清理，历史为持久来源）。"""
    sid = (scope_id or "").strip()
    pid = (profile_id or "").strip()
    nid_filter = (node_id or "").strip()
    if not sid or not pid:
        return []
    from synapse.rd_meeting.room_runtime import read_history

    pending: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for ev in read_history(sid, limit=500):
        if not isinstance(ev, dict):
            continue
        if nid_filter:
            ev_nid = str(ev.get("node_id") or "").strip()
            if ev_nid and ev_nid != nid_filter:
                continue
        et = str(ev.get("event") or "").strip()
        to_agent = str(ev.get("to_agent") or "").strip()
        if to_agent != pid:
            continue
        if et == "delegation_started":
            pending.append(ev)
        elif et == "delegation_finished":
            started = pending.pop(0) if pending else None
            ok = ev.get("ok")
            if ok is None:
                ok = str(ev.get("status") or "").strip().lower() == "completed"
            runs.append(
                {
                    "status": "completed" if ok else "failed",
                    "reason": str((started or {}).get("reason") or ""),
                    "from_agent": str((started or {}).get("from_agent") or ""),
                    "task_preview": str((started or {}).get("task_preview") or ""),
                    "plan_item_id": str((started or {}).get("plan_item_id") or ""),
                    "result_summary": str(ev.get("text") or "").strip(),
                    "elapsed_s": ev.get("elapsed_s"),
                    "started_at": (started or {}).get("ts"),
                    "finished_at": ev.get("ts"),
                }
            )
    for started in pending:
        runs.append(
            {
                "status": "delegating",
                "reason": str(started.get("reason") or ""),
                "from_agent": str(started.get("from_agent") or ""),
                "task_preview": str(started.get("task_preview") or ""),
                "plan_item_id": str(started.get("plan_item_id") or ""),
                "started_at": started.get("ts"),
            }
        )
    return runs


def _delegation_runs_for_profile(
    scope_id: str | None,
    profile_id: str,
    sub_rows: list[dict[str, Any]],
    *,
    node_id: str | None = None,
) -> list[dict[str, Any]]:
    """历史委派为主；进行中任务用 live sub_agent 状态覆盖指标。"""
    hist = _delegation_runs_from_history(scope_id, profile_id, node_id=node_id)
    live = _delegation_runs_from_sub_rows(sub_rows)
    if not live:
        return hist
    if not hist:
        return live
    out = list(hist)
    live_by_status = {str(r.get("status") or ""): r for r in live}
    for i, run in enumerate(out):
        st = str(run.get("status") or "")
        if st in ("delegating", "starting", "running") and live:
            out[i] = {**run, **live[-1]}
            return out
    if live[-1].get("status") in ("running", "starting", "delegating"):
        out.append(live[-1])
    return out





def _resolve_system_prompt(agent: Any) -> str:

    ctx = getattr(agent, "_context", None)

    system = str(getattr(ctx, "system", "") or "").strip()

    if system:

        return system

    builder = getattr(agent, "_build_system_prompt", None)

    if callable(builder):

        try:

            return str(builder() or "")

        except Exception as exc:

            logger.debug("probe _build_system_prompt failed: %s", exc)

    return ""




def _merge_task_with_activity(
    task: dict[str, Any] | None,
    activity_entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not activity_entries and not task:
        return task
    merged: dict[str, Any] = dict(task) if isinstance(task, dict) else {}
    act_tools, act_skills = aggregate_tools_and_skills(activity_entries)
    tools: list[str] = list(merged.get("tools_executed") or [])
    for name in act_tools:
        if name not in tools:
            tools.append(name)
    skills: list[dict[str, Any]] = list(merged.get("skills_executed") or [])
    skill_seen = {_skill_key(s) for s in skills if isinstance(s, dict)}
    for item in act_skills:
        key = _skill_key(item)
        if key in skill_seen:
            continue
        skill_seen.add(key)
        skills.append(item)
    merged["tools_executed"] = tools
    merged["skills_executed"] = skills
    if act_tools:
        merged["tools_total_hint"] = max(int(merged.get("tools_total_hint") or 0), len(tools))
    if act_skills:
        merged["skills_total_hint"] = max(int(merged.get("skills_total_hint") or 0), len(skills))
    return merged


def _load_agent_activity_bundle(
    scope_id: str | None,
    node_id: str,
    profile_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not scope_id or not profile_id:
        return [], []
    raw = read_activity_log(scope_id, node_id, profile_id)
    history = [enrich_display(row) for row in raw]
    return raw, history


def probe_pooled_agent(

    agent: Any,

    *,

    session_id: str,

    profile_id: str,

    message_char_limit: int = _DEFAULT_MESSAGE_CHAR_LIMIT,

    fallback_task_session_ids: list[str] | None = None,

    sub_agent_rows: list[dict[str, Any]] | None = None,

    scope_id: str | None = None,

    current_node_id: str = "pending",

) -> dict[str, Any]:

    """从 Agent 池实例提取可读的上下文快照。"""

    role = "host" if session_id.endswith(":host") else "worker"

    ctx = getattr(agent, "_context", None)

    raw_messages = list(getattr(ctx, "messages", None) or [])

    messages, messages_truncated = _serialize_messages(raw_messages, char_limit=message_char_limit)



    system_prompt = _resolve_system_prompt(agent)

    system_prompt, system_truncated = _truncate_text(system_prompt, message_char_limit * 2)



    suffix = str(getattr(agent, "_custom_prompt_suffix", "") or "")

    suffix, suffix_truncated = _truncate_text(suffix, message_char_limit)



    sub_rows = list(sub_agent_rows or [])

    task = _merge_task_with_sub_agents(

        _task_snapshot(agent, session_id, fallback_session_ids=fallback_task_session_ids),

        sub_rows,

    )

    activity_raw, processing_history = _load_agent_activity_bundle(
        scope_id, current_node_id, profile_id
    )
    task = _merge_task_with_activity(task, activity_raw)



    return {

        "session_id": session_id,

        "profile_id": profile_id,

        "role": role,

        "current_node_id": current_node_id,

        "preferred_endpoint": str(getattr(agent, "_preferred_endpoint", "") or ""),

        "default_cwd": str(getattr(agent, "default_cwd", "") or ""),

        "system_prompt": system_prompt,

        "system_prompt_truncated": system_truncated,

        "custom_prompt_suffix": suffix,

        "custom_prompt_suffix_truncated": suffix_truncated,

        "messages": messages,

        "messages_count": len(raw_messages),

        "messages_truncated": messages_truncated,

        "processing_history": processing_history,

        "processing_history_count": len(processing_history),

        "task": task,

        "delegation_runs": _delegation_runs_for_profile(
            scope_id, profile_id, sub_rows, node_id=current_node_id
        ),

        "last_usage": getattr(agent, "last_usage", None),

    }





def _sub_rows_for_profile(sub_agents: list[dict[str, Any]], profile_id: str) -> list[dict[str, Any]]:

    pid = (profile_id or "").strip()

    if not pid:

        return []

    out: list[dict[str, Any]] = []

    for row in sub_agents:

        if not isinstance(row, dict):

            continue

        rid = str(row.get("profile_id") or row.get("agent_id") or "").strip()

        if rid == pid:

            out.append(row)

    return out


def _worker_profile_ids_from_delegation_history(
    scope_id: str | None,
    *,
    node_id: str | None = None,
) -> list[str]:
    sid = (scope_id or "").strip()
    nid_filter = (node_id or "").strip()
    if not sid:
        return []
    from synapse.rd_meeting.room_runtime import read_history

    ids: list[str] = []
    seen: set[str] = set()
    for ev in read_history(sid, limit=500):
        if not isinstance(ev, dict):
            continue
        if nid_filter:
            ev_nid = str(ev.get("node_id") or "").strip()
            if ev_nid and ev_nid != nid_filter:
                continue
        if str(ev.get("event") or "") not in ("delegation_started", "delegation_finished"):
            continue
        to_agent = str(ev.get("to_agent") or "").strip()
        if to_agent and to_agent not in seen:
            seen.add(to_agent)
            ids.append(to_agent)
    return ids


def collect_meeting_agent_contexts(
    room_id: str,
    agent_pool: Any | None,
    *,
    orchestrator: Any | None = None,
    message_char_limit: int = _DEFAULT_MESSAGE_CHAR_LIMIT,
    node_id: str | None = None,
) -> dict[str, Any]:
    """汇总会议室下 host / worker 的上下文；``node_id`` 指定 SOP 节点（默认同 dev.status 当前节点）。"""
    rid = (room_id or "").strip()
    scope_id = scope_id_for_room_id(rid)

    live_node_id = "pending"
    if scope_id:
        dev = load_dev_status(scope_id)
        if dev:
            live_node_id = str(dev.get("current_node_id") or "pending")

    target_node_id = (node_id or "").strip() or live_node_id
    probe_live_pool = target_node_id == live_node_id

    prefix = f"rd_meeting:{rid}:"
    host_sid = host_session_id(rid)

    sub_agents: list[dict[str, Any]] = []
    if probe_live_pool and orchestrator is not None:
        getter = getattr(orchestrator, "get_sub_agent_states", None)
        if callable(getter):
            sub_agents = list(getter(host_sid) or [])

    agents: list[dict[str, Any]] = []
    seen_profiles: set[str] = set()

    if probe_live_pool and agent_pool is not None:

        stats = agent_pool.get_stats() if hasattr(agent_pool, "get_stats") else {}

        seen: set[tuple[str, str]] = set()

        for sess in stats.get("sessions", []):

            sid = str(sess.get("session_id") or "")

            if not sid.startswith(prefix):

                continue

            for info in sess.get("agents", []) or []:

                pid = str(info.get("profile_id") or "")

                key = (sid, pid)

                if key in seen:

                    continue

                seen.add(key)

                getter = getattr(agent_pool, "get_existing", None)

                if not callable(getter):

                    continue

                pooled = getter(sid, pid)

                if pooled is None:

                    continue

                seen_profiles.add(pid)

                fallback_ids = [host_sid] if not sid.endswith(":host") else None

                sub_rows = _sub_rows_for_profile(sub_agents, pid)

                agents.append(

                    probe_pooled_agent(

                        pooled,

                        session_id=sid,

                        profile_id=pid,

                        message_char_limit=message_char_limit,

                        fallback_task_session_ids=fallback_ids,

                        sub_agent_rows=sub_rows,

                        scope_id=scope_id,
                        current_node_id=target_node_id,
                    )
                )

    if scope_id:
        host_profile_id = ""
        try:
            from synapse.rd_meeting.binding import resolve_node_binding

            b = resolve_node_binding(target_node_id)
            host_profile_id = str(b.get("host_profile_id") or "default").strip() or "default"
        except Exception:
            host_profile_id = "default"
        for pid in list_node_agent_profiles(scope_id, target_node_id):
            if pid in seen_profiles:
                continue
            activity_raw, processing_history = _load_agent_activity_bundle(
                scope_id, target_node_id, pid
            )
            if not processing_history:
                continue
            role = "host" if pid == host_profile_id else "worker"
            sid = host_sid if role == "host" else f"{prefix}{pid}"
            task = _merge_task_with_activity(None, activity_raw)
            agents.append(
                {
                    "session_id": sid,
                    "profile_id": pid,
                    "role": role,
                    "current_node_id": target_node_id,
                    "system_prompt": "",
                    "messages": [],
                    "messages_count": 0,
                    "processing_history": processing_history,
                    "processing_history_count": len(processing_history),
                    "task": task,
                    "delegation_runs": _delegation_runs_for_profile(
                        scope_id,
                        pid,
                        _sub_rows_for_profile(sub_agents, pid),
                        node_id=target_node_id,
                    ),
                    "offline_from_disk": True,
                }
            )

    for pid in _worker_profile_ids_from_delegation_history(scope_id, node_id=target_node_id):
        if pid in seen_profiles:
            continue
        runs = _delegation_runs_for_profile(
            scope_id,
            pid,
            _sub_rows_for_profile(sub_agents, pid),
            node_id=target_node_id,
        )
        if not runs:
            continue
        agents.append(
            {
                "session_id": f"{prefix}{pid}",
                "profile_id": pid,
                "role": "worker",
                "current_node_id": target_node_id,
                "system_prompt": "",
                "messages": [],
                "messages_count": 0,
                "delegation_runs": runs,
                "offline_from_history": True,
            }
        )

    return {
        "room_id": rid,
        "scope_id": scope_id,
        "current_node_id": target_node_id,
        "live_node_id": live_node_id,
        "host_session_id": host_sid,
        "agents": agents,
        "sub_agents": sub_agents if probe_live_pool else [],
        "probed_at": datetime.now().isoformat(timespec="seconds"),
    }





def dump_meeting_agent_contexts(

    payload: dict[str, Any],

    *,

    scope_id: str,

) -> str:

    """将探测结果写入工单目录 debug/agent_contexts/，并打 INFO 摘要日志。"""

    sid = (scope_id or "").strip()

    if not sid:

        raise ValueError("scope_id_required")



    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    out_dir = scope_dir(sid) / "debug" / "agent_contexts"

    out_dir.mkdir(parents=True, exist_ok=True)

    path = out_dir / f"{ts}.json"

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")



    for agent in payload.get("agents") or []:

        if not isinstance(agent, dict):

            continue

        task = agent.get("task") if isinstance(agent.get("task"), dict) else {}

        logger.info(

            "[rd_meeting context] room=%s profile=%s role=%s "

            "msgs=%s task=%s iter=%s tools=%s → %s",

            payload.get("room_id"),

            agent.get("profile_id"),

            agent.get("role"),

            agent.get("messages_count"),

            task.get("status"),

            task.get("iteration"),

            len(task.get("tools_executed") or []),

            path,

        )



    if not payload.get("agents"):

        logger.info(

            "[rd_meeting context] room=%s scope=%s no pooled agents (file=%s)",

            payload.get("room_id"),

            sid,

            path,

        )



    return str(path)

