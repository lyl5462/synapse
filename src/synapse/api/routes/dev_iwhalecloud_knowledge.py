"""产品知识：架构文档生成、任务状态、AI 润色（挂到 dev_iwhalecloud.router）。"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from synapse.agents.profile import AgentProfile, SkillsMode
from synapse.api.schemas import error_response, success_response

logger = logging.getLogger(__name__)


class ProductKnowledgeGenerateRequest(BaseModel):
    repo_name: str = Field(..., description="仓库名称")
    gitnexus_url: str = Field(..., description="GitNexus 服务地址")
    product_desc: str = Field(..., description="产品描述")
    code_path: str = Field(..., description="代码路径")
    core_features: str = Field(..., description="主要功能")
    local_data_path: str = Field("", description="本地拉取数据路径")


class ProductKnowledgeRefineRequest(BaseModel):
    content: str = Field(..., description="当前文档内容")
    prompt: str = Field(..., description="修改需求")


_knowledge_tasks: dict[str, dict[str, Any]] = {}


def _get_preferred_claude_model(request: Request) -> str | None:
    """遍历系统配置的 LLM 端点，优选 claude 系模型，优先 claude-4.5-sonnet 关键词。"""
    try:
        llm_registry = getattr(request.app.state, "llm_registry", None)
        if llm_registry is None:
            return None
        if not hasattr(llm_registry, "list_models"):
            return None
        # list_models 在多数 registry 为 async，此处作尽力同步探测；失败则走默认模型
        models = llm_registry.list_models
        if asyncio.iscoroutinefunction(models):
            return None
        raw = models()  # type: ignore[call-arg]
        if raw is None or asyncio.iscoroutine(raw):
            return None
        model_ids: list[str] = []
        for m in raw:
            mid = getattr(m, "id", None) or str(m)
            if "claude" in mid.lower():
                model_ids.append(mid)
        if not model_ids:
            return None
        for m in model_ids:
            if "claude-4.5-sonnet" in m.lower() or "claude-4-5-sonnet" in m.lower():
                return m
        return model_ids[0]
    except Exception as e:
        logger.warning("获取优选模型失败: %s", e)
        return None


async def _run_knowledge_generation_task(
    task_id: str, req: ProductKnowledgeGenerateRequest, app_state: Any, model_id: str | None = None
) -> None:
    pool = getattr(app_state, "agent_pool", None)
    if not pool:
        _knowledge_tasks[task_id] = {"status": "error", "error": "Agent pool not initialized"}
        return
    prof_id: str = ""
    try:
        prompt = f"""gitnexus服务部署在[{req.gitnexus_url}]上，请生成仓库[{req.repo_name}]的系统架构文档。
产品描述：[{req.product_desc}]
代码路径：[{req.code_path}]
主要功能：[{req.core_features}]
本地拉取数据路径：[{req.local_data_path}]"""

        base_profile = pool.get_profile("default") or AgentProfile(id="default", name="小鲸")
        prof_id = f"__pkg_gen_{task_id}"
        test_profile = replace(
            base_profile,
            id=prof_id,
            skills=["whalecloud-dev-tool-arch-create"],
            skills_mode=SkillsMode.INCLUSIVE,
            ephemeral=True,
        )
        if model_id:
            test_profile = replace(test_profile, model=model_id)

        temp_dir = Path(tempfile.mkdtemp(prefix="synapse_pkg_gen_"))
        session_id = f"pkg_gen_{task_id}"
        agent = await pool.get_or_create(session_id, test_profile)
        agent.default_cwd = str(temp_dir)
        if getattr(agent, "shell_tool", None):
            agent.shell_tool.default_cwd = str(temp_dir)  # type: ignore[union-attr]
        agent._current_session_id = session_id
        _knowledge_tasks[task_id]["status"] = "running"
        result = await asyncio.wait_for(
            agent.execute_task_from_message(prompt),
            timeout=600.0,
        )
        if result.success:
            functional_arch = ""
            tech_arch = ""
            func_path = temp_dir / "FUNCTIONAL_ARCH.md"
            if func_path.is_file():
                functional_arch = func_path.read_text(encoding="utf-8")
            tech_path = temp_dir / "TECH_ARCH.md"
            if tech_path.is_file():
                tech_arch = tech_path.read_text(encoding="utf-8")
            _knowledge_tasks[task_id] = {
                "status": "completed",
                "data": {
                    "functional_arch": functional_arch,
                    "tech_arch": tech_arch,
                    "output": str(result.data) if result.data else "",
                },
            }
        else:
            _knowledge_tasks[task_id] = {
                "status": "error",
                "error": result.error or "Unknown error",
            }
    except TimeoutError:
        _knowledge_tasks[task_id] = {"status": "error", "error": "Task timeout"}
    except Exception as e:
        logger.exception("Knowledge generation task failed")
        _knowledge_tasks[task_id] = {"status": "error", "error": str(e)}
    finally:
        try:
            if prof_id:
                pool.invalidate_profile(prof_id)
        except Exception:
            pass


def register_product_knowledge_routes(router: APIRouter) -> None:
    """在 dev_iwhalecloud 的 `router` 上注册产品知识相关路由。"""

    @router.post("/api/dev/iwhalecloud/product_knowledge/generate")
    async def product_knowledge_generate(request: Request, body: ProductKnowledgeGenerateRequest) -> Any:
        task_id = uuid.uuid4().hex
        _knowledge_tasks[task_id] = {"status": "pending", "created_at": time.time()}
        model_id = _get_preferred_claude_model(request)
        logger.info("Product knowledge generation task %s, preferred model: %s", task_id, model_id)
        asyncio.create_task(
            _run_knowledge_generation_task(
                task_id, body, request.app.state, model_id if model_id else None
            )
        )
        return success_response({"task_id": task_id}, "文档生成任务已启动")

    @router.get("/api/dev/iwhalecloud/product_knowledge/status/{task_id}")
    def product_knowledge_status(task_id: str) -> Any:
        task = _knowledge_tasks.get(task_id)
        if not task:
            return error_response(404, "任务不存在")
        return success_response(task)

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
            base_profile = pool.get_profile("default") or AgentProfile(id="default", name="小鲸")
            test_profile = replace(
                base_profile,
                id=prof_id,
                ephemeral=True,
            )
            session_id = f"pkg_refine_{uuid.uuid4().hex}"
            agent = await pool.get_or_create(session_id, test_profile)
            result = await asyncio.wait_for(
                agent.execute_task_from_message(rfprompt),
                timeout=120.0,
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
