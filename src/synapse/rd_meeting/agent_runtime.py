"""研发会议室 Agent 运行时：任务级工具白名单 + Profile 技能预注入（对齐产品知识生成）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from synapse.agents.profile import AgentProfile, SkillsMode

logger = logging.getLogger(__name__)

MeetingRole = Literal["host", "worker"]

# 任务级工具白名单（与 dev_iwhalecloud_knowledge 的 _slim_tools 同思路；不含 list_skills）
MEETING_COMMON_TOOL_NAMES: frozenset[str] = frozenset(
    {
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


def collect_skill_body_blocks(agent: Any, skill_ids: list[str]) -> list[str]:
    """读取 SKILL.md 正文块（与产品知识生成 task 内 skill_bodies 格式对齐）。"""
    if not skill_ids:
        return []
    loader = getattr(agent, "skill_loader", None)
    blocks: list[str] = []
    seen: set[str] = set()
    for sid in skill_ids:
        key = (sid or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        skill = loader.get_skill(key) if loader else None
        if skill is None:
            reg = getattr(agent, "skill_registry", None)
            if reg is not None:
                entry = reg.get(key)
                if entry is not None and hasattr(entry, "get_body"):
                    body = entry.get_body() or ""
                    if body.strip():
                        skill_dir = str(getattr(entry, "skill_dir", "") or "")
                        path_line = f"**技能路径**: {skill_dir}\n\n" if skill_dir else ""
                        blocks.append(f"### 研发技能：{key}\n\n{path_line}{body}")
            continue
        body = getattr(skill, "body", None) or ""
        if not str(body).strip():
            continue
        skill_dir = str(getattr(skill, "skill_dir", "") or "")
        path_line = f"**技能路径**: {skill_dir}\n\n" if skill_dir else ""
        blocks.append(f"### 研发技能：{key}\n\n{path_line}{body}")
    return blocks


def format_meeting_skill_guidance_section(skill_bodies: list[str]) -> str:
    if not skill_bodies:
        return ""
    return (
        "\n\n---\n## 已挂载技能（SKILL 全文，请严格遵照执行）\n\n"
        + "\n\n---\n\n".join(skill_bodies)
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
    """在会议室 base system 上追加技能全文，并裁剪工具。返回最终 system prompt。"""
    skill_ids = skill_ids_from_profile(profile)
    bodies = collect_skill_body_blocks(agent, skill_ids)
    full = (base_system_prompt or "").rstrip() + format_meeting_skill_guidance_section(bodies)
    apply_meeting_slim_tools(agent, role)
    return full
