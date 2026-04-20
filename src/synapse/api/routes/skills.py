"""
Skills route: GET /api/skills, POST /api/skills/config, GET /api/skills/marketplace

技能列表与配置管理。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 前端与约定：研发流程类技能的工具名前缀（参见 WORKSPACE SKILL.md tool_name）
DEV_TOOL_TOOL_PREFIX = "whalecloud_dev_tool_"

_DEV_TOOL_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def sanitize_dev_tool_slug(raw: str) -> str | None:
    """Validate user slug for whalecloud-dev-tool-{slug} folder names."""
    s = (raw or "").strip().lower()
    if len(s) < 2 or len(s) > 48:
        return None
    if _DEV_TOOL_SLUG_RE.fullmatch(s) is None:
        return None
    return s


def _merge_external_allowlist_add(skill_id: str) -> None:
    """If data/skills.json uses an explicit external_allowlist list, append skill_id."""
    try:
        from synapse.config import settings

        base = settings.project_root
    except Exception:
        base = Path.cwd()
    cfg_path = base / "data" / "skills.json"
    if not cfg_path.exists():
        return
    try:
        raw = cfg_path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    al = data.get("external_allowlist", None)
    if not isinstance(al, list):
        return
    ids = {str(x).strip() for x in al if str(x).strip()}
    if skill_id in ids:
        return
    data["external_allowlist"] = list(al) + [skill_id]
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _notify_skills_changed(action: str = "reload") -> None:
    """Fire-and-forget WS broadcast for skill state changes."""
    try:
        from synapse.api.routes.websocket import broadcast_event

        asyncio.ensure_future(broadcast_event("skills:changed", {"action": action}))
    except Exception:
        pass


router = APIRouter()

SKILLS_SH_API = "https://skills.sh/api/search"


_skills_cache: dict | None = None
"""Module-level cache for GET /api/skills response.
Populated on first request, invalidated by install/uninstall/reload/edit."""


def _invalidate_skills_cache() -> None:
    """Clear the cached skill list so the next GET /api/skills re-scans disk."""
    global _skills_cache
    _skills_cache = None


def _read_external_allowlist() -> tuple[Path, set[str] | None]:
    """Read external_allowlist from data/skills.json.

    Returns (base_path, allowlist). allowlist is None when the file doesn't
    exist or has no external_allowlist key (meaning "all external skills enabled").
    """
    import json

    try:
        from synapse.config import settings

        base_path = settings.project_root
    except Exception:
        base_path = Path.cwd()

    external_allowlist: set[str] | None = None
    try:
        cfg_path = base_path / "data" / "skills.json"
        if cfg_path.exists():
            raw = cfg_path.read_text(encoding="utf-8")
            cfg = json.loads(raw) if raw.strip() else {}
            al = cfg.get("external_allowlist", None)
            if isinstance(al, list):
                external_allowlist = {str(x).strip() for x in al if str(x).strip()}
    except Exception:
        pass
    return base_path, external_allowlist


def _apply_allowlist_and_rebuild_catalog(request: Request) -> int:
    """Re-read skills.json allowlist, prune agent's loader & registry, rebuild catalog.

    Call this after any operation that changes loaded skills or the allowlist.
    Returns the number of pruned external skills.
    """
    from synapse.core.agent import Agent

    agent = getattr(request.app.state, "agent", None)
    actual_agent = agent
    if not isinstance(agent, Agent):
        actual_agent = getattr(agent, "_local_agent", None)
    if actual_agent is None:
        return 0

    _, external_allowlist = _read_external_allowlist()

    loader = getattr(actual_agent, "skill_loader", None)
    removed = 0
    if loader:
        from synapse.skills.preset_utils import collect_preset_referenced_skills

        effective = loader.compute_effective_allowlist(external_allowlist)
        agent_skills = collect_preset_referenced_skills()
        removed = loader.prune_external_by_allowlist(
            effective, agent_referenced_skills=agent_skills
        )

    catalog = getattr(actual_agent, "skill_catalog", None)
    if catalog:
        catalog.invalidate_cache()
        new_text = catalog.generate_catalog()
        if hasattr(actual_agent, "_skill_catalog_text"):
            actual_agent._skill_catalog_text = new_text

    # 同步系统技能的 tool_name → handler 映射到 handler_registry
    if hasattr(actual_agent, "_update_skill_tools"):
        actual_agent._update_skill_tools()

    # 通知所有 Agent 池技能已变更，使池中旧 Agent 在下次使用时重建
    _notify_pools_skills_changed(request)

    return removed


def _notify_pools_skills_changed(request: Request) -> None:
    """通知所有 Agent 实例池全局技能已变更。"""
    for pool_attr in ("agent_pool", "orchestrator"):
        obj = getattr(request.app.state, pool_attr, None)
        if obj is None:
            continue
        pool = getattr(obj, "_pool", obj)
        if hasattr(pool, "notify_skills_changed"):
            try:
                pool.notify_skills_changed()
            except Exception as e:
                logger.warning(f"Failed to notify pool ({pool_attr}): {e}")


async def _auto_translate_new_skills(request: Request, install_url: str) -> None:
    """安装后为缺少 i18n 翻译的技能自动生成中文翻译（写入 agents/openai.yaml）。

    翻译失败不影响安装结果，仅记录日志。
    """
    from synapse.core.agent import Agent

    try:
        agent = getattr(request.app.state, "agent", None)
        actual_agent = agent
        if not isinstance(agent, Agent):
            actual_agent = getattr(agent, "_local_agent", None)
        if actual_agent is None:
            return

        brain = getattr(actual_agent, "brain", None)
        registry = getattr(actual_agent, "skill_registry", None)
        if not brain or not registry:
            return

        from synapse.skills.i18n import auto_translate_skill

        for skill in registry.list_all():
            if skill.name_i18n:
                continue
            if not skill.skill_path:
                continue
            skill_dir = Path(skill.skill_path).parent
            if not skill_dir.exists():
                continue
            await auto_translate_skill(
                skill_dir,
                skill.name,
                skill.description,
                brain,
            )
    except Exception as e:
        logger.warning(f"Auto-translate after install failed: {e}")


@router.get("/api/skills")
async def list_skills(request: Request):
    """List all available skills with their config schemas.

    Returns ALL discovered skills (including disabled ones) with correct
    ``enabled`` status derived from ``data/skills.json`` allowlist.

    Uses a module-level cache to avoid re-scanning disk on every request.
    The cache is invalidated by install/uninstall/reload/edit operations.
    """
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache

    base_path, external_allowlist = _read_external_allowlist()

    # load_all() does synchronous file I/O — run in a thread to avoid blocking
    # the event loop.
    try:
        from synapse.skills.loader import SkillLoader

        loader = SkillLoader()
        await asyncio.to_thread(loader.load_all, base_path=base_path)
        all_skills = loader.registry.list_all()
        effective_allowlist = loader.compute_effective_allowlist(external_allowlist)
    except Exception:
        from synapse.core.agent import Agent

        agent = getattr(request.app.state, "agent", None)
        actual_agent = agent
        if not isinstance(agent, Agent):
            actual_agent = getattr(agent, "_local_agent", None)
        if actual_agent is None:
            return {"skills": []}
        registry = getattr(actual_agent, "skill_registry", None)
        if registry is None:
            return {"skills": []}
        all_skills = registry.list_all()
        effective_allowlist = external_allowlist

    skills = []
    for skill in all_skills:
        config = None
        parsed = getattr(skill, "_parsed_skill", None)
        if parsed and hasattr(parsed, "metadata"):
            config = getattr(parsed.metadata, "config", None) or None

        is_system = bool(skill.system)
        sid = getattr(skill, "skill_id", skill.name)
        is_enabled = is_system or effective_allowlist is None or sid in effective_allowlist

        relative_path = None
        if skill.skill_path:
            try:
                relative_path = str(Path(skill.skill_path).relative_to(base_path))
            except (ValueError, TypeError):
                relative_path = sid

        tool_nm = getattr(skill, "tool_name", None) or ""
        out_category = skill.category
        if tool_nm.startswith(DEV_TOOL_TOOL_PREFIX):
            out_category = "研发工具"

        skills.append(
            {
                "skill_id": sid,
                "capability_id": getattr(skill, "capability_id", ""),
                "namespace": getattr(skill, "namespace", ""),
                "origin": getattr(skill, "origin", "project"),
                "visibility": getattr(skill, "visibility", "public"),
                "permission_profile": getattr(skill, "permission_profile", ""),
                "name": skill.name,
                "description": skill.description,
                "name_i18n": skill.name_i18n or None,
                "description_i18n": skill.description_i18n or None,
                "system": is_system,
                "enabled": is_enabled,
                "category": out_category,
                "tool_name": skill.tool_name,
                "config": config,
                "path": relative_path,
                "source_url": getattr(skill, "source_url", None),
            }
        )

    def _sort_key(s: dict) -> tuple:
        enabled = s.get("enabled", False)
        system = s.get("system", False)
        if enabled and not system:
            tier = 0
        elif enabled and system:
            tier = 1
        else:
            tier = 2
        return (tier, s.get("name", ""))

    skills.sort(key=_sort_key)

    result = {"skills": skills}
    _skills_cache = result
    return result


@router.post("/api/skills/config")
async def update_skill_config(request: Request):
    """Persist skill configuration to data/skill_configs.json."""
    body = await request.json()
    skill_name = body.get("skill_name", "")
    config_values = body.get("config", {})

    if not skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")

    try:
        from synapse.config import settings

        config_file = settings.project_root / "data" / "skill_configs.json"
    except Exception:
        config_file = Path.cwd() / "data" / "skill_configs.json"

    existing: dict = {}
    if config_file.exists():
        try:
            raw = config_file.read_text(encoding="utf-8")
            existing = json.loads(raw) if raw.strip() else {}
        except Exception:
            pass

    existing[skill_name] = config_values
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"status": "ok", "skill": skill_name, "config": config_values}


@router.post("/api/skills/install")
async def install_skill(request: Request):
    """安装技能（远程模式替代 Tauri synapse_install_skill 命令）。

    POST body: { "url": "github:user/repo/skill" }
    安装完成后自动重新加载技能并应用 allowlist。
    """
    import asyncio

    from synapse.core.agent import Agent

    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return {"error": "url is required"}

    try:
        from synapse.config import settings

        workspace_dir = str(settings.project_root)
    except Exception:
        workspace_dir = str(__import__("pathlib").Path.cwd())

    try:
        from synapse.setup_center.bridge import install_skill as _install_skill

        await asyncio.to_thread(_install_skill, workspace_dir, url)
    except FileNotFoundError as e:
        missing = getattr(e, "filename", None) or "外部命令"
        logger.error("Skill install missing dependency: %s", e, exc_info=True)
        return {
            "error": (
                f"安装失败：未找到可执行命令 `{missing}`。"
                "请先安装 Git 并确保在 PATH 中，或改用 GitHub 简写/单个 SKILL.md 链接。"
            )
        }
    except Exception as e:
        logger.error("Skill install failed: %s", e, exc_info=True)
        return {"error": str(e)}

    # 验证安装的技能是否能被 SkillLoader 正确解析
    install_warning = None
    try:
        from synapse.setup_center.bridge import _resolve_skills_dir

        skills_dir = _resolve_skills_dir(workspace_dir)
        # 找到刚安装的技能目录（最新修改的含 SKILL.md 的子目录）
        candidates = sorted(
            (d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            from synapse.skills.parser import SkillParser

            parser = SkillParser()
            try:
                parser.parse_directory(candidates[0])
            except Exception as parse_err:
                import shutil

                skill_dir_name = candidates[0].name
                logger.error(
                    "Installed skill %s has invalid SKILL.md, removing: %s",
                    skill_dir_name,
                    parse_err,
                )
                shutil.rmtree(str(candidates[0]), ignore_errors=True)
                return {
                    "error": (
                        f"技能文件已下载，但 SKILL.md 格式无效，无法加载：{parse_err}。"
                        "该技能可能不兼容 Synapse 格式，已自动清理。"
                    )
                }
    except Exception as ve:
        install_warning = str(ve)
        logger.warning("Post-install validation skipped: %s", ve)

    # 安装成功后：重新加载技能到 agent 运行时，并应用 allowlist
    try:
        agent = getattr(request.app.state, "agent", None)
        actual_agent = agent
        if not isinstance(agent, Agent):
            actual_agent = getattr(agent, "_local_agent", None)

        if actual_agent is not None:
            loader = getattr(actual_agent, "skill_loader", None)
            if loader:
                base_path, _ = _read_external_allowlist()
                loader.load_all(base_path)
            _apply_allowlist_and_rebuild_catalog(request)

            # 自动翻译：为新安装的技能生成 i18n (agents/openai.yaml)
            await _auto_translate_new_skills(request, url)
    except Exception as e:
        logger.warning(f"Post-install reload failed (skill was installed): {e}")

    _invalidate_skills_cache()
    _notify_skills_changed("install")
    result: dict = {"status": "ok", "url": url}
    if install_warning:
        result["warning"] = install_warning
    return result


@router.post("/api/skills/uninstall")
async def uninstall_skill(request: Request):
    """卸载技能。

    POST body: { "skill_id": "skill-directory-name" }
    卸载后自动重新加载技能并刷新 allowlist。
    """
    from synapse.core.agent import Agent

    body = await request.json()
    skill_id = (body.get("skill_id") or "").strip()
    if not skill_id:
        return {"error": "skill_id is required"}

    try:
        from synapse.config import settings

        workspace_dir = str(settings.project_root)
    except Exception:
        workspace_dir = str(__import__("pathlib").Path.cwd())

    try:
        from synapse.setup_center.bridge import uninstall_skill as _uninstall_skill

        await asyncio.to_thread(_uninstall_skill, workspace_dir, skill_id)
    except Exception as e:
        logger.error("Skill uninstall failed: %s", e, exc_info=True)
        return {"error": str(e)}

    try:
        agent = getattr(request.app.state, "agent", None)
        actual_agent = agent
        if not isinstance(agent, Agent):
            actual_agent = getattr(agent, "_local_agent", None)
        if actual_agent is not None:
            loader = getattr(actual_agent, "skill_loader", None)
            if loader:
                loader.unload_skill(skill_id)
                base_path, _ = _read_external_allowlist()
                loader.load_all(base_path)
            _apply_allowlist_and_rebuild_catalog(request)
    except Exception as e:
        logger.warning(f"Post-uninstall reload failed: {e}")

    _invalidate_skills_cache()
    _notify_skills_changed("uninstall")
    return {"status": "ok", "skill_id": skill_id}


@router.post("/api/skills/reload")
async def reload_skills(request: Request):
    """热重载技能（安装新技能后、修改 SKILL.md 后、切换启用/禁用后调用）。

    POST body: { "skill_name": "optional-name" }
    如果 skill_name 为空或未提供，则重新扫描并加载所有技能。
    全量重载后会重新读取 data/skills.json 的 allowlist 并裁剪禁用技能。
    """
    from synapse.core.agent import Agent

    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    skill_name = (body.get("skill_name") or "").strip()

    agent = getattr(request.app.state, "agent", None)
    actual_agent = agent
    if not isinstance(agent, Agent):
        actual_agent = getattr(agent, "_local_agent", None)

    if actual_agent is None:
        return {"error": "Agent not initialized"}

    loader = getattr(actual_agent, "skill_loader", None)
    registry = getattr(actual_agent, "skill_registry", None)
    if not loader or not registry:
        return {"error": "Skill loader/registry not available"}

    try:
        _invalidate_skills_cache()
        if skill_name:
            reloaded = loader.reload_skill(skill_name)
            if reloaded:
                _apply_allowlist_and_rebuild_catalog(request)
                _notify_skills_changed("reload")
                return {"status": "ok", "reloaded": [skill_name]}
            else:
                return {"error": f"Skill '{skill_name}' not found or reload failed"}
        else:
            base_path, _ = _read_external_allowlist()
            loaded_count = loader.load_all(base_path)

            pruned = _apply_allowlist_and_rebuild_catalog(request)
            total = len(registry.list_all())
            _notify_skills_changed("reload")
            return {
                "status": "ok",
                "reloaded": "all",
                "loaded": loaded_count,
                "pruned": pruned,
                "total": total,
            }
    except Exception as e:
        logger.error(f"Skill reload failed: {e}")
        return {"error": str(e)}


@router.get("/api/skills/content/{skill_name:path}")
async def get_skill_content(skill_name: str, request: Request):
    """读取单个技能的 SKILL.md 原始内容。

    返回 { content, path, system } 供前端展示和编辑。
    系统内置技能标记 system=true，前端可据此决定是否允许编辑。
    """
    from synapse.skills.loader import SkillLoader

    base_path, _ = _read_external_allowlist()

    # 优先从 agent 运行时的 loader 中查找（已加载的技能）
    from synapse.core.agent import Agent

    agent = getattr(request.app.state, "agent", None)
    actual_agent = agent if isinstance(agent, Agent) else getattr(agent, "_local_agent", None)

    skill = None
    if actual_agent:
        loader = getattr(actual_agent, "skill_loader", None)
        if loader:
            skill = loader.get_skill(skill_name)

    if not skill:
        # Fallback: 用临时 loader 扫描
        try:
            tmp_loader = SkillLoader()
            tmp_loader.load_all(base_path=base_path)
            skill = tmp_loader.get_skill(skill_name)
        except Exception:
            pass

    if not skill:
        return {"error": f"Skill '{skill_name}' not found"}

    try:
        content = skill.path.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": f"Failed to read SKILL.md: {e}"}

    safe_path = skill_name
    try:
        safe_path = str(Path(skill.path).relative_to(base_path))
    except (ValueError, TypeError):
        pass

    return {
        "content": content,
        "path": safe_path,
        "system": skill.metadata.system,
    }


@router.put("/api/skills/content/{skill_name:path}")
async def update_skill_content(skill_name: str, request: Request):
    """更新技能的 SKILL.md 内容并热重载。

    PUT body: { "content": "完整的 SKILL.md 内容" }

    流程:
    1. 校验新内容能被正确解析（frontmatter + body）
    2. 写入磁盘
    3. 热重载该技能
    4. 返回更新后的元数据
    """
    from synapse.core.agent import Agent
    from synapse.skills.parser import skill_parser

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    new_content = body.get("content", "")
    if not new_content.strip():
        return {"error": "content is required"}

    # 查找技能
    agent = getattr(request.app.state, "agent", None)
    actual_agent = agent if isinstance(agent, Agent) else getattr(agent, "_local_agent", None)

    skill = None
    loader = None
    if actual_agent:
        loader = getattr(actual_agent, "skill_loader", None)
        if loader:
            skill = loader.get_skill(skill_name)

    if not skill:
        return {"error": f"Skill '{skill_name}' not found"}

    if skill.metadata.system:
        return {"error": "Cannot edit system (built-in) skills"}

    # 1. 校验新内容格式
    try:
        parsed = skill_parser.parse_content(new_content, skill.path)
    except Exception as e:
        return {"error": f"Invalid SKILL.md format: {e}"}

    # 2. 写入磁盘
    try:
        skill.path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"error": f"Failed to write SKILL.md: {e}"}

    # 3. 热重载
    reloaded = False
    if loader:
        try:
            result = loader.reload_skill(skill_name)
            if result:
                _apply_allowlist_and_rebuild_catalog(request)
                reloaded = True
        except Exception as e:
            logger.warning(f"Skill reload after edit failed: {e}")

    _invalidate_skills_cache()
    _notify_skills_changed("content_update")
    return {
        "status": "ok",
        "reloaded": reloaded,
        "name": parsed.metadata.name,
        "description": parsed.metadata.description,
    }


def _skill_registry_from_request(request: Request):
    from synapse.core.agent import Agent

    agent = getattr(request.app.state, "agent", None)
    actual = agent if isinstance(agent, Agent) else getattr(agent, "_local_agent", None)
    if actual is None:
        return None
    return getattr(actual, "skill_registry", None)


def _resolve_profile_for_dev_tool_test(agent_profile_id: str | None):
    """默认使用「小鲸」（preset id=default）；可由请求覆盖 agent_profile_id。"""
    from synapse.agents.presets import SYSTEM_PRESETS
    from synapse.agents.profile import get_profile_store

    pid = (agent_profile_id or "").strip() or "default"
    store = get_profile_store()
    loaded = store.get(pid)
    if loaded:
        return loaded
    for sp in SYSTEM_PRESETS:
        if sp.id == pid:
            return sp
    for sp in SYSTEM_PRESETS:
        if sp.id == "default":
            return sp
    return SYSTEM_PRESETS[0]


@router.post("/api/skills/dev-tools/test")
async def dev_tools_test_skill(request: Request):
    """在临时目录中用指定 Agent（默认小鲸）对单个研发流程技能做一次快速验证。"""
    pool = getattr(request.app.state, "agent_pool", None)
    if pool is None:
        return JSONResponse(
            status_code=503,
            content={"error": "agent_pool_unavailable", "message": "Agent pool not initialized"},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_json"})

    skill_id = (body.get("skill_id") or "").strip()
    message = (body.get("message") or "").strip()
    agent_profile_raw = body.get("agent_profile_id")
    agent_profile_id = agent_profile_raw if isinstance(agent_profile_raw, str) else None

    timeout_raw = body.get("timeout_seconds")
    try:
        timeout_s = float(timeout_raw) if timeout_raw is not None else 180.0
    except (TypeError, ValueError):
        timeout_s = 180.0
    timeout_s = max(30.0, min(timeout_s, 600.0))

    if not skill_id:
        return JSONResponse(status_code=400, content={"error": "skill_id_required"})

    reg = _skill_registry_from_request(request)
    if reg is None:
        return JSONResponse(status_code=503, content={"error": "skill_registry_unavailable"})

    entry = reg.get(skill_id)
    if entry is None:
        return JSONResponse(status_code=404, content={"error": "skill_not_found", "skill_id": skill_id})

    tn = (entry.tool_name or "").strip()
    if not tn.startswith(DEV_TOOL_TOOL_PREFIX):
        return JSONResponse(
            status_code=400,
            content={"error": "not_dev_tool_skill", "tool_name": tn},
        )

    base_prof = _resolve_profile_for_dev_tool_test(agent_profile_id)
    prof_id = f"__dev_tool_test_{uuid.uuid4().hex[:16]}"
    session_id = f"devtool_test_{uuid.uuid4().hex}"

    from synapse.agents.profile import SkillsMode

    test_profile = replace(
        base_prof,
        id=prof_id,
        skills=[skill_id],
        skills_mode=SkillsMode.INCLUSIVE,
        ephemeral=True,
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="synapse_dev_tool_test_"))
    try:
        agent = await pool.get_or_create(session_id, test_profile)
        agent.default_cwd = str(temp_dir)
        if getattr(agent, "shell_tool", None):
            agent.shell_tool.default_cwd = str(temp_dir)
        agent._current_session_id = session_id

        default_msg = (
            "请在当前工作目录下完成一次最小验证：确认本研发流程技能可用，"
            "可按需调用 list_skills / get_skill_info，并简要说明验证步骤与结果。"
        )
        user_msg = message or default_msg

        result = await asyncio.wait_for(
            agent.execute_task_from_message(user_msg),
            timeout=timeout_s,
        )
        out_data = result.data
        if isinstance(out_data, str):
            output_text = out_data
        else:
            output_text = str(out_data) if out_data is not None else ""

        return {
            "success": result.success,
            "output": output_text if result.success else None,
            "error": result.error if not result.success else None,
            "duration_seconds": result.duration_seconds,
        }
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={
                "error": "timeout",
                "message": f"验证超时（{timeout_s:.0f}s）",
            },
        )
    except Exception as e:
        logger.exception("dev-tools test failed")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        try:
            pool.invalidate_profile(prof_id)
        except Exception:
            logger.warning("invalidate_profile after dev-tools test failed", exc_info=True)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


@router.post("/api/skills/dev-tools/create")
async def create_dev_tool_skill(request: Request):
    """在 ``skills/whalecloud-dev-tool-{slug}/`` 下创建 SKILL.md（及可选 .synapse-i18n.json）。"""
    import yaml as pyyaml

    from synapse.skills.parser import SkillParser

    body = await request.json()
    slug_in = body.get("slug") or body.get("skill_slug") or ""
    slug = sanitize_dev_tool_slug(str(slug_in))
    if not slug:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_slug",
                "message": "slug 须为 2–48 字符，仅小写字母、数字与连字符（如 my-flow）",
            },
        )

    name_zh = str(body.get("name_zh") or "").strip()
    name_en = str(body.get("name_en") or "").strip()
    desc_zh = str(body.get("description_zh") or "").strip()
    desc_en = str(body.get("description_en") or "").strip()

    try:
        from synapse.config import settings

        workspace_root = Path(settings.project_root)
    except Exception:
        workspace_root = Path.cwd()

    dir_name = f"whalecloud-dev-tool-{slug}"
    skill_id = dir_name
    tool_name = f"{DEV_TOOL_TOOL_PREFIX}{slug.replace('-', '_')}"

    skills_root = workspace_root / "skills"
    skill_folder = skills_root / dir_name
    skill_md = skill_folder / "SKILL.md"

    if skill_folder.exists():
        return JSONResponse(
            status_code=409,
            content={"error": "exists", "message": f"技能目录已存在: {dir_name}"},
        )

    primary_desc = (desc_en or desc_zh or "R&D workflow skill (Synapse).").strip()
    primary_desc = primary_desc.replace("\n", " ").strip()[:1024]
    display_title = (name_en or name_zh or dir_name).strip()
    when_use = (
        (desc_en or desc_zh or "When this R&D workflow applies.")
        .strip()
        .replace("\n", " ")[:800]
    )

    fm = {
        "name": dir_name,
        "description": primary_desc,
        "tool-name": tool_name,
        "license": "MIT",
        "category": "Dev Tools",
        "when-to-use": when_use,
        "keywords": ["whalecloud-dev-tool"],
    }
    fm_txt = pyyaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()

    intro_body = ""
    if desc_zh:
        intro_body += f"\n\n## 说明（中文）\n\n{desc_zh}\n"
    if desc_en:
        intro_body += f"\n\n## Overview (English)\n\n{desc_en}\n"

    md = f"---\n{fm_txt}\n---\n\n# {display_title}\n\n在编辑区完善指令、脚本与 references；可使用「测试验证」检查。\n{intro_body}"

    parser = SkillParser()
    try:
        parsed = parser.parse_content(md, skill_md)
        errs = parser.validate(parsed)
        hard = [e for e in (errs or []) if e.startswith("ERROR:")]
        if hard:
            return JSONResponse(status_code=400, content={"error": "validation", "details": hard})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    i18n_sidecar: dict[str, dict[str, str]] = {}
    if name_zh or desc_zh:
        i18n_sidecar["zh"] = {
            "name": name_zh or dir_name,
            "description": desc_zh or primary_desc,
        }
    if name_en or desc_en:
        i18n_sidecar["en"] = {
            "name": name_en or dir_name,
            "description": desc_en or primary_desc,
        }

    def _write_files() -> None:
        from synapse.skills.i18n import LEGACY_I18N_FILENAME

        skill_folder.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(md, encoding="utf-8")
        if i18n_sidecar:
            (skill_folder / LEGACY_I18N_FILENAME).write_text(
                json.dumps(i18n_sidecar, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    try:
        await asyncio.to_thread(_write_files)
    except Exception as e:
        logger.exception("dev-tools create write failed")
        await asyncio.to_thread(shutil.rmtree, str(skill_folder), ignore_errors=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

    _merge_external_allowlist_add(skill_id)

    try:
        from synapse.core.agent import Agent

        agent = getattr(request.app.state, "agent", None)
        actual_agent = agent
        if not isinstance(agent, Agent):
            actual_agent = getattr(agent, "_local_agent", None)
        if actual_agent is not None:
            loader = getattr(actual_agent, "skill_loader", None)
            if loader:
                base_path, _ = _read_external_allowlist()
                loader.load_all(base_path)
            _apply_allowlist_and_rebuild_catalog(request)
    except Exception as e:
        logger.warning("Post dev-tools create reload failed: %s", e)

    _invalidate_skills_cache()
    _notify_skills_changed("dev-tools-create")
    try:
        rel = skill_md.relative_to(workspace_root)
    except ValueError:
        rel = skill_md
    return {"status": "ok", "skill_id": skill_id, "path": str(rel).replace("\\", "/")}


@router.get("/api/skills/marketplace")
async def search_marketplace(q: str = "agent"):
    """Proxy to skills.sh search API (bypasses CORS for desktop app)."""
    from synapse.llm.providers.proxy_utils import (
        get_httpx_transport,
        get_proxy_config,
    )

    try:
        client_kwargs: dict = {
            "timeout": 15,
            "follow_redirects": True,
            "trust_env": False,
        }

        # 复用项目的代理和 IPv4 设置（get_proxy_config 含可达性验证）
        proxy = get_proxy_config()
        if proxy:
            client_kwargs["proxy"] = proxy

        transport = get_httpx_transport()
        if transport:
            client_kwargs["transport"] = transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(SKILLS_SH_API, params={"q": q})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("skills.sh API error: %s", e)
        return {"skills": [], "count": 0, "error": str(e)}


# Register API-layer side effects (cache invalidation + WS broadcast) so that
# skill changes made by the *tools* layer also propagate to the frontend.
def _on_skills_changed_api(action: str) -> None:
    _invalidate_skills_cache()
    _notify_skills_changed(action)


try:
    from synapse.skills.events import register_on_change

    register_on_change(_on_skills_changed_api)
except Exception:
    pass
