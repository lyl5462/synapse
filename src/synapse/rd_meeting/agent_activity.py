"""研发会议室：智能体节点级活动埋点（输入 / 输出 / 工具 / 技能）。

落盘路径（用户约定）::

    work/<scope>/agents/<node_id>/<profile_id>/activity.jsonl

每条记录为 JSON 一行，``category`` 取 ``input`` | ``output`` | ``tool`` | ``skill``。
写入失败仅打 warning，不阻断主流程。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from synapse.rd_meeting.dev_status import load_dev_status
from synapse.rd_meeting.live import parse_rd_meeting_session, scope_id_for_room_id
from synapse.rd_meeting.paths import agent_sop_node_dir, agent_sop_profile_dir

logger = logging.getLogger(__name__)

ActivityCategory = Literal["input", "output", "tool", "skill"]
InputSource = Literal["human", "system", "host"]

_PREVIEW_LIMIT = 2_000
_INPUT_JSON_LIMIT = 4_000
_SKILL_TOOLS = frozenset(
    {
        "get_skill_info",
        "run_skill_script",
        "get_skill_reference",
        "read_skill_file",
        "reload_skill",
        "unload_skill",
    }
)

_CATEGORY_LABELS: dict[str, str] = {
    "input": "接收输入",
    "output": "产出反馈",
    "tool": "调用工具",
    "skill": "调用技能",
}

_INPUT_SOURCE_LABELS: dict[str, str] = {
    "human": "人类",
    "system": "应用系统",
    "host": "主持 Agent",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _truncate(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…（已截断，原文 {len(s)} 字符）"


def _safe_json(obj: Any, limit: int = _INPUT_JSON_LIMIT) -> Any:
    if obj is None:
        return None
    try:
        raw = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(obj)
    if len(raw) <= limit:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return _truncate(raw, limit)


def activity_dir(scope_id: str, node_id: str, profile_id: str) -> Path:
    return agent_sop_profile_dir(scope_id, node_id, profile_id)


def _activity_path(scope_id: str, node_id: str, profile_id: str) -> Path:
    return activity_dir(scope_id, node_id, profile_id) / "activity.jsonl"


def _next_seq(path: Path) -> int:
    if not path.is_file():
        return 1
    try:
        count = sum(1 for _ in path.open(encoding="utf-8"))
        return count + 1
    except OSError:
        return 1


def _append_row(scope_id: str, node_id: str, profile_id: str, row: dict[str, Any]) -> dict[str, Any] | None:
    sid = (scope_id or "").strip()
    nid = (node_id or "pending").strip() or "pending"
    pid = (profile_id or "").strip()
    if not sid or not pid:
        return None
    path = _activity_path(sid, nid, pid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        seq = _next_seq(path)
        entry = {
            "id": row.get("id") or uuid.uuid4().hex[:12],
            "seq": seq,
            "ts": row.get("ts") or _now_iso(),
            "category": row.get("category"),
            "node_id": nid,
            "profile_id": pid,
            **{k: v for k, v in row.items() if k not in ("id", "seq", "ts", "category", "node_id", "profile_id")},
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str))
            fh.write("\n")
        _touch_meta(sid, nid, pid, entry)
        return entry
    except OSError as exc:
        logger.warning("agent_activity append failed %s: %s", path, exc)
        return None


def _touch_meta(scope_id: str, node_id: str, profile_id: str, last_entry: dict[str, Any]) -> None:
    meta_path = activity_dir(scope_id, node_id, profile_id) / "meta.json"
    try:
        payload: dict[str, Any] = {}
        if meta_path.is_file():
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "scope_id": scope_id,
                "node_id": node_id,
                "profile_id": profile_id,
                "updated_at": _now_iso(),
                "last_category": last_entry.get("category"),
                "last_seq": last_entry.get("seq"),
                "entry_count": int(payload.get("entry_count") or 0) + 1,
            }
        )
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("agent_activity meta touch failed: %s", exc)


def set_agent_activity_binding(
    agent: Any,
    *,
    scope_id: str,
    node_id: str,
    profile_id: str,
    host_profile_id: str = "",
    role: str = "host",
    room_id: str = "",
) -> None:
    """在会议室 configure / bind 时写入 agent 实例，供工具埋点读取。"""
    try:
        agent._rd_meeting_activity = {  # type: ignore[attr-defined]
            "scope_id": (scope_id or "").strip(),
            "node_id": (node_id or "pending").strip() or "pending",
            "profile_id": (profile_id or "").strip(),
            "host_profile_id": (host_profile_id or profile_id or "").strip(),
            "role": (role or "host").strip(),
            "room_id": (room_id or "").strip(),
        }
    except Exception as exc:
        logger.debug("set_agent_activity_binding failed: %s", exc)


def resolve_agent_activity_binding(agent: Any) -> dict[str, str] | None:
    """从 agent 实例解析会议室活动上下文。"""
    bound = getattr(agent, "_rd_meeting_activity", None)
    if isinstance(bound, dict) and bound.get("scope_id") and bound.get("profile_id"):
        return {
            "scope_id": str(bound["scope_id"]),
            "node_id": str(bound.get("node_id") or "pending"),
            "profile_id": str(bound["profile_id"]),
            "host_profile_id": str(bound.get("host_profile_id") or bound["profile_id"]),
            "role": str(bound.get("role") or "host"),
            "room_id": str(bound.get("room_id") or ""),
        }

    session_id = (
        str(getattr(agent, "_current_session_id", "") or "")
        or str(getattr(getattr(agent, "_current_session", None), "id", "") or "")
    ).strip()
    if not session_id:
        return None

    parsed = parse_rd_meeting_session(session_id)
    if not parsed:
        return None

    room_id = str(parsed.get("room_id") or "").strip()
    scope_id = scope_id_for_room_id(room_id)
    if not scope_id:
        return None

    dev = load_dev_status(scope_id)
    node_id = str(dev.get("current_node_id") or "pending") if dev else "pending"

    role_part = str(parsed.get("role") or "")
    if role_part == "host":
        profile_id = ""
        sess = getattr(agent, "_current_session", None)
        ctx = getattr(sess, "context", None) if sess else None
        profile_id = str(getattr(ctx, "agent_profile_id", "") or "").strip()
        if not profile_id:
            profile_id = str(getattr(agent, "_agent_profile_id", "") or "").strip()
        host_profile_id = profile_id
        role = "host"
    else:
        profile_id = role_part
        host_profile_id = ""
        role = "worker"
        binding_host = ""
        try:
            from synapse.rd_meeting.binding import resolve_node_binding

            b = resolve_node_binding(node_id)
            binding_host = str(b.get("host_profile_id") or "").strip()
        except Exception:
            binding_host = ""
        host_profile_id = binding_host

    if not profile_id:
        return None

    return {
        "scope_id": scope_id,
        "node_id": node_id,
        "profile_id": profile_id,
        "host_profile_id": host_profile_id or profile_id,
        "role": role,
        "room_id": room_id,
    }


def record_host_human_input(
    scope_id: str,
    node_id: str,
    host_profile_id: str,
    *,
    input_kind: str,
    title: str,
    summary: str = "",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    binding = resolve_binding_for_profile(
        scope_id, node_id, host_profile_id, host_profile_id=host_profile_id
    )
    return record_input(
        binding,
        source="human",
        input_kind=input_kind,
        title=title,
        summary=summary,
        detail=detail,
    )

    scope_id: str,
    node_id: str,
    profile_id: str,
    *,
    host_profile_id: str = "",
) -> dict[str, str]:
    return {
        "scope_id": (scope_id or "").strip(),
        "node_id": (node_id or "pending").strip() or "pending",
        "profile_id": (profile_id or "").strip(),
        "host_profile_id": (host_profile_id or profile_id or "").strip(),
    }


def record_input(
    binding: dict[str, str],
    *,
    source: InputSource,
    input_kind: str,
    title: str,
    summary: str = "",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        {
            "category": "input",
            "source": source,
            "input_kind": input_kind,
            "title": title,
            "summary": _truncate(summary),
            "detail": detail or {},
            "display_title": f"{_INPUT_SOURCE_LABELS.get(source, source)} · {title}",
        },
    )


def record_output(
    binding: dict[str, str],
    *,
    output_kind: str,
    title: str,
    summary: str = "",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        {
            "category": "output",
            "output_kind": output_kind,
            "title": title,
            "summary": _truncate(summary),
            "detail": detail or {},
            "display_title": title,
        },
    )


def record_tool(
    binding: dict[str, str],
    *,
    tool_name: str,
    tool_input: Any = None,
    result_preview: str = "",
    success: bool = True,
    duration_ms: int | None = None,
) -> dict[str, Any] | None:
    name = (tool_name or "").strip()
    if not name:
        return None
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        {
            "category": "tool",
            "tool_name": name,
            "tool_input": _safe_json(tool_input),
            "result_preview": _truncate(result_preview),
            "success": bool(success),
            "duration_ms": duration_ms,
            "display_title": name,
        },
    )


def record_skill(
    binding: dict[str, str],
    *,
    skill_name: str,
    skill_tool: str,
    script_name: str = "",
    result_preview: str = "",
    success: bool = True,
    duration_ms: int | None = None,
) -> dict[str, Any] | None:
    sname = (skill_name or "").strip()
    if not sname:
        return None
    title = sname
    if script_name:
        title = f"{sname} / {script_name}"
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        {
            "category": "skill",
            "skill_name": sname,
            "skill_tool": (skill_tool or "").strip(),
            "script_name": (script_name or "").strip(),
            "result_preview": _truncate(result_preview),
            "success": bool(success),
            "duration_ms": duration_ms,
            "display_title": title,
        },
    )


def try_record_tool_from_agent(
    agent: Any,
    *,
    tool_name: str,
    tool_input: Any,
    result_preview: str,
    success: bool,
    duration_ms: int | None,
) -> None:
    """Agent 工具循环内调用：会议室上下文存在则落盘 tool + skill。"""
    if not getattr(agent, "_org_context", False):
        return
    binding = resolve_agent_activity_binding(agent)
    if not binding:
        return
    name = (tool_name or "").strip()
    if not name:
        return
    try:
        record_tool(
            binding,
            tool_name=name,
            tool_input=tool_input,
            result_preview=result_preview,
            success=success,
            duration_ms=duration_ms,
        )
        if name in _SKILL_TOOLS:
            skill_name = ""
            script_name = ""
            if isinstance(tool_input, dict):
                skill_name = str(tool_input.get("skill_name") or "").strip()
                script_name = str(tool_input.get("script_name") or "").strip()
            if skill_name:
                record_skill(
                    binding,
                    skill_name=skill_name,
                    skill_tool=name,
                    script_name=script_name,
                    result_preview=result_preview,
                    success=success,
                    duration_ms=duration_ms,
                )
    except Exception as exc:
        logger.debug("try_record_tool_from_agent failed: %s", exc)


def try_record_output_from_agent(
    agent: Any,
    *,
    output_kind: str,
    title: str,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> None:
    if not getattr(agent, "_org_context", False):
        return
    binding = resolve_agent_activity_binding(agent)
    if not binding:
        return
    try:
        record_output(
            binding,
            output_kind=output_kind,
            title=title,
            summary=summary,
            detail=detail,
        )
    except Exception as exc:
        logger.debug("try_record_output_from_agent failed: %s", exc)


def read_activity_log(
    scope_id: str,
    node_id: str,
    profile_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    path = _activity_path(scope_id, node_id, profile_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    except OSError as exc:
        logger.warning("read_activity_log failed %s: %s", path, exc)
        return []
    if len(rows) > limit:
        return rows[-limit:]
    return rows


def aggregate_tools_and_skills(entries: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    tools: list[str] = []
    skills: list[dict[str, Any]] = []
    skill_seen: set[str] = set()
    for row in entries:
        cat = str(row.get("category") or "")
        if cat == "tool":
            name = str(row.get("tool_name") or "").strip()
            if name and name not in tools:
                tools.append(name)
        elif cat == "skill":
            sname = str(row.get("skill_name") or "").strip()
            if not sname:
                continue
            key = "|".join([sname, str(row.get("skill_tool") or ""), str(row.get("script_name") or "")])
            if key in skill_seen:
                continue
            skill_seen.add(key)
            ts_raw = row.get("ts") or ""
            try:
                ts = datetime.fromisoformat(str(ts_raw)).timestamp()
            except (TypeError, ValueError):
                ts = 0.0
            skills.append(
                {
                    "skill": sname,
                    "tool": str(row.get("skill_tool") or ""),
                    "script": str(row.get("script_name") or "") or None,
                    "ts": ts,
                }
            )
    return tools, skills


def enrich_display(entry: dict[str, Any]) -> dict[str, Any]:
    """为前端补充展示字段。"""
    row = dict(entry)
    cat = str(row.get("category") or "")
    row.setdefault("category_label", _CATEGORY_LABELS.get(cat, cat))
    if cat == "input":
        src = str(row.get("source") or "")
        row.setdefault("source_label", _INPUT_SOURCE_LABELS.get(src, src))
    if not row.get("display_title"):
        if cat == "tool":
            row["display_title"] = str(row.get("tool_name") or "工具")
        elif cat == "skill":
            sn = str(row.get("skill_name") or "")
            sc = str(row.get("script_name") or "")
            row["display_title"] = f"{sn} / {sc}" if sc else sn
        elif cat == "output":
            row["display_title"] = str(row.get("title") or "产出")
        elif cat == "input":
            row["display_title"] = str(row.get("title") or "输入")
    return row


def list_node_agent_profiles(scope_id: str, node_id: str) -> list[str]:
    """列出某节点下已有活动目录的 profile_id。"""
    root = agent_sop_node_dir(scope_id, node_id)
    if not root.is_dir():
        return []
    out: list[str] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "activity.jsonl").is_file():
            out.append(child.name)
    return out
