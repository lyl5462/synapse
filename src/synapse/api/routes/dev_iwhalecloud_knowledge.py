"""产品知识：架构文档生成、任务状态、AI 润色（挂到 dev_iwhalecloud.router）。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from synapse.agents.profile import AgentProfile, SkillsMode, get_profile_store
from synapse.api.schemas import error_response, success_response
from synapse.config import settings

logger = logging.getLogger(__name__)

_FALLBACK_RD_SKILL_ID = "whalecloud-dev-tool-arch-create"


def _get_enabled_rd_skill_ids(agent: Any) -> set[str]:
    """从 agent skill_loader 中动态获取已启用的研发工具技能 id 集合。"""
    try:
        loader = getattr(agent, "skill_loader", None)
        if not loader:
            return set()
        from synapse.utils.whaleclouddevtool import is_whalecloud_dev_tool_skill_id

        # _loaded_skills: dict[skill_id, ParsedSkill]
        loaded: dict = getattr(loader, "_loaded_skills", {})
        return {sid for sid in loaded if is_whalecloud_dev_tool_skill_id(sid)}
    except Exception:
        return set()


def _normalize_rd_skill_ids(raw_ids: list[str], enabled_ids: set[str]) -> list[str]:
    """过滤出已启用研发工具中存在的技能 id；若全部无效则 fallback 到默认。"""
    result = []
    for raw in raw_ids:
        s = (raw or "").strip().lower().replace("_", "-")
        if s and (not enabled_ids or s in enabled_ids):
            result.append(s)
    return result if result else [_FALLBACK_RD_SKILL_ID]


def _repo_name_from_git_url(url: str | None) -> str | None:
    """从 Git HTTPS URL 取仓库名（最后一段去掉 .git），失败则返回 None。"""
    if not url or not isinstance(url, str):
        return None
    part = url.rstrip("/").split("/")[-1]
    if part.endswith(".git"):
        part = part[:-4]
    return part or None


class ProductKnowledgeGenerateRequest(BaseModel):
    task_id: str = Field(
        ...,
        description="前端生成并经 docs_initialize 同步的任务 ID，与统一服务 doc_process_info 一致",
        min_length=1,
        max_length=128,
    )
    repo_name: str = Field(..., description="仓库名称（优先使用 repo_url 解析；前端传不到时作为兜底）")
    repo_url: str | None = Field(None, description="仓库 Git URL，用于从路径解析真实仓库名")
    gitnexus_url: str = Field(..., description="GitNexus 服务地址")
    product_desc: str = Field(..., description="产品描述")
    code_path: str = Field(..., description="代码路径")
    core_features: str = Field(..., description="主要功能")
    rd_skill_ids: list[str] = Field(
        default=[_FALLBACK_RD_SKILL_ID],
        description="研发工具技能 id 列表（多选，动态白名单）",
    )
    preferred_endpoint: str | None = Field(
        None,
        description="首选 LLM 端点 name（与 llm_endpoints.json 中一致）；空则走全局路由",
        max_length=200,
    )


class ProductKnowledgeRefineRequest(BaseModel):
    content: str = Field(..., description="当前文档内容")
    prompt: str = Field(..., description="修改需求")


_knowledge_tasks: dict[str, dict[str, Any]] = {}


def _task_status_dir() -> Path:
    d = settings.synapse_home / "tmp" / "task"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _task_status_path(task_id: str) -> Path | None:
    """与 _knowledge_tasks 同步的持久化文件：tmp/task/<task_id>.status（JSON）。task_id 仅保留安全字符。"""
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "", (task_id or "").strip())
    if not safe or len(safe) > 200:
        return None
    return _task_status_dir() / f"{safe}.status"


def _persist_task(task_id: str) -> None:
    """将当前内存中的任务快照写入磁盘；completed 不写 data 正文，仅保留 repo_name 供从 MD 回读。"""
    snap = _knowledge_tasks.get(task_id)
    if not snap:
        return
    path = _task_status_path(task_id)
    if path is None:
        return
    out: dict[str, Any] = {k: v for k, v in snap.items() if k != "data"}
    if snap.get("status") == "completed":
        out["repo_name"] = snap.get("repo_name")
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        logger.warning("Persist task %s failed: %s", task_id, e)


def _load_task_from_disk(task_id: str) -> dict[str, Any] | None:
    path = _task_status_path(task_id)
    if path is None or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _read_arch_from_repo_dir(repo_name: str) -> dict[str, Any]:
    """completed 时从本机临时目录读取架构 MD（权威数据源）。"""
    output_dir = settings.synapse_home / "tmp" / "gitnexus" / repo_name
    functional_arch = ""
    tech_arch = ""
    func_path = output_dir / "FUNCTIONAL_ARCH.md"
    if func_path.is_file():
        try:
            functional_arch = func_path.read_text(encoding="utf-8")
        except OSError:
            pass
    tech_path = output_dir / "TECH_ARCH.md"
    if tech_path.is_file():
        try:
            tech_arch = tech_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return {
        "functional_arch": functional_arch,
        "tech_arch": tech_arch,
        "output": "",
    }


def _assemble_task_for_response(task_id: str) -> dict[str, Any] | None:
    """合并内存/磁盘元数据；completed 始终从 tmp/gitnexus/<repo>/ 读取 MD 作为 data（非 completed 不把 MD 当完成态）。"""
    meta = _knowledge_tasks.get(task_id)
    if meta is None:
        meta = _load_task_from_disk(task_id)
        if meta is not None:
            _knowledge_tasks[task_id] = meta
    if not meta:
        return None
    st = meta.get("status")
    if st == "completed":
        repo_name = meta.get("repo_name")
        if isinstance(repo_name, str) and repo_name.strip():
            data = _read_arch_from_repo_dir(repo_name.strip())
            mem_data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
            out_data = {
                **data,
                "output": str(mem_data.get("output", "") or data.get("output", "")),
            }
            merged = {**{k: v for k, v in meta.items() if k != "data"}, "data": out_data}
            _knowledge_tasks[task_id] = merged
            return merged
        mem_data = meta.get("data")
        if isinstance(mem_data, dict):
            return meta
        empty = {**meta, "data": {"functional_arch": "", "tech_arch": "", "output": ""}}
        _knowledge_tasks[task_id] = empty
        return empty
    return meta


async def _run_knowledge_generation_task(
    task_id: str, req: ProductKnowledgeGenerateRequest, app_state: Any
) -> None:
    pool = getattr(app_state, "agent_pool", None)
    if not pool:
        _knowledge_tasks[task_id] = {"status": "error", "error": "Agent pool not initialized"}
        _persist_task(task_id)
        return
    prof_id: str = ""
    try:
        ep = (req.preferred_endpoint or "").strip() or None
        base_profile = get_profile_store().get("default") or AgentProfile(id="default", name="小鲸")

        # 先创建临时 agent（用于读取 skill_loader），再根据动态白名单过滤技能列表
        prof_id = f"__pkg_gen_{task_id}"
        _tmp_profile = replace(base_profile, id=prof_id, ephemeral=True, preferred_endpoint=ep)
        session_id = f"pkg_gen_{task_id}"
        agent = await pool.get_or_create(session_id, _tmp_profile)

        enabled_ids = _get_enabled_rd_skill_ids(agent)
        rd_skills = _normalize_rd_skill_ids(req.rd_skill_ids, enabled_ids)

        # 重建 profile 挂载过滤后的技能列表
        test_profile = replace(
            base_profile,
            id=prof_id,
            skills=rd_skills,
            skills_mode=SkillsMode.INCLUSIVE,
            ephemeral=True,
            preferred_endpoint=ep,
        )
        # 用新 profile 更新已创建的 agent（工厂会重建系统提示词）
        pool.invalidate_profile(prof_id)
        agent = await pool.get_or_create(session_id, test_profile)

        # repo_url 优先解析真实仓库名，前端未传时 fallback 到 repo_name
        repo_name = _repo_name_from_git_url(req.repo_url) or req.repo_name

        # 自动推导本地数据路径：~/.synapse/tmp/gitnexus/<repo_name>/
        local_data_path = settings.synapse_home / "tmp" / "gitnexus" / repo_name
        local_data_path.mkdir(parents=True, exist_ok=True)

        # 将已挂载的技能 body 读出（含真实路径），注入到 system prompt
        skill_bodies: list[str] = []
        loader = getattr(agent, "skill_loader", None)
        if loader:
            for sid in rd_skills:
                skill = loader.get_skill(sid)
                if skill and skill.body:
                    skill_path_line = f"**技能路径**: {skill.skill_dir}\n\n"
                    skill_bodies.append(f"### 研发技能：{sid}\n\n{skill_path_line}{skill.body}")

        # 技能全量内容注入到 system prompt，让大模型在执行前完整获取技能指引
        skill_section = ""
        if skill_bodies:
            skill_section = (
                "\n\n---\n## 研发工具技能指引（请严格遵照以下指引执行任务）\n\n"
                + "\n\n---\n\n".join(skill_bodies)
            )
        minimal_system_prompt = "你是一个研发工具助手，请按照用户的要求生成系统架构文档。" + skill_section

        prompt = f"""gitnexus服务部署在[{req.gitnexus_url}]上，请使用工具whalecloud-dev-tool-arch-create生成仓库[{repo_name}]的系统架构和功能架构文档。
产品描述：[{req.product_desc}]
代码路径：[{req.code_path}]
主要功能：[{req.core_features}]
本地数据根目录：[{local_data_path}]（gitnexus 拉取的数据将存放于此，请以此路径作为本地数据访问根目录）"""

        output_dir = local_data_path
        agent.default_cwd = str(output_dir)
        if getattr(agent, "shell_tool", None):
            agent.shell_tool.default_cwd = str(output_dir)  # type: ignore[union-attr]
        agent._current_session_id = session_id

        # 架构文档生成专用工具集：只保留 SKILL 实际需要的执行工具，大幅节省 token
        # SKILL 里用到：run_shell（执行 node 脚本）、文件读写、目录列举
        _ARCH_GEN_TOOL_NAMES = frozenset({
            "run_shell",
            "read_file",
            "write_file",
            "list_directory",
        })
        _orig_tools = getattr(agent, "_tools", None)
        _slim_tools = (
            [t for t in _orig_tools if t.get("name") in _ARCH_GEN_TOOL_NAMES]
            if _orig_tools is not None
            else None
        )

        # 用极简提示词覆盖 system prompt，并锁定阻止动态重建
        # _org_context=True 会使 _build_system_prompt_compiled* 直接返回 _context.system
        _orig_org_context = getattr(agent, "_org_context", None)
        _orig_system = getattr(getattr(agent, "_context", None), "system", None)
        try:
            agent._org_context = True  # type: ignore[attr-defined]
            if hasattr(agent, "_context") and agent._context is not None:
                agent._context.system = minimal_system_prompt
            if _slim_tools is not None:
                agent._tools = _slim_tools  # type: ignore[attr-defined]

            _knowledge_tasks[task_id]["status"] = "running"
            _persist_task(task_id)
            result = await asyncio.wait_for(
                agent.execute_task_from_message(prompt),
                timeout=3600.0,
            )
        finally:
            # 恢复原始状态，避免影响后续复用（ephemeral agent 通常会被销毁，但以防万一）
            agent._org_context = _orig_org_context  # type: ignore[attr-defined]
            if hasattr(agent, "_context") and agent._context is not None and _orig_system is not None:
                agent._context.system = _orig_system
            if _orig_tools is not None:
                agent._tools = _orig_tools  # type: ignore[attr-defined]

        if result.success:
            functional_arch = ""
            tech_arch = ""
            func_path = output_dir / "FUNCTIONAL_ARCH.md"
            if func_path.is_file():
                functional_arch = func_path.read_text(encoding="utf-8")
            tech_path = output_dir / "TECH_ARCH.md"
            if tech_path.is_file():
                tech_arch = tech_path.read_text(encoding="utf-8")
            _knowledge_tasks[task_id] = {
                "status": "completed",
                "repo_name": repo_name,
                "data": {
                    "functional_arch": functional_arch,
                    "tech_arch": tech_arch,
                    "output": str(result.data) if result.data else "",
                },
            }
            _persist_task(task_id)
        else:
            _knowledge_tasks[task_id] = {
                "status": "error",
                "error": result.error or "Unknown error",
            }
            _persist_task(task_id)
    except TimeoutError:
        _knowledge_tasks[task_id] = {"status": "error", "error": "Task timeout"}
        _persist_task(task_id)
    except Exception as e:
        logger.exception("Knowledge generation task failed")
        _knowledge_tasks[task_id] = {"status": "error", "error": str(e)}
        _persist_task(task_id)
    finally:
        try:
            if prof_id:
                pool.invalidate_profile(prof_id)
        except Exception:
            pass


def register_product_knowledge_routes(router: APIRouter) -> None:
    """在 dev_iwhalecloud 的 `router` 上注册产品知识相关路由。"""

    @router.post("/api/dev/iwhalecloud/product_knowledge/generate")
    async def product_knowledge_generate(
        _request: Request, body: ProductKnowledgeGenerateRequest
    ) -> Any:
        task_id = body.task_id.strip()

        # 幂等校验：同一 task_id 未到终态时拒绝重复提交（含进程重启后从磁盘恢复的状态）
        existing = _knowledge_tasks.get(task_id) or _load_task_from_disk(task_id)
        if existing and existing.get("status") not in ("completed", "error"):
            if task_id not in _knowledge_tasks:
                _knowledge_tasks[task_id] = existing
            return success_response({"task_id": task_id}, "任务已在执行中")

        repo_resolved = _repo_name_from_git_url(body.repo_url) or body.repo_name
        _knowledge_tasks[task_id] = {
            "status": "pending",
            "created_at": time.time(),
            "repo_name": repo_resolved,
        }
        _persist_task(task_id)
        ep = (body.preferred_endpoint or "").strip() or None
        logger.info(
            "Product knowledge generation task %s, rd_skill_ids=%s, preferred_endpoint=%s",
            task_id,
            body.rd_skill_ids,
            ep or "(auto)",
        )
        asyncio.create_task(_run_knowledge_generation_task(task_id, body, _request.app.state))
        return success_response({"task_id": task_id}, "文档生成任务已启动")

    @router.get("/api/dev/iwhalecloud/product_knowledge/status/{task_id}")
    def product_knowledge_status(task_id: str) -> Any:
        task = _assemble_task_for_response(task_id.strip())
        if not task:
            return error_response(404, "任务不存在")
        return success_response(task)

    # TODO: 需要做同步流式的改造
    # TODO: 和初始化一样，TASK_ID要前端生成
    @router.post("/api/dev/iwhalecloud/product_knowledge/refine")
    async def product_knowledge_refine(request: Request, body: ProductKnowledgeRefineRequest) -> Any:
        pool = getattr(request.app.state, "agent_pool", None)
        if not pool:
            return error_response(503, "Agent pool not initialized")
        prof_id = f"__pkg_refine_{uuid.uuid4().hex[:8]}"
        try:
            rfprompt = f"""请根据以下修改需求，调整提供的 Markdown 文档内容。
修改需求：{body.prompt}

当前文档内容：
```markdown
{body.content}
```

请直接输出修改后的完整 Markdown 内容，不要包含任何额外的解释或说明。"""
            base_profile = get_profile_store().get("default") or AgentProfile(id="default", name="小鲸")
            test_profile = replace(
                base_profile,
                id=prof_id,
                ephemeral=True,
            )
            session_id = f"pkg_refine_{uuid.uuid4().hex}"
            agent = await pool.get_or_create(session_id, test_profile)
            result = await asyncio.wait_for(
                agent.execute_task_from_message(rfprompt),
                timeout=600.0,
            )
            if result.success:
                output = str(result.data) if result.data else ""
                md_match = re.search(r"```markdown\s*(.*?)\s*```", output, re.DOTALL)
                refined_content = md_match.group(1) if md_match else output
                return success_response({"content": refined_content}, "文档优化成功")
            return error_response(500, result.error or "文档优化失败")
        except TimeoutError:
            return error_response(504, "文档优化超时")
        except Exception as e:
            logger.exception("Knowledge refine failed")
            return error_response(500, str(e))
        finally:
            try:
                pool.invalidate_profile(prof_id)
            except Exception:
                pass
