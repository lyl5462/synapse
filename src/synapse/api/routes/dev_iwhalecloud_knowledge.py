"""产品知识：架构文档生成、任务状态、AI 润色（挂到 dev_iwhalecloud.router）。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
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
_REFINE_SKILL_ID = "whalecloud-dev-tool-arch-modify"


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
    repo_name: str = Field(
        ..., description="仓库名称（优先使用 repo_url 解析；前端传不到时作为兜底）"
    )
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
    prod_name: str = Field(
        ...,
        description="产品标识，与统一服务 docs_initialize 的 prod 一致；落盘根为 synapse_home/tmp/docs/<prod_name>/<doc_type>/",
        min_length=1,
        max_length=512,
    )
    doc_type: str = Field(
        ...,
        description="文档类型，与统一服务 doc_type 一致；与 prod_name 共同决定落盘目录",
        min_length=1,
        max_length=256,
    )


class ProductKnowledgeRefineRequest(BaseModel):
    prod_name: str = Field(..., description="产品标识，与 docs_initialize prod 一致", min_length=1, max_length=512)
    doc_type: str = Field(..., description="文档类型，与生成任务一致", min_length=1, max_length=256)
    targets: list[str] = Field(..., description="稳定文件名数组，必须恰好 1 个元素")
    user_prompt: str = Field(..., description="用户修改要求（不含产品信息块）")
    preferred_endpoint: str | None = Field(None, description="首选 LLM 端点 name", max_length=200)
    rd_skill_ids: list[str] = Field(
        default=[_FALLBACK_RD_SKILL_ID],
        description="研发工具技能 id 列表（多选，动态白名单）",
    )
    product_desc: str = Field(default="", description="产品描述（服务端注入 user 消息）")
    code_path: str = Field(default="", description="代码路径（服务端注入 user 消息）")
    core_features: str = Field(default="", description="主要功能（服务端注入 user 消息）")
    gitnexus_url: str = Field(default="", description="GitNexus 服务地址（源码缓存不存在时用于拉取）")


class ProductKnowledgeRefineSessionBody(BaseModel):
    """按 prod + doc_type + target 定位 refine_sessions/<target>/ 下的会话。"""

    prod_name: str = Field(..., min_length=1, max_length=512)
    doc_type: str = Field(..., min_length=1, max_length=256)
    target: str = Field(..., min_length=1, max_length=512, description="与本地草稿 doc_name 一致的文件名")


# 系统提示词：产品知识文档 AI 编辑（refine 专用）
_REFINE_SYSTEM_PROMPT_BASE = """\
你是一个产品知识文档编辑助手。你的任务是根据用户要求，精准修改指定的产品知识文档。

## 核心原则（不得违反）
1. **以实际代码为基础不臆断**：所有新增/修改内容必须有源码依据；若源码缓存存在则优先读取，找不到依据时须标注「[待源码确认]」，不得凭空描述。
2. **以历史文档为参考不造谣**：必须先完整读取待修改文件，保留用户未要求修改的所有章节与措辞；不得凭印象替换已有准确描述。
3. **以用户需求为根本不发散**：修改范围严格限定在用户指定内容，不主动扩展修改其他章节。

## 工作流程
请严格按照以下步骤执行（已注入的技能 whalecloud-dev-tool-arch-modify 中有完整的分阶段指引，请遵照执行）：

1. **解析修改意图**：读取 user 消息中的产品上下文与用户修改要求，拆解修改点列表。
2. **读取历史文档**：使用 read_file 工具读取待修改文件（会话 proposed/ 目录下的工作副本），记录不应被修改的章节。
3. **查阅源码**（若修改涉及功能描述/架构关系）：
   - 先检查源码本地缓存路径（`synapse_home/tmp/gitnexus/<repo_name>/files/`）是否存在；
   - 缓存存在则直接用 read_file / list_directory 读取，**不需要重新拉取**；
   - 缓存不存在则从 CODE_PATH 指定路径直接读取源文件；
   - 每个修改点记录「源码依据：<文件路径> → <具体证据>」。
4. **修改文档**：按修改点逐一修改，不扩散到其他章节，新增内容附源码路径作为论据。
5. **完整性校验**：确认未被要求修改的章节均已保留，修改点均有源码依据或标注「[待源码确认]」。
6. **写回文件**：使用 write_file 将完整修改后的文档写回 proposed/ 目录（同一文件名）。

## 输出约束
- Markdown 文档：输出完整可替换的正文；若在回复文字中附带文档片段，**必须**且仅能用 ```markdown ... ``` 包裹。
- `.excalidraw` 文件：输出合法 JSON；优先使用工具写文件，避免在聊天中贴大段 JSON；节点名称必须来自真实源码符号。
- **禁止**改变文件名（必须与 targets[0] 一致）。
- **禁止**删除用户未要求删除的章节。
- **禁止**直接写入知识文档根目录下的权威源文件（只允许写 proposed/ 子目录）。
- **禁止**调用不在白名单中的工具（如 run_shell）。
- **禁止**臆断产品功能和代码实现；未找到源码证据的描述必须标注「[待源码确认]」。
"""


class ProductKnowledgeLocalDraftQuery(BaseModel):
    prod_name: str = Field(
        ...,
        description="与 docs_initialize 的 prod 一致",
        min_length=1,
        max_length=512,
    )
    doc_type: str = Field(
        ...,
        description="与 docs_initialize 的 doc_type 一致",
        min_length=1,
        max_length=256,
    )


class LocalDraftDocRow(BaseModel):
    doc_name: str = Field(..., min_length=1, max_length=512)
    content: str = Field(default="")


class ProductKnowledgeLocalDraftWriteRequest(BaseModel):
    prod_name: str = Field(..., min_length=1, max_length=512)
    doc_type: str = Field(..., min_length=1, max_length=256)
    doc_content: list[LocalDraftDocRow] = Field(
        ...,
        description="与 get_doc / docs_submit 的 doc_content 项结构一致",
    )


_knowledge_tasks: dict[str, dict[str, Any]] = {}

_ATOMIC_WRITE_SUFFIX = ".synapse_part"

# refine 在途任务超时（秒）：超过后 status 查询视为超时并清理目录
_REFINE_SESSION_TIMEOUT_SECS = 3600


# ---------------------------------------------------------------------------
# Refine session.status 落盘工具（目录：refine_sessions/<target>/）
# ---------------------------------------------------------------------------

def _refine_session_status_path(session_root: Path) -> Path:
    return session_root / "session.status"


def _refine_target_session_root(docs_root: Path, target_safe: str) -> Path:
    return docs_root / "refine_sessions" / target_safe


def _write_refine_session_status(session_root: Path, payload: dict[str, Any]) -> None:
    """原子写入 session.status；失败仅记录日志不抛出。"""
    path = _refine_session_status_path(session_root)
    tmp = path.with_suffix(".synapse_part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        logger.warning("write refine session.status failed: %s", e)


def _read_refine_session_status(session_root: Path) -> dict[str, Any] | None:
    """读取 session.status；不存在或解析失败返回 None。"""
    path = _refine_session_status_path(session_root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _rmtree_refine_session_root(session_root: Path) -> None:
    try:
        if session_root.exists():
            shutil.rmtree(session_root, ignore_errors=True)
    except Exception as e:
        logger.warning("rmtree refine session %s failed: %s", session_root, e)


def _cleanup_legacy_pkg_refine_dirs(docs_root: Path) -> None:
    """移除旧版 refine_sessions/pkg_refine_* 目录，避免与按 target 分目录的布局冲突。"""
    sessions_dir = docs_root / "refine_sessions"
    if not sessions_dir.is_dir():
        return
    try:
        entries = list(sessions_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("pkg_refine_"):
            _rmtree_refine_session_root(entry)


def _knowledge_docs_root(doc_type: str, prod_name: str) -> Path:
    """大模型产出（FUNCTIONAL_ARCH.md、TECH_ARCH.md、*.excalidraw 等）目录。"""
    return settings.synapse_home / "tmp" / "docs" / prod_name / doc_type


def _safe_docs_file_basename(name: str) -> str | None:
    """拒绝路径穿越与隐藏/临时文件名的落盘文件名。"""
    s = (name or "").strip()
    if not s or s in (".", ".."):
        return None
    if "/" in s or "\\" in s:
        return None
    if ".." in s:
        return None
    if s.startswith("."):
        return None
    return s


def _local_draft_dir_list_doc_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    try:
        for p in sorted(root.iterdir()):
            if not p.is_file():
                continue
            if p.name.startswith("__"):
                continue
            if p.name.startswith("."):
                continue
            if p.name.endswith(_ATOMIC_WRITE_SUFFIX):
                continue
            out.append(p)
    except OSError as e:
        logger.warning("list draft dir %s: %s", root, e)
    return out


def local_draft_has_any_file(doc_type: str, prod_name: str) -> bool:
    root = _knowledge_docs_root(doc_type, prod_name)
    return len(_local_draft_dir_list_doc_files(root)) > 0


def read_local_draft_doc_rows(doc_type: str, prod_name: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    root = _knowledge_docs_root(doc_type, prod_name)
    for p in _local_draft_dir_list_doc_files(root):
        safe = _safe_docs_file_basename(p.name)
        if not safe or safe != p.name:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            text = ""
        rows.append({"doc_name": p.name, "content": text})
    return rows


def write_local_draft_doc_rows_atomic(
    doc_type: str, prod_name: str, rows: list[tuple[str, str]]
) -> None:
    """全量写入该 doc_type 下文档：单文件 .synapse_part + replace；并删除目录内未出现在 payload 中的普通文件。"""
    root = _knowledge_docs_root(doc_type, prod_name)
    root.mkdir(parents=True, exist_ok=True)
    wanted: set[str] = set()
    normalized: list[tuple[str, str]] = []
    for raw_name, content in rows:
        name = _safe_docs_file_basename(raw_name)
        if not name:
            raise ValueError(f"invalid_doc_name:{raw_name!r}")
        wanted.add(name)
        normalized.append((name, content))
    for name, content in normalized:
        dest = root / name
        part = dest.with_name(dest.name + _ATOMIC_WRITE_SUFFIX)
        part.write_bytes(content.encode("utf-8"))
        part.replace(dest)
    for p in root.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith(_ATOMIC_WRITE_SUFFIX):
            p.unlink(missing_ok=True)
            continue
        if p.name.startswith(".") or p.name.startswith("__"):
            continue
        if p.name not in wanted:
            try:
                p.unlink()
            except OSError as e:
                logger.warning("remove orphan draft %s: %s", p, e)


def clear_local_draft_doc_dir(doc_type: str, prod_name: str) -> int:
    """提交成功后清空 synapse_home/tmp/docs/<prod>/<doc_type>/ 下普通文件（含遗留 .synapse_part）。"""
    root = _knowledge_docs_root(doc_type, prod_name)
    if not root.is_dir():
        return 0
    n = 0
    for p in list(root.iterdir()):
        if p.is_file():
            try:
                p.unlink()
                n += 1
            except OSError as e:
                logger.warning("clear draft file %s: %s", p, e)
    return n


def _gitnexus_local_data_path(repo_name: str) -> Path:
    """GitNexus 拉取/缓存数据根目录（与架构产出目录分离）。"""
    return settings.synapse_home / "tmp" / "gitnexus" / repo_name


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
    """将当前内存中的任务快照写入磁盘；completed 不写 data 正文，保留 doc_type 等元数据供从 tmp 目录回读 MD。"""
    snap = _knowledge_tasks.get(task_id)
    if not snap:
        return
    path = _task_status_path(task_id)
    if path is None:
        return
    out: dict[str, Any] = {k: v for k, v in snap.items() if k != "data"}
    if snap.get("status") == "completed":
        out["repo_name"] = snap.get("repo_name")
        out["doc_type"] = snap.get("doc_type")
        out["prod_name"] = snap.get("prod_name")
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


def _read_arch_from_doc_root(doc_type: str, prod_name: str) -> dict[str, Any]:
    """completed 时从 synapse_home/tmp/docs/<prod_name>/<doc_type>/ 读取架构 MD（与生成任务 cwd 一致）。"""
    output_dir = _knowledge_docs_root(doc_type, prod_name)
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
    sys_arch_layers_excalidraw = ""
    sal_path = output_dir / "sys-arch-layers.excalidraw"
    if sal_path.is_file():
        try:
            sys_arch_layers_excalidraw = sal_path.read_text(encoding="utf-8")
        except OSError:
            pass
    tech_stack_excalidraw = ""
    ts_ex_path = output_dir / "tech-stack.excalidraw"
    if ts_ex_path.is_file():
        try:
            tech_stack_excalidraw = ts_ex_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return {
        "functional_arch": functional_arch,
        "tech_arch": tech_arch,
        "sys_arch_layers_excalidraw": sys_arch_layers_excalidraw,
        "tech_stack_excalidraw": tech_stack_excalidraw,
        "output": "",
    }


def _assemble_task_for_response(task_id: str) -> dict[str, Any] | None:
    """合并内存/磁盘元数据；completed 始终从 tmp/docs/<prod_name>/<doc_type>/ 读取 MD 作为 data（非 completed 不把 MD 当完成态）。"""
    meta = _knowledge_tasks.get(task_id)
    if meta is None:
        meta = _load_task_from_disk(task_id)
        if meta is not None:
            _knowledge_tasks[task_id] = meta
    if not meta:
        return None
    st = meta.get("status")
    if st == "completed":
        raw_dt = meta.get("doc_type")
        raw_pn = meta.get("prod_name")
        if isinstance(raw_dt, str) and isinstance(raw_pn, str):
            data = _read_arch_from_doc_root(raw_dt, raw_pn)
        else:
            data = {
                "functional_arch": "",
                "tech_arch": "",
                "sys_arch_layers_excalidraw": "",
                "tech_stack_excalidraw": "",
                "output": "",
            }
        mem_data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        out_data = {
            **data,
            "output": str(mem_data.get("output", "") or data.get("output", "")),
        }
        merged = {**{k: v for k, v in meta.items() if k != "data"}, "data": out_data}
        _knowledge_tasks[task_id] = merged
        return merged
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
        doc_type = req.doc_type
        prod_name = req.prod_name

        # GitNexus 本地数据与架构产出分离：前者 tmp/gitnexus/<repo>，后者 tmp/docs/<prod>/<doc_type>
        local_data_path = _gitnexus_local_data_path(repo_name)
        local_data_path.mkdir(parents=True, exist_ok=True)
        output_dir = _knowledge_docs_root(doc_type, prod_name)
        output_dir.mkdir(parents=True, exist_ok=True)

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
        minimal_system_prompt = (
            "你是一个研发工具助手，请按照用户的要求生成系统架构文档。" + skill_section
        )

        prompt = f"""gitnexus服务部署在[{req.gitnexus_url}]上，请使用工具whalecloud-dev-tool-arch-create生成仓库[{repo_name}]的系统架构和功能架构文档。
产品描述：[{req.product_desc}]
代码路径：[{req.code_path}]
主要功能：[{req.core_features}]
GitNexus 本地数据根目录：[{local_data_path}]（materialize/缓存等请使用此路径，作为只读的图谱与源码缓存根）
架构文档产出目录：[{output_dir}]（FUNCTIONAL_ARCH.md、TECH_ARCH.md、*.excalidraw 等所有交付物必须写入此目录，不要使用 GitNexus 数据目录作为产出路径）"""

        agent.default_cwd = str(output_dir)
        if getattr(agent, "shell_tool", None):
            agent.shell_tool.default_cwd = str(output_dir)  # type: ignore[union-attr]
        agent._current_session_id = session_id

        # 架构文档生成专用工具集：只保留 SKILL 实际需要的执行工具，大幅节省 token
        # SKILL 里用到：run_shell（执行 node 脚本）、文件读写、目录列举
        _ARCH_GEN_TOOL_NAMES = frozenset(
            {
                "run_shell",
                "read_file",
                "write_file",
                "list_directory",
            }
        )
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
            if (
                hasattr(agent, "_context")
                and agent._context is not None
                and _orig_system is not None
            ):
                agent._context.system = _orig_system
            if _orig_tools is not None:
                agent._tools = _orig_tools  # type: ignore[attr-defined]

        if result.success:
            functional_arch = ""
            tech_arch = ""
            sys_arch_layers_excalidraw = ""
            tech_stack_excalidraw = ""
            func_path = output_dir / "FUNCTIONAL_ARCH.md"
            if func_path.is_file():
                functional_arch = func_path.read_text(encoding="utf-8")
            tech_path = output_dir / "TECH_ARCH.md"
            if tech_path.is_file():
                tech_arch = tech_path.read_text(encoding="utf-8")
            sal_path = output_dir / "sys-arch-layers.excalidraw"
            if sal_path.is_file():
                try:
                    sys_arch_layers_excalidraw = sal_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            ts_ex_path = output_dir / "tech-stack.excalidraw"
            if ts_ex_path.is_file():
                try:
                    tech_stack_excalidraw = ts_ex_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            _knowledge_tasks[task_id] = {
                "status": "completed",
                "repo_name": repo_name,
                "prod_name": prod_name,
                "doc_type": doc_type,
                "data": {
                    "functional_arch": functional_arch,
                    "tech_arch": tech_arch,
                    "sys_arch_layers_excalidraw": sys_arch_layers_excalidraw,
                    "tech_stack_excalidraw": tech_stack_excalidraw,
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
            "prod_name": body.prod_name,
            "doc_type": body.doc_type,
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

    @router.post("/api/dev/iwhalecloud/product_knowledge/local_draft/exists")
    def product_knowledge_local_draft_exists(body: ProductKnowledgeLocalDraftQuery) -> Any:
        exists = local_draft_has_any_file(body.doc_type, body.prod_name)
        return success_response({"exists": exists})

    @router.post("/api/dev/iwhalecloud/product_knowledge/local_draft/read")
    def product_knowledge_local_draft_read(body: ProductKnowledgeLocalDraftQuery) -> Any:
        rows = read_local_draft_doc_rows(body.doc_type, body.prod_name)
        return success_response({"doc_content": rows})

    @router.post("/api/dev/iwhalecloud/product_knowledge/local_draft/write")
    def product_knowledge_local_draft_write(body: ProductKnowledgeLocalDraftWriteRequest) -> Any:
        if not body.doc_content:
            return error_response(400, "doc_content_empty")
        pairs: list[tuple[str, str]] = []
        for r in body.doc_content:
            dn = r.doc_name.strip()
            if not dn:
                return error_response(400, "empty_doc_name")
            pairs.append((dn, r.content))
        try:
            write_local_draft_doc_rows_atomic(body.doc_type, body.prod_name, pairs)
        except ValueError as e:
            return error_response(400, str(e))
        except OSError as e:
            logger.exception("local draft write failed")
            return error_response(500, str(e))
        return success_response({"written": len(pairs)}, "本地草稿已保存")

    @router.post("/api/dev/iwhalecloud/product_knowledge/local_draft/clear")
    def product_knowledge_local_draft_clear(body: ProductKnowledgeLocalDraftQuery) -> Any:
        n = clear_local_draft_doc_dir(body.doc_type, body.prod_name)
        return success_response({"removed": n}, "本地草稿目录已清理")

    @router.post("/api/dev/iwhalecloud/product_knowledge/refine")
    async def product_knowledge_refine(
        request: Request, body: ProductKnowledgeRefineRequest
    ) -> Any:
        """
        异步提交 refine：落盘目录为 refine_sessions/<target>/ ，同 target 全局仅一个在途任务。
        返回 data.target；通过 refine/session/status 传入 prod_name、doc_type、target 轮询。
        """
        if len(body.targets) != 1:
            return error_response(400, "invalid_targets")
        target_name = body.targets[0].strip()
        safe_name = _safe_docs_file_basename(target_name)
        if not safe_name:
            return error_response(400, "invalid_targets")

        docs_root = _knowledge_docs_root(body.doc_type, body.prod_name)
        auth_file = docs_root / safe_name

        if not auth_file.is_file():
            return error_response(404, "target_not_found")

        pool = getattr(request.app.state, "agent_pool", None)
        if not pool:
            return error_response(503, "Agent pool not initialized")

        _cleanup_legacy_pkg_refine_dirs(docs_root)

        session_root = _refine_target_session_root(docs_root, safe_name)
        existing = _read_refine_session_status(session_root)
        if existing:
            st = str(existing.get("status", ""))
            started_at = float(existing.get("started_at", 0.0))
            elapsed = time.time() - started_at
            up = str(existing.get("user_prompt", ""))
            if st in ("pending", "running"):
                if elapsed < _REFINE_SESSION_TIMEOUT_SECS:
                    return {
                        "errorcode": 409,
                        "message": "refine_session_pending",
                        "data": {
                            "target": safe_name,
                            "user_prompt": up[:500],
                            "elapsed_minutes": round(elapsed / 60, 1),
                        },
                    }
                _rmtree_refine_session_root(session_root)
                logger.info(
                    "refine target %s timed out after %.1f min, cleaned before resubmit",
                    safe_name,
                    elapsed / 60,
                )
            elif st == "completed":
                return {
                    "errorcode": 409,
                    "message": "refine_session_pending_review",
                    "data": {
                        "target": safe_name,
                        "user_prompt": up[:500],
                    },
                }
            elif st == "error":
                _rmtree_refine_session_root(session_root)

        try:
            auth_content = auth_file.read_text(encoding="utf-8")
        except OSError as e:
            return error_response(500, f"read_authoritative_failed:{e}")

        _rmtree_refine_session_root(session_root)
        original_dir = session_root / "original"
        proposed_dir = session_root / "proposed"
        try:
            original_dir.mkdir(parents=True, exist_ok=True)
            proposed_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return error_response(500, f"mkdir_failed:{e}")

        original_copy = original_dir / safe_name
        proposed_copy = proposed_dir / safe_name
        original_copy.write_text(auth_content, encoding="utf-8")
        proposed_copy.write_text(auth_content, encoding="utf-8")

        run_id = uuid.uuid4().hex
        prof_id = f"__pkg_refine_{run_id}"
        started_ts = time.time()

        _write_refine_session_status(
            session_root,
            {
                "status": "pending",
                "run_id": run_id,
                "prod_name": body.prod_name,
                "doc_type": body.doc_type,
                "target": safe_name,
                "user_prompt": body.user_prompt,
                "started_at": started_ts,
            },
        )

        async def _run_refine_task() -> None:
            _write_refine_session_status(
                session_root,
                {
                    "status": "running",
                    "run_id": run_id,
                    "prod_name": body.prod_name,
                    "doc_type": body.doc_type,
                    "target": safe_name,
                    "user_prompt": body.user_prompt,
                    "started_at": started_ts,
                },
            )
            try:
                ep = (body.preferred_endpoint or "").strip() or None
                base_profile = get_profile_store().get("default") or AgentProfile(id="default", name="小鲸")
                _tmp_profile = replace(base_profile, id=prof_id, ephemeral=True, preferred_endpoint=ep)
                agent = await pool.get_or_create(run_id, _tmp_profile)

                enabled_ids = _get_enabled_rd_skill_ids(agent)
                rd_skills = _normalize_rd_skill_ids(body.rd_skill_ids, enabled_ids)

                refine_skills = list(rd_skills)
                if _REFINE_SKILL_ID in enabled_ids and _REFINE_SKILL_ID not in refine_skills:
                    refine_skills.append(_REFINE_SKILL_ID)

                final_profile = replace(
                    base_profile,
                    id=prof_id,
                    skills=refine_skills,
                    skills_mode=SkillsMode.INCLUSIVE,
                    ephemeral=True,
                    preferred_endpoint=ep,
                )
                pool.invalidate_profile(prof_id)
                agent = await pool.get_or_create(run_id, final_profile)

                skill_bodies: list[str] = []
                loader = getattr(agent, "skill_loader", None)
                if loader:
                    _skill_order = [_REFINE_SKILL_ID] + [s for s in refine_skills if s != _REFINE_SKILL_ID]
                    for sid in _skill_order:
                        skill = loader.get_skill(sid)
                        if skill and skill.body:
                            skill_path_line = f"**技能路径**: {skill.skill_dir}\n\n"
                            skill_bodies.append(f"### 研发技能：{sid}\n\n{skill_path_line}{skill.body}")

                skill_section = ""
                if skill_bodies:
                    skill_section = (
                        "\n\n---\n## 研发工具技能指引（请严格遵照以下指引执行任务）\n\n"
                        + "\n\n---\n\n".join(skill_bodies)
                    )
                refine_system = _REFINE_SYSTEM_PROMPT_BASE + skill_section

                # refine 允许 run_shell，用于源码缓存缺失时调用 gnx-tools.js materialize 拉取
                _REFINE_TOOL_NAMES = frozenset(
                    {"read_file", "write_file", "list_directory", "run_shell"}
                )
                _orig_tools = getattr(agent, "_tools", None)
                _slim_tools = (
                    [t for t in _orig_tools if t.get("name") in _REFINE_TOOL_NAMES]
                    if _orig_tools is not None
                    else None
                )

                _code_path = (body.code_path or "").strip()
                _repo_name_hint = ""
                if _code_path:
                    _repo_name_hint = _repo_name_from_git_url(_code_path) or Path(_code_path).name
                _gnx_cache_dir = (
                    str(_gitnexus_local_data_path(_repo_name_hint)) if _repo_name_hint else ""
                )

                # 获取 arch-create 技能的脚本目录路径，供 LLM 调用 gnx-tools.js
                _gnx_tools_script = ""
                if loader:
                    _arch_skill = loader.get_skill(_FALLBACK_RD_SKILL_ID)
                    if _arch_skill and _arch_skill.skill_dir:
                        _gnx_tools_script = str(
                            Path(_arch_skill.skill_dir) / "scripts" / "gnx-tools.js"
                        )

                product_ctx = f"""\
产品描述：[{body.product_desc}]
代码路径：[{body.code_path}]
主要功能：[{body.core_features}]
产品标识：[{body.prod_name}]
文档类型：[{body.doc_type}]
GitNexus 服务地址：[{body.gitnexus_url}]
源码缓存根目录：[{_gnx_cache_dir}]
gnx-tools.js 脚本路径：[{_gnx_tools_script}]"""

                user_message = f"""\
## 产品上下文（系统自动注入，请勿删除）
{product_ctx}

## 关于源码读取的说明
1. 优先检查「源码缓存根目录」下的 files/ 子目录是否存在且有内容（用 list_directory 检查）。
2. 若缓存存在，直接用 read_file / list_directory 读取，**无需拉取**。
3. 若缓存不存在或为空，使用 run_shell 执行以下命令拉取：
   node "{_gnx_tools_script}" materialize --url {body.gitnexus_url} --repo {_repo_name_hint} --cache {_gnx_cache_dir} --concurrency 8
4. 拉取完成后，源码位于「源码缓存根目录/files/」下，再用 read_file / list_directory 读取。

## 用户修改要求
{body.user_prompt}

## 待修改文件（仅允许修改下列路径对应的临时工作副本）
- {proposed_copy}

请按照技能 whalecloud-dev-tool-arch-modify 的工作流程执行：先读历史文档，再查阅或拉取源码，最后将修改后的完整文档写回上述路径。"""

                agent.default_cwd = str(docs_root)
                if getattr(agent, "shell_tool", None):
                    agent.shell_tool.default_cwd = str(docs_root)  # type: ignore[union-attr]
                agent._current_session_id = run_id

                _orig_org_context = getattr(agent, "_org_context", None)
                _orig_system = getattr(getattr(agent, "_context", None), "system", None)
                try:
                    agent._org_context = True  # type: ignore[attr-defined]
                    if hasattr(agent, "_context") and agent._context is not None:
                        agent._context.system = refine_system
                    if _slim_tools is not None:
                        agent._tools = _slim_tools  # type: ignore[attr-defined]

                    result = await asyncio.wait_for(
                        agent.execute_task_from_message(user_message),
                        timeout=3600.0,
                    )
                finally:
                    agent._org_context = _orig_org_context  # type: ignore[attr-defined]
                    if (
                        hasattr(agent, "_context")
                        and agent._context is not None
                        and _orig_system is not None
                    ):
                        agent._context.system = _orig_system
                    if _orig_tools is not None:
                        agent._tools = _orig_tools  # type: ignore[attr-defined]

                if not result.success:
                    _write_refine_session_status(
                        session_root,
                        {
                            "status": "error",
                            "run_id": run_id,
                            "prod_name": body.prod_name,
                            "doc_type": body.doc_type,
                            "target": safe_name,
                            "user_prompt": body.user_prompt,
                            "started_at": started_ts,
                            "error": result.error or "文档优化失败",
                        },
                    )
                    return

                # --- 读取 proposed 产物 ---
                proposed_text = ""
                if proposed_copy.is_file():
                    try:
                        proposed_text = proposed_copy.read_text(encoding="utf-8")
                    except OSError:
                        pass

                if not proposed_text.strip():
                    output = str(result.data) if result.data else ""
                    md_match = re.search(r"```markdown\s*(.*?)\s*```", output, re.DOTALL)
                    if md_match:
                        proposed_text = md_match.group(1)
                        try:
                            proposed_copy.write_text(proposed_text, encoding="utf-8")
                        except OSError:
                            pass

                if not proposed_text.strip():
                    _write_refine_session_status(
                        session_root,
                        {
                            "status": "error",
                            "run_id": run_id,
                            "prod_name": body.prod_name,
                            "doc_type": body.doc_type,
                            "target": safe_name,
                            "user_prompt": body.user_prompt,
                            "started_at": started_ts,
                            "error": "empty_proposed",
                        },
                    )
                    return

                _write_refine_session_status(
                    session_root,
                    {
                        "status": "completed",
                        "run_id": run_id,
                        "prod_name": body.prod_name,
                        "doc_type": body.doc_type,
                        "target": safe_name,
                        "user_prompt": body.user_prompt,
                        "started_at": started_ts,
                        "original": auth_content,
                        "proposed": proposed_text,
                    },
                )

            except TimeoutError:
                _write_refine_session_status(
                    session_root,
                    {
                        "status": "error",
                        "run_id": run_id,
                        "prod_name": body.prod_name,
                        "doc_type": body.doc_type,
                        "target": safe_name,
                        "user_prompt": body.user_prompt,
                        "started_at": started_ts,
                        "error": "agent_timeout",
                    },
                )
            except Exception as e:
                logger.exception("Knowledge refine background task failed")
                _write_refine_session_status(
                    session_root,
                    {
                        "status": "error",
                        "run_id": run_id,
                        "prod_name": body.prod_name,
                        "doc_type": body.doc_type,
                        "target": safe_name,
                        "user_prompt": body.user_prompt,
                        "started_at": started_ts,
                        "error": str(e),
                    },
                )
            finally:
                try:
                    pool.invalidate_profile(prof_id)
                except Exception:
                    pass

        asyncio.create_task(_run_refine_task())

        return success_response(
            {"target": safe_name},
            "文档优化任务已提交，请按 target 轮询 session/status 获取结果",
        )

    @router.post("/api/dev/iwhalecloud/product_knowledge/refine/session/status")
    def product_knowledge_refine_session_status(body: ProductKnowledgeRefineSessionBody) -> Any:
        """
        按 prod_name + doc_type + target 读取 refine_sessions/<target>/session.status。
        返回 status: none | pending | running | completed | error | timeout。
        pending/running 超过 1 小时：清理目录并返回 timeout；error：清理目录后返回 error。
        completed 不清理，供前端展示对比直至 close。
        """
        safe = _safe_docs_file_basename(body.target.strip())
        if not safe:
            return error_response(400, "invalid_target")
        docs_root = _knowledge_docs_root(body.doc_type, body.prod_name)
        session_root = _refine_target_session_root(docs_root, safe)
        raw = _read_refine_session_status(session_root)
        if not raw:
            return success_response({"status": "none", "target": safe})

        st = str(raw.get("status", "unknown"))
        started_at = float(raw.get("started_at", 0.0))
        elapsed = time.time() - started_at
        user_prompt = str(raw.get("user_prompt", ""))

        if st in ("pending", "running"):
            if elapsed >= _REFINE_SESSION_TIMEOUT_SECS:
                _rmtree_refine_session_root(session_root)
                return success_response(
                    {
                        "status": "timeout",
                        "target": safe,
                        "user_prompt": user_prompt,
                        "elapsed_minutes": round(elapsed / 60, 1),
                    },
                )
            return success_response(
                {
                    "status": st,
                    "target": safe,
                    "targets": [safe],
                    "user_prompt": user_prompt,
                    "started_at": started_at,
                    "run_id": raw.get("run_id", ""),
                },
            )

        if st == "completed":
            return success_response(
                {
                    "status": "completed",
                    "target": safe,
                    "targets": [safe],
                    "user_prompt": user_prompt,
                    "started_at": started_at,
                    "original": raw.get("original", ""),
                    "proposed": raw.get("proposed", ""),
                },
            )

        if st == "error":
            err = str(raw.get("error", "unknown_error"))
            _rmtree_refine_session_root(session_root)
            return success_response(
                {
                    "status": "error",
                    "target": safe,
                    "user_prompt": user_prompt,
                    "error": err,
                },
            )

        return success_response({"status": "none", "target": safe})

    @router.post("/api/dev/iwhalecloud/product_knowledge/refine/session/close")
    def product_knowledge_refine_session_close(body: ProductKnowledgeRefineSessionBody) -> Any:
        """接受/拒绝后删除 refine_sessions/<target>/。"""
        safe = _safe_docs_file_basename(body.target.strip())
        if not safe:
            return error_response(400, "invalid_target")
        docs_root = _knowledge_docs_root(body.doc_type, body.prod_name)
        session_root = _refine_target_session_root(docs_root, safe)
        removed = False
        if session_root.exists():
            try:
                shutil.rmtree(session_root, ignore_errors=True)
                removed = True
            except Exception as e:
                logger.warning("refine session close failed: %s", e)
        return success_response({"removed": removed}, "会话已关闭")
