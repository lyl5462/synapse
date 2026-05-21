"""会议室专属 SKILL 加载与 prompt 渲染。

设计目标（对齐《多智能体研发会议室实现方案》§9）：

- 把会议室通用规范以一份 SKILL.md 收敛在 `skills/whalecloud-dev-tool-meeting-room/`。
- 小鲸（host）与所有协作智能体（worker）进入会议室后，都会在 prompt 中加载这份
  SKILL，并根据自己的角色裁剪可见段落。
- 同时把"参会智能体能力卡片"渲染进去，让小鲸按能力边界分派任务，让协作智能体
  之间可以互相请求协助。

本模块只负责**装配 prompt 片段**，不直接调用 LLM；由 `orchestrator.run_current_node`
在执行节点时把渲染结果拼接到节点提示词中。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from synapse.agents.profile import AgentProfile, get_profile_store
from synapse.rd_sop.nodes import node_display_name, stage_name_for_id

logger = logging.getLogger(__name__)

Role = Literal["host", "worker"]

DEFAULT_MEETING_SKILL_ID = "whalecloud-dev-tool-meeting-room"
DEFAULT_ASK_USER_SKILL_ID = "whalecloud-dev-tool-ask-user"
DEFAULT_LLM_ENDPOINT_KEY = "default"


# ─── SKILL.md 定位 ──────────────────────────────────────────────────────


def _candidate_skill_dirs() -> list[Path]:
    """按优先级返回会议室 SKILL 可能的根目录。

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


def find_meeting_skill_file(skill_id: str = DEFAULT_MEETING_SKILL_ID) -> Path | None:
    """在标准技能目录中查找会议室 SKILL.md 文件。"""
    sid = (skill_id or DEFAULT_MEETING_SKILL_ID).strip() or DEFAULT_MEETING_SKILL_ID
    for root in _candidate_skill_dirs():
        if not root.is_dir():
            continue
        path = root / sid / "SKILL.md"
        if path.is_file():
            return path
    return None


def load_ask_user_skill_body(skill_id: str = DEFAULT_ASK_USER_SKILL_ID) -> str:
    """读取人机问卷技能正文（host 专用片段）。"""
    path = find_meeting_skill_file(skill_id)
    if path is None:
        return ""
    try:
        return _strip_frontmatter(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("read ask-user skill %s failed: %s", path, exc)
        return ""


def load_meeting_skill_body(skill_id: str = DEFAULT_MEETING_SKILL_ID) -> str:
    """读取会议室 SKILL.md 正文（去掉 front-matter）。

    若 SKILL 文件不存在，返回一个最小化的兜底说明，保证会议室仍可启动。
    """
    path = find_meeting_skill_file(skill_id)
    if path is None:
        logger.warning(
            "meeting room skill %s not found in any skills directory; using fallback",
            skill_id,
        )
        return _FALLBACK_SKILL_BODY
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("read meeting skill %s failed: %s", path, exc)
        return _FALLBACK_SKILL_BODY
    return _strip_frontmatter(raw)


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


_FALLBACK_SKILL_BODY = """# 研发会议室通用规范（兜底版）

未找到 `whalecloud-dev-tool-meeting-room` 技能文件，使用兜底说明。
进入会议室的参会者必须遵守：

1. 会议室围绕当前 SOP 节点工作，目标是产出可验收的归档交付物。
2. 小鲸（Host）负责安排、检查、校验；协作智能体（Worker）负责在能力边界内执行。
3. 任何结论需可被源码 / 文档 / 工单证据复核；不可虚构。
4. 节点产物以 Markdown 形式归档，含一级标题与「结论 / 完成 / 交付」字样。
"""


# ─── 数据结构 ───────────────────────────────────────────────────────────


@dataclass
class MeetingRoomContext:
    """会议室运行时上下文（注入 SKILL 用）。"""

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
    meeting_skill_id: str
    archive_dir: str
    prompt_supplement: str = ""

    def template_vars(self) -> dict[str, str]:
        """仅流程/路径类占位符；议程与工单数据只在 ``DYNAMIC_MEETING_CONTEXT``。"""
        return {
            "ROLE": self.role,
            "HOST_PROFILE_ID": self.host_profile_id,
            "HOST_PROFILE_NAME": self.host_profile_name,
            "HOST_LLM_ENDPOINT": self.host_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY,
            "WORKER_LLM_ENDPOINT": self.worker_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY,
            "ARCHIVE_DIR": self.archive_dir,
            "STAGE_ID": str(self.stage_id),
            "NODE_ID": self.node_id,
            "DYNAMIC_MEETING_CONTEXT": "{DYNAMIC_MEETING_CONTEXT}",
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
    path = find_meeting_skill_file(sid)
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


def build_capability_cards(
    *,
    host_profile_id: str,
    worker_profile_ids: list[str],
    host_llm_endpoint: str,
    worker_llm_endpoint: str,
    exclude_self_id: str | None = None,
) -> str:
    """渲染参会智能体能力卡片清单。

    `exclude_self_id` 用于 Worker 视角时去除"自己的卡片"——但小鲸的卡片对
    所有 Worker 仍然可见，以明确主持人身份。
    """
    cards: list[str] = []

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
            cards.append(f"## {wid}\n- 角色：worker · 端点：`{worker_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`\n- 简介：未在 Profile 库中找到，使用兜底身份。")
            continue
        cards.append(
            _format_capability_card(
                wp,
                role="worker",
                llm_endpoint=worker_llm_endpoint,
            )
        )

    if not cards:
        return "（暂无可用参会智能体；请先在『系统智能体管理』中配置。）"

    return "\n\n".join(cards)


# ─── 角色裁剪 + 渲染 ────────────────────────────────────────────────────


_HOST_HIDE_SECTION = re.compile(
    r"^## 4\. 协作智能体（Worker）的协作规范.*?(?=^## 5\.)",
    re.MULTILINE | re.DOTALL,
)
_WORKER_HIDE_SECTION = re.compile(
    r"^## 3\. 小鲸（Host）的工作循环.*?(?=^## 4\.)",
    re.MULTILINE | re.DOTALL,
)


def trim_skill_for_role(skill_body: str, role: Role) -> str:
    """按角色裁剪 SKILL：host 隐藏 Worker 视角，worker 隐藏 Host 视角。"""
    if role == "host":
        return _HOST_HIDE_SECTION.sub("", skill_body)
    if role == "worker":
        return _WORKER_HIDE_SECTION.sub("", skill_body)
    return skill_body


def render_skill(skill_body: str, variables: dict[str, str]) -> str:
    """填充 SKILL 占位符；``DYNAMIC_MEETING_CONTEXT`` 最后注入，避免污染四段式正文。"""
    dynamic = variables.get("DYNAMIC_MEETING_CONTEXT")
    procedural = {k: v for k, v in variables.items() if k != "DYNAMIC_MEETING_CONTEXT"}
    rendered = skill_body
    for key, value in procedural.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    if dynamic is not None:
        rendered = rendered.replace("{DYNAMIC_MEETING_CONTEXT}", str(dynamic))
    return rendered


def build_room_skill_prompt(
    context: MeetingRoomContext,
    *,
    skill_body: str | None = None,
    init_context: dict[str, Any] | None = None,
    binding: dict[str, Any] | None = None,
    sop_node_display: str = "",
) -> str:
    """生成会议室唯一动态注入：SKILL 规范 + 四段式 ``{DYNAMIC_MEETING_CONTEXT}``。"""
    from synapse.rd_meeting.dynamic_prompt import build_dynamic_meeting_context

    body = skill_body if skill_body is not None else load_meeting_skill_body(context.meeting_skill_id)
    body = trim_skill_for_role(body, context.role)

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
        "meeting_skill_id": context.meeting_skill_id,
        "prompt_supplement": context.prompt_supplement,
        "human_confirm": False,
    }

    dynamic = build_dynamic_meeting_context(
        binding=bind,
        init_data=init_context,
        scope_type=context.scope_type,  # type: ignore[arg-type]
        scope_id=context.scope_id,
        sop_node_display=sop_node_display or context.node_name,
    )

    variables = context.template_vars()
    variables["DYNAMIC_MEETING_CONTEXT"] = dynamic
    return render_skill(body, variables)


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
        meeting_skill_id=str(binding.get("meeting_skill_id") or DEFAULT_MEETING_SKILL_ID),
        archive_dir=str(archive_dir or ""),
        prompt_supplement=str(binding.get("prompt_supplement") or ""),
    )


def meeting_skill_preview(skill_id: str = DEFAULT_MEETING_SKILL_ID, limit: int = 280) -> dict[str, Any]:
    """供前端配置抽屉展示的会议室 SKILL 元信息（不渲染变量）。"""
    path = find_meeting_skill_file(skill_id)
    body = load_meeting_skill_body(skill_id)
    summary = ""
    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("---"):
            continue
        summary = text
        break
    return {
        "skill_id": skill_id,
        "exists": path is not None,
        "path": str(path) if path else None,
        "title": "研发会议室通用规范",
        "summary": summary[:limit],
        "length": len(body),
    }
