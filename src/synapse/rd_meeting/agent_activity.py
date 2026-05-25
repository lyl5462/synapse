"""研发会议室：智能体节点级活动埋点（输入 / 输出 / 工具 / 技能）。

落盘路径（用户约定）::

    work/<scope>/agents/<node_id>/<profile_id>/activity.jsonl

每条记录为 JSON 一行，``category`` 取 ``input`` | ``output`` | ``tool`` | ``skill_load`` | ``skill_load_blocked`` | ``skill_exec``
（旧数据可能仍为 ``skill``，读取时会按 ``skill_tool`` 归一化）。
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

ActivityCategory = Literal[
    "input", "output", "tool", "skill_load", "skill_load_blocked", "skill_exec", "skill"
]
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
_SKILL_LOAD_TOOLS = frozenset(
    {
        "get_skill_info",
        "get_skill_reference",
        "read_skill_file",
        "reload_skill",
        "unload_skill",
    }
)
_SKILL_EXEC_TOOLS = frozenset({"run_skill_script"})
# instruction-only 技能加载后，下列工具调用视为在该技能上下文中执行
_SKILL_CONTEXT_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "run_shell",
        "grep",
        "glob",
        "list_dir",
    }
)

_CATEGORY_LABELS: dict[str, str] = {
    "input": "接收输入",
    "output": "产出反馈",
    "tool": "调用工具",
    "skill_load": "加载技能",
    "skill_load_blocked": "技能加载被拦截",
    "skill_exec": "执行技能",
    "skill": "调用技能",  # 旧数据兼容
}

_TODO_BLOCK_MARKERS = ("建议先创建 Todo", "这是一个多步骤任务，建议先创建 Todo")
_INSTRUCTION_ONLY_SCRIPT = "instruction-only"

_SKILL_TOOL_LABELS: dict[str, str] = {
    "get_skill_info": "加载技能说明",
    "get_skill_reference": "加载技能参考",
    "read_skill_file": "读取技能文件",
    "run_skill_script": "执行技能脚本",
    "reload_skill": "重载技能",
    "unload_skill": "卸载技能",
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


def _skill_activity_category(skill_tool: str) -> str:
    tool = (skill_tool or "").strip()
    if tool in _SKILL_EXEC_TOOLS:
        return "skill_exec"
    if tool in _SKILL_LOAD_TOOLS:
        return "skill_load"
    return "skill_load"


def _normalize_category(row: dict[str, Any]) -> str:
    cat = str(row.get("category") or "")
    if cat == "skill":
        return _skill_activity_category(str(row.get("skill_tool") or ""))
    if cat == "skill_load" and is_todo_block_preview(str(row.get("result_preview") or "")):
        return "skill_load_blocked"
    return cat


def _category_label_for_row(row: dict[str, Any]) -> str:
    cat = _normalize_category(row)
    if cat == "skill_load_blocked":
        return _CATEGORY_LABELS["skill_load_blocked"]
    skill_tool = str(row.get("skill_tool") or "").strip()
    if cat == "skill_load" and skill_tool and is_todo_block_preview(str(row.get("result_preview") or "")):
        return _CATEGORY_LABELS["skill_load_blocked"]
    if cat in ("skill_load", "skill_exec", "skill") and skill_tool:
        return _SKILL_TOOL_LABELS.get(skill_tool, _CATEGORY_LABELS.get(cat, cat))
    return _CATEGORY_LABELS.get(cat, cat)


def is_todo_block_preview(result_preview: str) -> bool:
    """Todo 门禁拦截时 tool_executor 返回的固定提示文案。"""
    preview = str(result_preview or "")
    return any(marker in preview for marker in _TODO_BLOCK_MARKERS)


def _result_indicates_failure(tool_name: str, result_preview: str) -> bool:
    preview = str(result_preview or "").lstrip()
    if not preview:
        return False
    if is_todo_block_preview(preview):
        return True
    if preview.startswith("❌"):
        return True
    if tool_name == "run_skill_script" and "脚本执行失败" in preview[:300]:
        return True
    return False


def infer_tool_success(tool_name: str, result_preview: str, success: bool) -> bool:
    """根据工具返回文本修正 success（execute_tool 常把失败当字符串返回）。"""
    if not success:
        return False
    return not _result_indicates_failure(tool_name, result_preview)


def _get_executing_skill(agent: Any) -> str:
    return str(getattr(agent, "_rd_meeting_executing_skill", "") or "").strip()


def _get_executing_script(agent: Any) -> str:
    return str(getattr(agent, "_rd_meeting_executing_script", "") or "").strip()


def _set_executing_skill(agent: Any, skill_name: str) -> None:
    name = (skill_name or "").strip()
    try:
        agent._rd_meeting_executing_skill = name  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("set executing skill failed: %s", exc)


def _set_executing_script(agent: Any, script_name: str) -> None:
    name = (script_name or "").strip()
    try:
        agent._rd_meeting_executing_script = name  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("set executing script failed: %s", exc)


def _clear_executing_skill(agent: Any) -> None:
    _set_executing_skill(agent, "")
    _set_executing_script(agent, "")


def _maybe_set_executing_skill_from_load(
    agent: Any,
    *,
    skill_tool: str,
    skill_name: str,
    result_preview: str,
    success: bool,
) -> None:
    if not success or skill_tool != "get_skill_info":
        return
    if not (skill_name or "").strip():
        return
    preview_lower = str(result_preview or "").lower()
    if "instruction-only" in preview_lower or "no executable scripts" in preview_lower:
        _set_executing_skill(agent, skill_name)
        _set_executing_script(agent, _INSTRUCTION_ONLY_SCRIPT)


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


def resolve_binding_for_profile(
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
    executing_skill_id: str = "",
    executing_script_name: str = "",
) -> dict[str, Any] | None:
    name = (tool_name or "").strip()
    if not name:
        return None
    esid = (executing_skill_id or "").strip()
    escript = (executing_script_name or "").strip()
    display_title = esid if esid else name
    row: dict[str, Any] = {
        "category": "tool",
        "tool_name": name,
        "tool_input": _safe_json(tool_input),
        "result_preview": _truncate(result_preview),
        "success": bool(success),
        "duration_ms": duration_ms,
        "display_title": display_title,
    }
    if esid:
        row["executing_skill_id"] = esid
    if escript:
        row["executing_script_name"] = escript
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        row,
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
    stool = (skill_tool or "").strip()
    scname = (script_name or "").strip()
    category = _skill_activity_category(stool)
    label = _SKILL_TOOL_LABELS.get(stool, _CATEGORY_LABELS.get(category, category))
    row: dict[str, Any] = {
        "category": category,
        "skill_name": sname,
        "skill_tool": stool,
        "script_name": scname,
        "result_preview": _truncate(result_preview),
        "success": bool(success),
        "duration_ms": duration_ms,
        "display_title": sname,
        "category_label": label,
    }
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        row,
    )


def record_skill_load_blocked(
    binding: dict[str, str],
    *,
    skill_name: str,
    skill_tool: str,
    result_preview: str = "",
    duration_ms: int | None = None,
    block_reason: str = "todo_required",
) -> dict[str, Any] | None:
    sname = (skill_name or "").strip()
    if not sname:
        return None
    stool = (skill_tool or "").strip()
    return _append_row(
        binding["scope_id"],
        binding["node_id"],
        binding["profile_id"],
        {
            "category": "skill_load_blocked",
            "skill_name": sname,
            "skill_tool": stool,
            "block_reason": block_reason,
            "result_preview": _truncate(result_preview),
            "success": False,
            "duration_ms": duration_ms,
            "display_title": sname,
            "category_label": _CATEGORY_LABELS["skill_load_blocked"],
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
        success = infer_tool_success(name, result_preview, success)
        if name in _SKILL_TOOLS:
            skill_name = ""
            script_name = ""
            if isinstance(tool_input, dict):
                skill_name = str(tool_input.get("skill_name") or "").strip()
                script_name = str(tool_input.get("script_name") or "").strip()
            if skill_name:
                if is_todo_block_preview(result_preview):
                    record_skill_load_blocked(
                        binding,
                        skill_name=skill_name,
                        skill_tool=name,
                        result_preview=result_preview,
                        duration_ms=duration_ms,
                    )
                    return
                if name == "run_skill_script":
                    _clear_executing_skill(agent)
                elif name == "get_skill_info" and success:
                    _maybe_set_executing_skill_from_load(
                        agent,
                        skill_tool=name,
                        skill_name=skill_name,
                        result_preview=result_preview,
                        success=success,
                    )
                # 技能类工具只记 skill 行，避免与 tool 行重复展示（如 get_skill_info + 同名技能）
                record_skill(
                    binding,
                    skill_name=skill_name,
                    skill_tool=name,
                    script_name=script_name,
                    result_preview=result_preview,
                    success=success,
                    duration_ms=duration_ms,
                )
                return
        executing_skill = ""
        executing_script = ""
        if name in _SKILL_CONTEXT_TOOLS:
            executing_skill = _get_executing_skill(agent)
            executing_script = _get_executing_script(agent)
        record_tool(
            binding,
            tool_name=name,
            tool_input=tool_input,
            result_preview=result_preview,
            success=success,
            duration_ms=duration_ms,
            executing_skill_id=executing_skill,
            executing_script_name=executing_script,
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


def _append_skill_aggregate(
    skills: list[dict[str, Any]],
    skill_seen: set[str],
    *,
    skill_name: str,
    tool_name: str,
    script_name: str = "",
    ts_raw: Any = "",
    kind: str = "exec",
) -> None:
    sname = (skill_name or "").strip()
    if not sname:
        return
    key = "|".join([kind, sname, tool_name, script_name])
    if key in skill_seen:
        return
    skill_seen.add(key)
    try:
        ts = datetime.fromisoformat(str(ts_raw)).timestamp()
    except (TypeError, ValueError):
        ts = 0.0
    entry: dict[str, Any] = {
        "skill": sname,
        "tool": tool_name,
        "script": script_name or None,
        "ts": ts,
        "kind": kind,
    }
    skills.append(entry)


def aggregate_tools_and_skills(entries: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    tools: list[str] = []
    skills: list[dict[str, Any]] = []
    skill_seen: set[str] = set()
    for row in entries:
        cat = _normalize_category(row)
        ts_raw = row.get("ts") or ""
        if cat == "tool":
            name = str(row.get("tool_name") or "").strip()
            if name and name not in tools:
                tools.append(name)
            esid = str(row.get("executing_skill_id") or "").strip()
            if esid:
                escript = str(row.get("executing_script_name") or "").strip()
                _append_skill_aggregate(
                    skills,
                    skill_seen,
                    skill_name=esid,
                    tool_name=name,
                    script_name=escript,
                    ts_raw=ts_raw,
                    kind="instruction",
                )
        elif cat == "skill_exec":
            sname = str(row.get("skill_name") or "").strip()
            _append_skill_aggregate(
                skills,
                skill_seen,
                skill_name=sname,
                tool_name=str(row.get("skill_tool") or ""),
                script_name=str(row.get("script_name") or ""),
                ts_raw=ts_raw,
                kind="exec",
            )
        elif cat == "skill_load":
            sname = str(row.get("skill_name") or "").strip()
            _append_skill_aggregate(
                skills,
                skill_seen,
                skill_name=sname,
                tool_name=str(row.get("skill_tool") or ""),
                ts_raw=ts_raw,
                kind="load",
            )
    return tools, skills


def enrich_display(entry: dict[str, Any]) -> dict[str, Any]:
    """为前端补充展示字段。"""
    row = dict(entry)
    normalized = _normalize_category(row)
    if normalized != row.get("category"):
        row["category"] = normalized
    if normalized == "skill_load_blocked":
        row["success"] = False
    row.setdefault("category_label", _category_label_for_row(row))
    if normalized == "input":
        src = str(row.get("source") or "")
        row.setdefault("source_label", _INPUT_SOURCE_LABELS.get(src, src))
    # display_title 仅保留技能名或工具名，链式关系由前端用 executing_skill_id + tool_name 组合展示
    esid = str(row.get("executing_skill_id") or "").strip()
    if normalized == "tool":
        row["display_title"] = esid if esid else str(row.get("tool_name") or row.get("display_title") or "工具")
    elif normalized in ("skill_load", "skill_exec", "skill", "skill_load_blocked"):
        row["display_title"] = str(row.get("skill_name") or row.get("display_title") or "")
    elif not row.get("display_title"):
        if normalized == "output":
            row["display_title"] = str(row.get("title") or "产出")
        elif normalized == "input":
            row["display_title"] = str(row.get("title") or "输入")
    row.pop("chain_label", None)
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
