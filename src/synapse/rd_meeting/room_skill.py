"""会议室运行时 system 上下文装配。

设计目标（对齐《多智能体研发会议室实现方案》§9）：

- 会议室通用规范来自 ``prompts/meeting_room_rules.md``（或 ``settings.rd_meeting_rules_path``），
  与 SKILL 加载机制无关，仅作为本会议室 Host 的 system 上下文片段。
- 同时渲染「参会能力卡片」（host 视角）/「你的能力档案」（worker 视角），让小鲸按能力
  边界派单、让 worker 清楚自己的身份与边界。
- `ask-user` 仍以独立 SKILL.md 形式存在（人机问卷格式与示例较多，单独维护）。

本模块只负责**装配 prompt 片段**，不直接调用 LLM；由 `orchestrator.run_current_node`
在执行节点时把渲染结果拼接到节点提示词中。
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from synapse.agents.profile import AgentProfile, get_profile_store
from synapse.rd_meeting.collaboration import collaboration_worker_ids
from synapse.rd_meeting.product_assets import resolve_repo_code_path
from synapse.rd_sop.nodes import node_display_name, stage_name_for_id

logger = logging.getLogger(__name__)

Role = Literal["host", "worker"]

DEFAULT_ASK_USER_SKILL_ID = "whalecloud-dev-tool-ask-user"
DEFAULT_LLM_ENDPOINT_KEY = "default"

# 默认会议室规则文件名（与本模块同级 prompts/ 目录）
_DEFAULT_RULES_FILENAME = "meeting_room_rules.md"


# ─── SKILL.md 定位（仅供 ask-user 等真正的外部 SKILL 使用） ────────────


def _candidate_skill_dirs() -> list[Path]:
    """按优先级返回外部 SKILL 可能的根目录。

    顺序：
    1. settings.skills_path（生产模式：~/.synapse/workspaces/<ws>/skills）
    2. settings.project_root / skills（开发模式或开源仓库内）
    3. 仓库内 fallback：`<repo_root>/skills`，从本文件路径反推
    """
    candidates: list[Path] = []
    try:
        from synapse.config import settings

        candidates.append(Path(settings.skills_path))
        candidates.append(Path(settings.project_root) / "skills")
    except Exception as exc:
        logger.debug("settings unavailable in room_skill: %s", exc)

    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "skills")
    except Exception:
        pass

    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def _find_external_skill_file(skill_id: str) -> Path | None:
    """在标准技能目录中查找外部 SKILL.md 文件（ask-user 等）。"""
    sid = (skill_id or "").strip()
    if not sid:
        return None
    for root in _candidate_skill_dirs():
        if not root.is_dir():
            continue
        path = root / sid / "SKILL.md"
        if path.is_file():
            return path
    return None


def load_ask_user_skill_body(skill_id: str = DEFAULT_ASK_USER_SKILL_ID) -> str:
    """读取人机问卷技能正文（host 专用片段，仍为外部 SKILL）。"""
    path = _find_external_skill_file(skill_id)
    if path is None:
        return ""
    try:
        return _strip_frontmatter(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("read ask-user skill %s failed: %s", path, exc)
        return ""


def get_meeting_room_rules() -> str:
    """返回会议室通用规范正文。

    优先级：
    1. ``settings.rd_meeting_rules_path``（私有化 / 多租户场景可指向自定义规则文件）
    2. 本模块同级 ``prompts/meeting_room_rules.md``（随仓库发布的默认版本）

    文件缺失或读盘失败时返回空字符串并打 error 日志。

    读取结果带 LRU 缓存。如需在运行时强制重载，调用
    :func:`reload_meeting_room_rules`。
    """
    text, _ = _load_meeting_room_rules()
    return text


def get_meeting_room_rules_meta() -> dict[str, str]:
    """返回当前生效规则的元数据：``source`` / ``sha256[:12]`` / ``length``。

    供调试 / 审计使用——例如把 hash 一并写进 ``hitl_submission.schema_snapshot``，
    便于复盘"那次会议跑成那样时用的是哪一版规则"。
    """
    text, source = _load_meeting_room_rules()
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return {"source": source, "sha256": digest, "length": str(len(text))}


def reload_meeting_room_rules() -> dict[str, str]:
    """清除规则缓存，下次取用时重新读盘。返回新的元数据。"""
    _load_meeting_room_rules.cache_clear()  # type: ignore[attr-defined]
    return get_meeting_room_rules_meta()


def _resolve_rules_path() -> Path | None:
    """按优先级解析规则文件路径。"""
    try:
        from synapse.config import settings

        override = getattr(settings, "rd_meeting_rules_path", "") or ""
        if isinstance(override, str) and override.strip():
            p = Path(override).expanduser()
            if p.is_file():
                return p
            logger.warning(
                "settings.rd_meeting_rules_path=%r not found, falling back to bundled rules",
                override,
            )
    except Exception as exc:
        logger.debug("settings.rd_meeting_rules_path lookup skipped: %s", exc)

    bundled = Path(__file__).resolve().parent / "prompts" / _DEFAULT_RULES_FILENAME
    if bundled.is_file():
        return bundled
    return None


def _load_meeting_room_rules_uncached() -> tuple[str, str]:
    """实际读盘逻辑，返回 (text, source_label)。"""
    path = _resolve_rules_path()
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
            return text, str(path)
        except OSError as exc:
            logger.error("read meeting room rules %s failed: %s", path, exc)
    else:
        logger.error(
            "meeting room rules file not found; expected prompts/%s or settings.rd_meeting_rules_path",
            _DEFAULT_RULES_FILENAME,
        )
    return "", "<missing>"


try:
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _load_meeting_room_rules() -> tuple[str, str]:  # type: ignore[no-redef]
        return _load_meeting_room_rules_uncached()
except Exception:  # pragma: no cover - lru_cache 总是可用，仅作防御
    def _load_meeting_room_rules() -> tuple[str, str]:  # type: ignore[no-redef]
        return _load_meeting_room_rules_uncached()


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    try:
        head, body = text.split("\n---", 1)
        if head.startswith("---"):
            body = body.lstrip("\n")
            return body
    except ValueError:
        return text
    return text



# ─── 数据结构 ───────────────────────────────────────────────────────────


@dataclass
class MeetingRoomContext:
    """会议室运行时上下文（用于装配 system prompt）。"""

    role: Role
    scope_type: str
    scope_id: str
    ticket_title: str
    node_id: str
    node_name: str
    node_intent: str
    stage_id: int
    stage_name: str
    host_profile_id: str
    host_profile_name: str
    host_llm_endpoint: str
    worker_llm_endpoint: str
    worker_profile_ids: list[str]
    archive_dir: str
    prompt_supplement: str = ""
    self_profile_id: str = ""

    def template_vars(self) -> dict[str, str]:
        """流程 / 路径类占位符。

        新版规则段已不依赖这些变量（运行时头与「系统信息」段直接展示具体值），
        但保留映射以便测试 / 自定义 `skill_body` 时仍能渲染。
        """
        return {
            "ROLE": self.role,
            "HOST_PROFILE_ID": self.host_profile_id,
            "HOST_PROFILE_NAME": self.host_profile_name,
            "HOST_LLM_ENDPOINT": self.host_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY,
            "WORKER_LLM_ENDPOINT": self.worker_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY,
            "ARCHIVE_DIR": self.archive_dir,
            "STAGE_ID": str(self.stage_id),
            "NODE_ID": self.node_id,
        }


# ─── 能力卡片 ───────────────────────────────────────────────────────────


def resolve_agent_profile(profile_id: str) -> AgentProfile | None:
    """解析参会智能体 Profile（供 dynamic_prompt 等模块使用）。"""
    return _resolve_profile(profile_id)


def _resolve_profile(profile_id: str) -> AgentProfile | None:
    pid = (profile_id or "").strip()
    if not pid:
        return None
    try:
        store = get_profile_store()
        p = store.get(pid)
        if p is not None:
            return p
    except Exception as exc:
        logger.debug("get_profile_store failed for %s: %s", pid, exc)
    try:
        from synapse.agents.presets import SYSTEM_PRESETS

        for sp in SYSTEM_PRESETS:
            if sp.id == pid:
                return sp
    except Exception:
        return None
    return None


_SKILL_LABEL_CACHE: dict[str, str | None] = {}


def _normalize_skill_id(skill_ref: str) -> str:
    norm = str(skill_ref).strip()
    if not norm:
        return ""
    return norm.split("@", 1)[-1] if "@" in norm else norm


def resolve_skill_label(skill_id: str) -> str | None:
    """从 SKILL.md frontmatter 读取 ``label``（与 Setup Center 展示一致）。"""
    sid = _normalize_skill_id(skill_id)
    if not sid:
        return None
    if sid in _SKILL_LABEL_CACHE:
        return _SKILL_LABEL_CACHE[sid]
    label: str | None = None
    path = _find_external_skill_file(sid)
    if path is not None:
        try:
            from synapse.skills.parser import skill_parser

            parsed = skill_parser.parse_file(path)
            raw = parsed.metadata.label
            if raw and str(raw).strip():
                label = str(raw).strip()
        except Exception as exc:
            logger.debug("resolve skill label %s failed: %s", sid, exc)
    _SKILL_LABEL_CACHE[sid] = label
    return label


def format_skill_entry(skill_ref: str) -> str:
    """展示用：``skill_id（label）``；无 label 时仅 id。"""
    sid = _normalize_skill_id(skill_ref)
    if not sid:
        return ""
    label = resolve_skill_label(sid)
    if label:
        return f"{sid}（{label}）"
    return sid


def format_skill_entries(skills: Iterable[str], *, limit: int = 0) -> list[str]:
    out: list[str] = []
    for s in skills:
        entry = format_skill_entry(str(s))
        if not entry:
            continue
        out.append(entry)
        if limit and len(out) >= limit:
            break
    return out


def _short_skill_names(skills: Iterable[str], limit: int = 6) -> list[str]:
    """兼容旧调用：仅返回 skill id（不含 label）。"""
    out: list[str] = []
    for s in skills:
        sid = _normalize_skill_id(str(s))
        if not sid:
            continue
        out.append(sid)
        if len(out) >= limit:
            break
    return out


def _format_capability_card(
    profile: AgentProfile,
    *,
    role: str,
    llm_endpoint: str,
) -> str:
    name = profile.get_display_name() or profile.name or profile.id
    skills = format_skill_entries(profile.skills or [], limit=6)
    desc = (profile.description or "").strip()
    custom = (profile.custom_prompt or "").strip()

    lines: list[str] = []
    lines.append(f"## {name} (`{profile.id}`)")
    lines.append(f"- 角色：{role} · 端点：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`")
    if desc:
        lines.append(f"- 简介：{desc}")
    if skills:
        lines.append(f"- 核心技能：{', '.join(skills)}")
    if custom:
        short = re.sub(r"\s+", " ", custom).strip()
        if len(short) > 160:
            short = short[:160] + "…"
        lines.append(f"- 主张：{short}")
    return "\n".join(lines)


def _format_self_capability_block(
    profile: AgentProfile | None,
    *,
    fallback_id: str,
    llm_endpoint: str,
) -> str:
    """渲染 Worker 视角下「你的能力档案」段：用第一人称语气强化身份与边界。

    与 `_format_capability_card` 的区别：
    - 不显示"角色：worker"（已在顶部"当前角色"中说明）
    - 主张不截断，完整展示其 custom_prompt
    - 若 profile 找不到则给出兜底身份说明
    """
    if profile is None:
        return (
            f"- **智能体 ID**：`{fallback_id or '(unknown)'}`\n"
            f"- **使用端点**：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`\n"
            "- **简介**：未在 Profile 库中找到你的档案，请按通用研发协作者身份执行；遇到不确定时主动反问小鲸。"
        )

    name = profile.get_display_name() or profile.name or profile.id
    skills = format_skill_entries(profile.skills or [], limit=12)
    desc = (profile.description or "").strip()
    custom = (profile.custom_prompt or "").strip()

    lines: list[str] = []
    lines.append(f"- **身份**：{name}（`{profile.id}`）")
    lines.append(f"- **使用端点**：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`")
    if desc:
        lines.append(f"- **简介**：{desc}")
    if skills:
        lines.append(f"- **你具备的技能**（仅在这些范围内执行任务）：")
        for s in skills:
            lines.append(f"  - {s}")
    if custom:
        lines.append("- **角色主张 / 工作风格**：")
        for line in custom.splitlines():
            t = line.rstrip()
            if t:
                lines.append(f"  > {t}")
    return "\n".join(lines)


def build_capability_cards(
    *,
    host_profile_id: str,
    worker_profile_ids: list[str],
    host_llm_endpoint: str,
    worker_llm_endpoint: str,
    exclude_self_id: str | None = None,
    include_host: bool = True,
) -> str:
    """渲染参会智能体能力卡片清单。

    - `exclude_self_id`: 排除「自己」的 worker 卡片，避免自我介绍冗余。
    - `include_host`: 是否渲染 host 卡片。host 视角下应传 ``False``（自己就是小鲸，
      无需再看自己的卡片）；worker 视角下保留 host 卡片，便于明确主持人身份。
    """
    cards: list[str] = []

    if include_host and (not exclude_self_id or exclude_self_id != host_profile_id):
        host_profile = _resolve_profile(host_profile_id)
        if host_profile is not None:
            cards.append(_format_capability_card(host_profile, role="host", llm_endpoint=host_llm_endpoint))

    for wid in worker_profile_ids or []:
        wid = str(wid).strip()
        if not wid or wid == host_profile_id:
            continue
        if exclude_self_id and wid == exclude_self_id:
            continue
        wp = _resolve_profile(wid)
        if wp is None:
            cards.append(
                f"## {wid}\n- 角色：worker · 端点：`{worker_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`\n"
                "- 简介：未在 Profile 库中找到，使用兜底身份。"
            )
            continue
        cards.append(
            _format_capability_card(
                wp,
                role="worker",
                llm_endpoint=worker_llm_endpoint,
            )
        )

    if not cards:
        return "（除你之外暂无其他参会智能体；如需协作请在『系统智能体管理』中配置。）"

    return "\n\n".join(cards)


# ─── 角色裁剪 + 渲染 ────────────────────────────────────────────────────


def trim_skill_for_role(skill_body: str, role: Role) -> str:
    """按角色返回流程规则正文。

    - ``host``：原样返回（规则段仅给 host 看）。
    - ``worker``：返回空字符串——worker 的边界与协作要点已在运行时头的
      「协作专家职责」+「你的能力档案」中说清楚，不再追加任何长文规范。
    """
    if role == "worker":
        return ""
    return skill_body


def render_skill(skill_body: str, variables: dict[str, str]) -> str:
    """填充规范正文中的占位符。

    新版规则段已不含 ``{ROLE}`` / ``{ARCHIVE_DIR}`` / ``{DYNAMIC_MEETING_CONTEXT}`` 等占位
    （这些信息全部在运行时头与「系统信息」段直接展示），本函数仅作为兼容入口保留。
    """
    rendered = skill_body
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _resolve_archive_output_dir(
    *,
    work_dir: str,
    scope_id: str = "",
    stage_name: str = "",
    node_id: str = "",
    archive_dir: str = "",
    system: dict[str, Any] | None = None,
) -> str:
    """解析本节点会议产出目录 ``work/<scope>/archive/<stage_name>/<node_id>/``。"""
    sys_map = system if isinstance(system, dict) else {}
    ad = (archive_dir or str(sys_map.get("archive_dir") or "")).strip()
    if ad:
        return ad

    sid = (scope_id or str(sys_map.get("scope_id") or "")).strip()
    nid = (node_id or str(sys_map.get("node_id") or "")).strip()
    stg = (stage_name or str(sys_map.get("stage_name") or "")).strip()
    if sid and nid:
        from synapse.rd_meeting.paths import archive_node_dir
        from synapse.rd_sop.nodes import stage_id_for_node_id, stage_name_for_id

        if not stg:
            stg = stage_name_for_id(stage_id_for_node_id(nid))
        return str(archive_node_dir(sid, stg, nid))

    wo = (work_dir or str(sys_map.get("work_order_dir") or "")).strip()
    if wo and stg and nid:
        from synapse.rd_meeting.paths import archive_stage_segment

        return str(Path(wo) / "archive" / archive_stage_segment(stg) / nid)
    return ""


def build_product_workspace_paths_section(
    init_context: dict[str, Any] | None,
    *,
    scope_id: str = "",
    stage_name: str = "",
    node_id: str = "",
    archive_dir: str = "",
) -> str:
    """渲染 room_opened 落盘后的产品代码 / 文档路径（Host / Worker 必读）。"""
    if not isinstance(init_context, dict):
        return ""
    product = init_context.get("product")
    system = init_context.get("system")
    prod = product if isinstance(product, dict) else {}
    sys_map = system if isinstance(system, dict) else {}

    code_root = str(prod.get("code_root") or sys_map.get("product_code_root") or "").strip()
    doc_root = str(prod.get("doc_root") or sys_map.get("product_doc_root") or "").strip()
    work_dir = str(prod.get("work_order_dir") or sys_map.get("work_order_dir") or "").strip()
    if not code_root and not doc_root and not work_dir:
        return ""

    lines: list[str] = ["## 产品工作区路径（room_opened 已落盘，必读）", ""]
    lines.append(
        "- **约定**：产品源码在 `work/<scope>/code/<repo_name>/`；"
        "产品文档在 `work/<scope>/doc/<doc_type>/`。"
        "读代码 / 文档时**必须**使用下列路径，**禁止**臆造目录。"
    )
    if work_dir:
        lines.append(f"- **工单工作目录**：`{work_dir}`")
    if code_root:
        lines.append(f"- **产品代码根目录**：`{code_root}`")
    repos = prod.get("repos")
    if isinstance(repos, list):
        for r in repos:
            if not isinstance(r, dict):
                continue
            name = str(r.get("repo_name") or "仓库").strip()
            local = str(r.get("local_path") or "").strip()
            code_path = str(r.get("code_path") or "").strip()
            resolved = str(r.get("resolved_code_path") or "").strip() or resolve_repo_code_path(
                local_path=local,
                repo_name=name,
                code_path=code_path,
                code_root=code_root,
            )
            if not resolved:
                continue
            st = str(r.get("materialize_status") or "").strip()
            note = f"（{st}）" if st and st != "ok" else ""
            lines.append(f"  - 代码 `{name}` 路径参数：")
            lines.append(f"    REPO_NAME：{name}")
            lines.append(f"    CODE_PATH：{resolved}{note}")
    if doc_root:
        lines.append(f"- **产品文档根目录**：`{doc_root}`")
    docs = prod.get("docs")
    if isinstance(docs, list):
        for d in docs:
            if not isinstance(d, dict):
                continue
            local = str(d.get("local_path") or "").strip()
            if not local:
                continue
            dtype = str(d.get("doc_type") or "文档").strip()
            st = str(d.get("materialize_status") or "").strip()
            note = f"（{st}）" if st and st != "ok" else ""
            lines.append(f"  - 文档 `{dtype}`：`{local}`{note}")

    archive_path = _resolve_archive_output_dir(
        work_dir=work_dir,
        scope_id=scope_id,
        stage_name=stage_name,
        node_id=node_id,
        archive_dir=archive_dir,
        system=sys_map,
    )
    if archive_path:
        lines.append(f"- **会议产出路径（OUTPUT_DIR / ARCHIVE_DIR）**：`{archive_path}`")
    lines.append("")
    return "\n".join(lines)


def _extract_product_label(init_context: dict[str, Any] | None) -> str:
    """从 init_context 中提取『涉及产品』展示值。"""
    if not isinstance(init_context, dict):
        return "（未识别产品）"
    product = init_context.get("product")
    if not isinstance(product, dict):
        return "（未识别产品）"
    prod = str(product.get("prod") or "").strip()
    version = str(product.get("version") or "").strip()
    name = str(product.get("name") or product.get("product_name") or "").strip()
    suffix = f"@{version}" if version else ""
    if name and prod:
        return f"{name}（prod=`{prod}`{suffix}）"
    if prod:
        return f"`{prod}`{suffix}"
    if name:
        return name
    return "（未识别产品）"


def _human_confirm_label(binding: dict[str, Any] | None) -> str:
    if not isinstance(binding, dict):
        return "未配置"
    if binding.get("human_confirm"):
        return "**开启**（中途待确认内容及会议结果均需用户表单确认后才能推进）"
    return "关闭（自动处理推进会议, 不需要和人工交互）"


def _format_hitl_artifact_lines(
    binding: dict[str, Any] | None,
    *,
    scope_id: str,
    stage_name: str,
    node_id: str,
) -> list[str]:
    """``human_confirm`` 开启时展示人机台账绝对路径与用途说明。"""
    if not isinstance(binding, dict) or not binding.get("human_confirm"):
        return []
    nid = (node_id or "").strip()
    sid = (scope_id or "").strip()
    if not sid or not nid or nid == "pending":
        return []

    from synapse.rd_meeting.hitl_confirmed import resolve_stage_name_for_node
    from synapse.rd_meeting.hitl_context import HITL_CONTEXT_FILENAME, hitl_context_path

    stg = (stage_name or "").strip() or resolve_stage_name_for_node(nid, binding)
    if not stg:
        return []

    ctx_abs = str(hitl_context_path(sid, stg, nid).resolve())
    return [
        f"- **人工确认产物（机器台账）**：`{ctx_abs}`（`{HITL_CONTEXT_FILENAME}`）",
        "  - 仅 **interactive** 问卷提交时由系统自动维护；含各轮结构化确认与 ``confirmed_by_id`` 汇总。",
        "  - 生成上方「会议产出」Markdown **之前**必须 ``read_file`` 该路径并综合全量确认项；"
        f"``whalecloud-dev-tool-doc-generate`` 的 ``CONTEXT_JSON`` 应指向该文件；**禁止**自写 ``clarify_context.json`` 等替代台账。",
    ]

def format_reprocess_instruction(scope_id: str, node_id: str) -> str:
    """若存在一次性重处理原因，渲染须注入 system 的说明段。"""
    from synapse.rd_meeting.room_runtime import load_room_state

    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid:
        return ""
    rs = load_room_state(sid) or {}
    reason = str(rs.get("reprocess_reason") or "").strip()
    if not reason:
        return ""

    node_label = f"`{nid}`" if nid else "当前节点"
    lines = [
        "## 重新处理指令（用户发起，必须遵循）",
        "",
        f"- **状态**：本节点 {node_label} 正处于**重新处理**流程（非首次执行）。",
        f"- **用户要求**：{reason}",
        "- **硬性约束**：你必须按照上述用户重处理的想法与意图进行处理，"
        "不得以旧结论搪塞；若与历史产出冲突，以用户本次重处理要求为准。",
    ]
    return "\n".join(lines)


def _format_meeting_outputs(binding: dict[str, Any] | None) -> str:
    """从 binding.node_outputs 渲染「会议产出」展示串（与归档强约束一一对应）。"""
    if not isinstance(binding, dict):
        return "（未配置会议产出，可能为系统节点或配置缺失）"
    outs = [
        str(n).strip()
        for n in (binding.get("node_outputs") or [])
        if str(n).strip() and not str(n).strip().startswith("（")
    ]
    if not outs:
        return "（未配置会议产出，可能为系统节点或配置缺失）"
    return "、".join(f"`{n}`" for n in outs)


def _append_host_duties_shared(lines: list[str], context: MeetingRoomContext) -> None:
    """主持职责：有/无协作智能体共用。"""
    lines.append(
        "- 必须熟悉本工单对应的产品信息（产品文档 / 仓库代码 / 历史工单），"
        "所有决策都要基于产品事实；缺少产品事实时可以拒绝或报错，**不得臆造**。"
    )
    lines.append(
        "- 基于产品事实，**专注于上方「会议目标」中要做的具体事情**，不进行超出本节点目标的决策。"
    )
    lines.append(
        "- **用户反馈内容持久化**（共性原则）：用户反馈的内容（包括澄清、澄清后的问题）"
        "必须持久化到临时文件中，供下一轮迭代使用；**禁止**用户反馈内容丢失。"
    )
    lines.append(
        "- **多轮迭代继承上一轮结果**（共性原则）：上一轮已被认可 / 校验通过的结论**直接视为既成事实**，"
        "已被指正的按最新口径覆盖、新增想法纳入推演；下一轮**只**推进未决 / 新增 / 需重做的部分，"
        "**禁止**推倒重来或重复审问已通过项；详见下方规范 §3.1。"
    )
    if (context.node_id or "").strip() == "solution_review":
        lines.append(
            "- **方案评审节点（专用流程）**：须执行 `whalecloud-dev-tool-solution-review` 生成 "
            "`solution_review.json` 与 `方案评审结论.md`；**禁止** `submit_hitl_questionnaire(kind=interactive)`。"
            "人工评审由前端「方案评审」面板完成（补丁选择 + 通过/不通过），系统会自动进入门控。"
        )
    lines.append(
        "- **`human_confirm: true` 时**：每轮决策都通过 HITL 表单交由用户裁决；"
        "当用户无新想法亦无新指正时即视为本轮收敛。"
    )
    lines.append(
        '- **`human_confirm: false` 时**：不发表单，由你自评收敛质量——若三项校验（契合度 / 真实性 / 准确性）'
        "有任一不通过、证据缺失、产出相互矛盾、或决策高影响，则**必须再迭代一轮**；"
        "三项全过且产出已覆盖「会议产出」清单时才能归档；自主迭代原则上**不超过 3 轮**，"
        '仍未收敛时升级为 `submit_hitl_questionnaire(kind="exception", ...)` 请求人工介入。'
    )
    lines.append(
        "- 节点目标完成且通过自检后，按下方规范第 6 节归档到「本节点归档目录」"
        "（系统信息段已展示完整路径，并带阶段名 · 节点名便于识别）并报告结论。"
    )
    lines.append(
        "- **会议产出 = 归档文件名（硬约束）**：上方「会议产出」列出的就是本节点必须落盘的文件，"
        "归档文件名必须与之**逐字一致**（如 `需求澄清.md`、`模块功能.md`），"
        "**禁止**改名 / 加前后缀 / 用 `result.md` 替代；多文件时每一项都要落盘，且不能多出清单之外的文件。"
    )
    lines.append(
        '- **必须走 `whalecloud-dev-tool-doc-generate` 生成产出物**：先 `get_skill_info(whalecloud-dev-tool-doc-generate)` '
        "读 SKILL.md、确认 `templates/` 下存在与预期产出物**同名**的模板；"
        "若运行时头已给出 `hitl_context.json` 路径且文件存在，**必须先** `read_file` 该路径，"
        '再以之为 `CONTEXT_JSON` 调用 doc-generate 落盘；若模板缺失或与本节点产出物不匹配，**立即** '
        '`submit_hitl_questionnaire(kind="exception", summary="doc-generate 缺少 <文件名> 模板，需人工补齐模板或调整产出物清单")` '
        "请求人工介入，**禁止**自行手写 Markdown 兜底。"
    )
    lines.append(
        '- **`result_confirm` 不得整篇覆盖会议产出**：节点验收问卷仅用于确认/返工指令，'
        "禁止用验收轮反馈直接重写已归档的「会议产出」全文。"
    )
    lines.append(
        "- `human_confirm` 开启或出现异常 / 风险不可控时，必须调用 `submit_hitl_questionnaire`，"
        "**禁止伪造用户答复**，**禁止只口头宣称问卷已提交**。"
    )


def _append_host_duties_with_collaborators(lines: list[str]) -> None:
    """主持职责：本场有协作智能体。"""
    lines.append(
        "- **事实先于分析（强约束）**：委派分析型 SKILL 前，须先完成或并行完成代码/文档/相似工单事实收集；"
        "除非用户反馈了明确的分析方向, 否则禁止在指派任务时圈定范围或维度。"
    )
    lines.append(
        "- **委派 message 白名单（强约束）**：`delegate_to_agent(message=...)` **禁止**写入「方案原文」"
        "「拆解要求/维度」「待澄清问题清单」及任何未经核验的技术细节；"
        "只允许 skill/Phase、任务边界、工单字段原文引用、指向前序 Worker 已核验产出。详见下方规范 §3.0。"
    )
    lines.append(
        "- 产品事实收集**优先委派**给协作智能体，且须在分析型 SKILL 派单之前完成或并行启动；"
        "当且仅当现有 worker 不具备某项能力时，才自行调用工具/技能收集。"
    )
    lines.append(
        "- 必须通过 `submit_meeting_work_plan` 提交结构化计划后，再调用 `delegate_to_agent` 或 "
        "`delegate_parallel` 派单；委派后等待 worker 返回再继续。"
    )
    lines.append(
        "- 收到 worker 产出后，按「契合度 / 真实性 / 准确性」三项逐条校验；"
        "不通过则**重新派单**给同一 worker 并指出缺项。"
    )
    lines.append(
        "- 可用 worker 名单与能力边界见下方「参会能力卡片」（已排除你自己）；"
        "派单时 task 描述应指向卡片上的具体 skill / 能力，便于 Worker 加载对应 SKILL。"
    )
    lines.append(
        "- 派单时 `message` 只写编排指令（skill/Phase/边界/原文引用），"
        "**禁止**替 Worker 撰写方案描述或需求拆解框架；违规示例见规范 §3.0。"
    )
    lines.append(
        "- 若你（Host）自身 Profile 也配置了技能且必须自行执行（Worker 不具备时），"
        "同样须先 `get_skill_info(skill_id)` 读取 SKILL.md，再按 SKILL 指引用 shell / 读写工具执行，"
        "需要调用技能的脚本时再执行`run_skill_script`, **禁止**跳过 SKILL 硬猜流程。"
    )


def _append_host_duties_solo(lines: list[str]) -> None:
    """主持职责：本场无协作智能体，小鲸独立处理。"""
    lines.append(
        "- **本场无协作智能体（小鲸独立处理）**：本节点由你一人完成；"
        "**无需** `submit_meeting_work_plan`，**禁止** `delegate_to_agent` / `delegate_parallel`。"
        "完整流程见规范 §3.2。"
    )
    lines.append(
        "- **事实先于分析（强约束）**：跑分析型 SKILL 前，须先用 `read_file` / `run_shell` / "
        "`get_skill_info` + 技能脚本自行完成代码 / 文档 / 相似工单事实收集；"
        "除非用户反馈了明确分析方向，否则禁止在未取证前圈定范围或维度。"
    )
    lines.append(
        "- 直接按「你的能力档案」与会议目标执行 SKILL / 工具；"
        "勿调用 `submit_meeting_work_plan`（无 Worker 时系统会拒绝）。"
    )
    lines.append(
        "- 每轮产出（含 SKILL 落盘文件）后，对你自己的结果按「契合度 / 真实性 / 准确性」三项自检；"
        "不通过则在本会话内补证据 / 重跑 SKILL / 修正归档，**禁止**调用 delegate（无对象可派）。"
    )
    lines.append(
        "- 执行边界以「你的能力档案」为准；须先 `get_skill_info(skill_id)` 再按 SKILL 用 shell / 读写 / "
        "`run_skill_script` 执行，**禁止**跳过 SKILL 硬猜流程。"
    )


def _append_host_capability_cards_with_collaborators(lines: list[str], cards: str) -> None:
    """参会能力卡片：有协作智能体。"""
    lines.append("## 参会能力卡片")
    lines.append("")
    lines.append("以下是本场会议可用的协作智能体（不含你自己），分派任务时必须先比对其能力边界：")
    lines.append("")
    lines.append(cards)


def build_meeting_runtime_header(
    context: MeetingRoomContext,
    *,
    now_iso: str | None = None,
    binding: dict[str, Any] | None = None,
    init_context: dict[str, Any] | None = None,
) -> str:
    """生成"运行时头"——替代原 Identity / Catalogs / Multi-Agent 段。

    Host 与 Worker 各加一段角色专属说明；末尾附参会能力卡片。
    无论 host 还是 worker，能力卡片都会**排除自己**，避免自我介绍冗余。
    """
    from datetime import datetime as _dt

    role = context.role
    self_pid = (context.self_profile_id or "").strip()
    if not self_pid:
        if role == "host":
            self_pid = context.host_profile_id
        elif context.worker_profile_ids:
            self_pid = context.worker_profile_ids[0]

    role_label = "小鲸主持人" if role == "host" else "协作专家"
    now = (now_iso or _dt.now().isoformat(timespec="seconds")).strip()
    product_label = _extract_product_label(init_context)
    confirm_label = _human_confirm_label(binding)
    meeting_outputs_label = _format_meeting_outputs(binding)
    supplement = ""
    if isinstance(binding, dict):
        supplement = str(binding.get("prompt_supplement") or "").strip()
    if not supplement:
        supplement = (context.prompt_supplement or "").strip()

    lines: list[str] = []
    lines.append("# 你是 Synapse 研发会议室参会智能体")
    lines.append("")
    lines.append(f"- **当前角色**：{role_label}（`role={role}`）")
    lines.append(f"- **会议工单**:[`{context.scope_id}`]-{context.ticket_title}")
    lines.append(f"- **涉及产品**：{product_label}")
    lines.append(f"- **会议任务**：{context.stage_name}阶段的{context.node_name}任务")
    lines.append(f"- **会议产出**：{meeting_outputs_label}（最终归档文件名必须**完全等于**这里列出的名字；详见下方归档约束）")
    lines.append(f"- **会议目标**：{context.node_intent}")
    reprocess_block = format_reprocess_instruction(context.scope_id, context.node_id)
    if reprocess_block:
        lines.append("")
        lines.append(reprocess_block)
    lines.append(f"- **人工确认**：{confirm_label}")
    lines.extend(
        _format_hitl_artifact_lines(
            binding,
            scope_id=context.scope_id,
            stage_name=context.stage_name,
            node_id=context.node_id,
        )
    )
    from synapse.rd_meeting.prior_outputs import (
        format_prior_sop_outputs_section,
        load_skipped_node_ids,
    )

    prior_block = format_prior_sop_outputs_section(
        context.scope_id,
        context.node_id,
        skipped_node_ids=load_skipped_node_ids(context.scope_id),
    )
    if prior_block:
        lines.append("")
        lines.append(prior_block.rstrip())

    lines.append(f"- **当前时间**：{now}")
    lines.append("- **回复语言**：中文")
    if supplement:
        lines.append(f"- **运营补充**：{supplement}")
    paths_block = build_product_workspace_paths_section(
        init_context,
        scope_id=context.scope_id,
        stage_name=context.stage_name,
        node_id=context.node_id,
        archive_dir=context.archive_dir,
    )
    if paths_block:
        lines.append("")
        lines.append(paths_block.rstrip())
    lines.append("")

    solo_host = False
    if role == "host":
        solo_host = not collaboration_worker_ids(
            context.host_profile_id,
            context.worker_profile_ids,
        )
        lines.append("## 主持人职责")
        _append_host_duties_shared(lines, context)
        if solo_host:
            _append_host_duties_solo(lines)
        else:
            _append_host_duties_with_collaborators(lines)
    else:
        lines.append("## 协作专家职责")
        lines.append(
            "- 必须调用并优先调用 `create_todo` 创建任务计划；每完成一步用 `update_todo_step` 更新状态，"
            "需要时用 `get_todo_status` 查看进度，全部完成后 `complete_todo` 收尾，然后再执行具体操作"
        )
        lines.append("- 必须熟悉本工单对应的产品信息（产品文档 / 仓库代码 / 历史工单），所有决策都要基于产品事实；缺少产品事实时可以拒绝或报错，**不得臆造**。")
        lines.append("- 你是子 Agent，**禁止再发起委派**（不要调用 delegate_to_agent / delegate_parallel），也无法直接联系其他 Worker；任何「需要别人配合」的诉求都改为在产出里向小鲸说明。")
        lines.append("- 仅在「你的能力档案」描述的能力边界内执行任务；超出边界时**坦诚向小鲸说明**并建议改派，不要勉强执行、不要伪造结果。")
        lines.append(
            "- **接到子任务后**，先看 system「已挂载技能（摘要）」确认 skill_id，"
            "再 `get_skill_info(skill_id)` 加载完整 SKILL.md 后执行；"
            "**禁止**拉全量技能列表，**禁止**未读 SKILL 就用通用工具硬做。"
        )
        lines.append("- 输出必须自给自足：含结论、证据、产物路径；Markdown 一级标题，结尾含「结论」「完成」或「交付」。")
        lines.append("- 你看不到主会话历史，也看不到其他 Worker 的能力卡片。工单/产品/系统参数在 system prompt「系统信息」段；委派 message 中的分析性描述若无来源标注，**不得采信**，须自行通过 SKILL 从代码/文档/工单获取事实。")

    lines.append("")
    lines.append("## 工具与技能使用")
    lines.append(
        "- **可用工具**（本会话已裁剪，仅暴露任务所需项；禁止伪造工具输出）："
        "run_shell / read_file / write_file / list_directory / web_search / "
        "create_todo / update_todo_step / get_todo_status / complete_todo "
        "get_skill_info / run_skill_script / get_skill_reference 等。"
    )
    if role == "host":
        lines.append(
            "- **Host 额外工具**：submit_meeting_work_plan、submit_hitl_questionnaire、"
            "delegate_to_agent、delegate_parallel、send_agent_message。"
        )
    lines.append("- **外部技能（SKILL）执行路径（强约束）**：")
    skill_id_hint = (
        "「你的能力档案」"
        if role == "host" and solo_host
        else "「参会能力卡片」/「你的能力档案」"
    )
    lines.append(
        f"  1. system「已挂载技能（摘要）」仅含元数据；"
        f"从{skill_id_hint}确认 skill_id 后，"
        "**必须先** `get_skill_info(skill_id)` 加载完整 SKILL.md。"
    )
    lines.append(
        "  2. 需要参考文档时用 `get_skill_reference`；有预置脚本时用 `run_skill_script`。"
    )
    lines.append(
        "  3. instruction-only 技能按 get_skill_info 指引写代码并 `run_shell` / 读写文件；"
        "**禁止**列举全库技能（本会话不提供 list_skills）。"
    )
    lines.append("- 任何结论必须可由源码、文档或工单证据回溯；严禁虚构。")
    lines.append("")

    if role == "host" and not solo_host:
        cards = build_capability_cards(
            host_profile_id=context.host_profile_id,
            worker_profile_ids=context.worker_profile_ids,
            host_llm_endpoint=context.host_llm_endpoint,
            worker_llm_endpoint=context.worker_llm_endpoint,
            exclude_self_id=self_pid or None,
            include_host=False,
        )
        _append_host_capability_cards_with_collaborators(lines, cards)

    
    self_profile = _resolve_profile(self_pid) if self_pid else None
    self_block = _format_self_capability_block(
        self_profile,
        fallback_id=self_pid,
        llm_endpoint=context.worker_llm_endpoint,
    )
    lines.append("## 你的能力档案")
    lines.append("")
    lines.append("这是小鲸在本节点为你配置的角色档案——所有任务都必须在此边界内执行；超界即向小鲸申请改派，不要勉强或臆造。")
    lines.append("")
    lines.append(self_block)
    lines.append("")
    return "\n".join(lines)


def build_room_skill_prompt(
    context: MeetingRoomContext,
    *,
    skill_body: str | None = None,
    init_context: dict[str, Any] | None = None,
    binding: dict[str, Any] | None = None,
    sop_node_display: str = "",
) -> str:
    """生成会议室完整 system prompt。

    结构（精简后，参见 docs `多智能体研发会议室实现方案.md` §9）：

    1. **运行时头**（`build_meeting_runtime_header`）—— Host / Worker 都看：
       身份、工单、会议任务/目标、人工确认、时间、角色职责、工具通则、能力卡片或能力档案。
    2. **系统信息**（`build_dynamic_meeting_context(include_overview=False)`）—— 都看：
       仅工单 / 产品 / 系统三段；运行时头已展示的「会议节点/会议目标/人工确认/协作智能体」
       不再重复。
    3. **会议室流程与规则**（``prompts/meeting_room_rules.md``）—— **仅 Host** 追加：
       节点成功标准、HITL 语义、工作循环、产品上下文加载、HITL 三场景与 summary 约束、
       归档要求、不变量。

    `skill_body` 仅供测试 / 缓存等场景覆盖。
    """
    from synapse.rd_meeting.dynamic_prompt import build_dynamic_meeting_context

    bind = dict(binding) if binding else {
        "node_id": context.node_id,
        "node_name": context.node_name,
        "stage_id": context.stage_id,
        "stage_name": context.stage_name,
        "node_intent": context.node_intent,
        "host_profile_id": context.host_profile_id,
        "worker_profile_ids": context.worker_profile_ids,
        "host_llm_endpoint_key": context.host_llm_endpoint,
        "worker_llm_endpoint_key": context.worker_llm_endpoint,
        "prompt_supplement": context.prompt_supplement,
        "human_confirm": False,
    }

    header = build_meeting_runtime_header(
        context,
        binding=bind,
        init_context=init_context,
    )

    system_info = build_dynamic_meeting_context(
        binding=bind,
        init_data=init_context,
        scope_type=context.scope_type,  # type: ignore[arg-type]
        scope_id=context.scope_id,
        sop_node_display=sop_node_display or context.node_name,
        include_overview=False,
    )

    body = skill_body if skill_body is not None else get_meeting_room_rules()
    body = trim_skill_for_role(body, context.role)
    rules_block = render_skill(body, context.template_vars()).strip() if body else ""

    parts = [header.rstrip(), "", system_info.strip()]
    if rules_block:
        parts.extend(["", "---", "", rules_block])
    return "\n".join(parts)


def _self_profile_id_for_context(context: MeetingRoomContext) -> str | None:
    """Worker 视角时，从 worker_profile_ids 推断当前 Worker 的 profile id。

    Phase 当前默认把 worker_profile_ids[0] 作为自己；后续 host 通过 delegate
    工具进入时会有独立 instance_key，再由调用方覆盖。
    """
    if context.role == "worker" and context.worker_profile_ids:
        first = str(context.worker_profile_ids[0]).strip()
        return first or None
    return None


def make_context(
    *,
    role: Role,
    binding: dict[str, Any],
    scope_type: str,
    scope_id: str,
    ticket_title: str,
    archive_dir: str,
    self_profile_id: str = "",
) -> MeetingRoomContext:
    """从 binding（resolve_node_binding 输出）+ scope 信息组装上下文。"""
    host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
    host_profile = _resolve_profile(host_id)
    host_name = (
        host_profile.get_display_name() if host_profile else host_id
    )

    worker_ids = list(binding.get("worker_profile_ids") or [])

    return MeetingRoomContext(
        role=role,
        scope_type=str(scope_type or "demand"),
        scope_id=str(scope_id or ""),
        ticket_title=str(ticket_title or ""),
        node_id=str(binding.get("node_id") or "pending"),
        node_name=str(binding.get("node_name") or node_display_name(str(binding.get("node_id") or ""))),
        node_intent=str(binding.get("node_intent") or binding.get("intent") or ""),
        stage_id=int(binding.get("stage_id") or 0),
        stage_name=str(binding.get("stage_name") or stage_name_for_id(int(binding.get("stage_id") or 0))),
        host_profile_id=host_id,
        host_profile_name=str(host_name),
        host_llm_endpoint=str(binding.get("host_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY),
        worker_llm_endpoint=str(binding.get("worker_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY),
        worker_profile_ids=[str(w) for w in worker_ids if str(w).strip()],
        archive_dir=str(archive_dir or ""),
        prompt_supplement=str(binding.get("prompt_supplement") or ""),
        self_profile_id=str(self_profile_id or "").strip(),
    )


