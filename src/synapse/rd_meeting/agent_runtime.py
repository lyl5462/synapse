"""研发会议室 Agent 运行时：任务级工具白名单 + Profile 技能摘要预注入。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from synapse.agents.profile import AgentProfile, SkillsMode

logger = logging.getLogger(__name__)

MeetingRole = Literal["host", "worker"]

# Todo 四件套（Agent 模式任务跟踪；Plan 模式工具 create_plan_file / exit_plan_mode 不暴露）
MEETING_TODO_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_todo",
        "update_todo_step",
        "get_todo_status",
        "complete_todo",
    }
)

# 任务级工具白名单（与 dev_iwhalecloud_knowledge 的 _slim_tools 同思路；不含 list_skills）
MEETING_COMMON_TOOL_NAMES: frozenset[str] = frozenset(
    {
        *MEETING_TODO_TOOL_NAMES,
        "run_shell",
        "read_file",
        "write_file",
        "list_directory",
        "get_skill_info",
        "run_skill_script",
        "get_skill_reference",
        "web_search",
    }
)

MEETING_HOST_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "delegate_to_agent",
        "delegate_parallel",
        "send_agent_message",
        "submit_meeting_work_plan",
        "submit_hitl_questionnaire",
    }
)

MEETING_WORKER_EXTRA_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "deliver_artifacts",
    }
)


def meeting_tool_names_for_role(role: MeetingRole) -> frozenset[str]:
    names = set(MEETING_COMMON_TOOL_NAMES)
    if role == "host":
        names |= MEETING_HOST_ONLY_TOOL_NAMES
    else:
        names |= MEETING_WORKER_EXTRA_TOOL_NAMES
    return frozenset(names)


def skill_ids_from_profile(profile: AgentProfile | None) -> list[str]:
    """从 Profile 解析本会话应预注入的 skill_id 列表。"""
    if profile is None:
        return []
    raw = [str(s).strip() for s in (profile.skills or []) if str(s).strip()]
    if not raw:
        return []
    if profile.skills_mode == SkillsMode.EXCLUSIVE:
        # 会议室预注入只支持「明确列出要用的技能」
        return []
    return _ensure_whalecloud_base_scripts(raw)


def _ensure_whalecloud_base_scripts(skill_ids: list[str]) -> list[str]:
    """含 whalecloud 研发技能时自动挂载共享脚本技能（与产品知识生成一致）。"""
    try:
        from synapse.utils.whaleclouddevtool import (
            WHALECLOUD_BASE_SCRIPTS_SKILL_ID,
            is_whalecloud_dev_tool_skill_id,
        )
    except Exception:
        return list(skill_ids)
    out = list(skill_ids)
    if any(is_whalecloud_dev_tool_skill_id(s) for s in out):
        base = WHALECLOUD_BASE_SCRIPTS_SKILL_ID
        if base not in out:
            out.append(base)
    return out


def _format_summary_block(*, skill_id: str, lines: list[str]) -> str:
    return f"### {skill_id}\n\n" + "\n".join(lines)


def _summary_lines_from_entry(entry: Any) -> list[str]:
    from synapse.skills.exposure import build_skill_exposure

    exposed = build_skill_exposure(entry)
    display = entry.get_display_name() if hasattr(entry, "get_display_name") else entry.name
    desc = entry.get_display_description() if hasattr(entry, "get_display_description") else entry.description
    lines = [f"- **名称**: {display}"]
    label = getattr(entry, "label", None)
    if label and str(label).strip():
        lines.append(f"- **标签**: {str(label).strip()}")
    if desc and str(desc).strip():
        lines.append(f"- **摘要**: {str(desc).strip()}")
    when = getattr(entry, "when_to_use", "") or ""
    if str(when).strip():
        lines.append(f"- **何时使用**: {str(when).strip()}")
    if exposed.scripts:
        lines.append(f"- **脚本**: {', '.join(exposed.scripts)}")
    else:
        lines.append(
            "- **类型**: instruction-only（无预置脚本；须先 get_skill_info 再按指引 run_shell / 读写文件）"
        )
    lines.append(f'- **完整指引**: 执行前调用 `get_skill_info("{entry.skill_id}")` 加载 SKILL.md')
    return lines


def _summary_lines_from_parsed(skill_id: str, parsed: Any) -> list[str]:
    meta = getattr(parsed, "metadata", None)
    if meta is None:
        return [
            "- **摘要**: （元数据不可用）",
            f'- **完整指引**: `get_skill_info("{skill_id}")`',
        ]
    name = getattr(meta, "name", skill_id) or skill_id
    desc = getattr(meta, "description", "") or ""
    when = getattr(meta, "when_to_use", "") or ""
    lines = [f"- **名称**: {name}"]
    if str(desc).strip():
        lines.append(f"- **摘要**: {str(desc).strip()}")
    if str(when).strip():
        lines.append(f"- **何时使用**: {str(when).strip()}")
    lines.append(f'- **完整指引**: 执行前调用 `get_skill_info("{skill_id}")` 加载 SKILL.md')
    return lines


def collect_skill_summary_blocks(agent: Any, skill_ids: list[str]) -> list[str]:
    """仅注入 L1 元数据摘要，不加载 SKILL.md 正文（L2 由 get_skill_info 按需加载）。"""
    if not skill_ids:
        return []
    registry = getattr(agent, "skill_registry", None)
    loader = getattr(agent, "skill_loader", None)
    blocks: list[str] = []
    seen: set[str] = set()

    for sid in skill_ids:
        key = (sid or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)

        entry = registry.get(key) if registry is not None else None
        if entry is not None:
            blocks.append(_format_summary_block(skill_id=key, lines=_summary_lines_from_entry(entry)))
            continue

        parsed = loader.get_skill(key) if loader is not None else None
        if parsed is not None:
            blocks.append(
                _format_summary_block(skill_id=key, lines=_summary_lines_from_parsed(key, parsed))
            )
            continue

        blocks.append(
            _format_summary_block(
                skill_id=key,
                lines=[
                    "- **摘要**: （注册表中未找到该技能）",
                    f'- **完整指引**: `get_skill_info("{key}")`',
                ],
            )
        )
    return blocks


def format_meeting_skill_guidance_section(skill_summaries: list[str]) -> str:
    if not skill_summaries:
        return ""
    return (
        "\n\n---\n## 已挂载技能（摘要）\n\n"
        "以下为 Profile 挂载技能的元数据摘要；**执行前**须对将要使用的 skill_id 调用 "
        "`get_skill_info(skill_id)` 加载完整 SKILL.md，再按指引调用 `run_skill_script` 或 shell / 读写工具。\n\n"
        + "\n\n---\n\n".join(skill_summaries)
    )


def apply_meeting_slim_tools(agent: Any, role: MeetingRole) -> None:
    """任务级裁剪工具列表；首次裁剪前保存 _meeting_orig_tools 供会议结束后恢复。"""
    allowed = meeting_tool_names_for_role(role)
    orig_tools = getattr(agent, "_tools", None)
    if orig_tools is None:
        return
    if getattr(agent, "_meeting_orig_tools", None) is None:
        agent._meeting_orig_tools = list(orig_tools)  # type: ignore[attr-defined]
    base = agent._meeting_orig_tools  # type: ignore[attr-defined]
    slim = [t for t in base if (t.get("name") or "") in allowed]
    agent._tools = slim  # type: ignore[attr-defined]
    try:
        from synapse.tools.catalog import ToolCatalog

        agent.tool_catalog = ToolCatalog(slim)
        pa = getattr(agent, "prompt_assembler", None)
        if pa is not None:
            pa._tool_catalog = agent.tool_catalog
    except Exception as exc:
        logger.debug("apply_meeting_slim_tools catalog sync failed: %s", exc)
    logger.info(
        "Meeting slim tools applied: role=%s allowed=%d remaining=%d",
        role,
        len(allowed),
        len(slim),
    )


def restore_meeting_slim_tools(agent: Any) -> None:
    """恢复会议前工具列表（池化 Agent 离开会议室时调用）。"""
    orig = getattr(agent, "_meeting_orig_tools", None)
    if orig is None:
        return
    agent._tools = list(orig)  # type: ignore[attr-defined]
    agent._meeting_orig_tools = None  # type: ignore[attr-defined]
    try:
        from synapse.tools.catalog import ToolCatalog

        agent.tool_catalog = ToolCatalog(agent._tools)
        pa = getattr(agent, "prompt_assembler", None)
        if pa is not None:
            pa._tool_catalog = agent.tool_catalog
    except Exception as exc:
        logger.debug("restore_meeting_slim_tools catalog sync failed: %s", exc)


def apply_meeting_agent_runtime(
    agent: Any,
    *,
    role: MeetingRole,
    profile: AgentProfile | None,
    base_system_prompt: str,
) -> str:
    """在会议室 base system 上追加技能摘要，并裁剪工具。返回最终 system prompt。"""
    skill_ids = skill_ids_from_profile(profile)
    summaries = collect_skill_summary_blocks(agent, skill_ids)
    full = (base_system_prompt or "").rstrip() + format_meeting_skill_guidance_section(summaries)
    apply_meeting_slim_tools(agent, role)
    return full
