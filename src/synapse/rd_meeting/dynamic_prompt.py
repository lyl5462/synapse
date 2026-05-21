"""研发会议室四段式动态上下文（唯一数据注入点，由 meeting-room SKILL 加载）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.agents.profile import AgentProfile
from synapse.rd_meeting.init_context import build_node_init_log_data, normalize_node_init_log_data
from synapse.rd_meeting.paths import archive_root
from synapse.rd_meeting.room_skill import (
    DEFAULT_LLM_ENDPOINT_KEY,
    format_skill_entries,
    resolve_agent_profile,
)
from synapse.rd_sop.nodes import node_display_name

ScopeType = Literal["demand", "task"]


def _format_worker_block(
    profile: AgentProfile,
    *,
    llm_endpoint: str,
) -> str:
    name = profile.get_display_name() or profile.name or profile.id
    lines = [f"**{name}**（`{profile.id}`）"]
    lines.append(f"- 端点：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`")
    desc = (profile.description or "").strip()
    if desc:
        lines.append(f"- 简介：{desc}")
    skills = format_skill_entries(profile.skills or [])
    if skills:
        lines.append(f"- 技能：{', '.join(skills)}")
    custom = (profile.custom_prompt or "").strip()
    if custom:
        short = custom.replace("\n", " ").strip()
        if len(short) > 240:
            short = short[:240] + "…"
        lines.append(f"- 主张：{short}")
    return "\n".join(lines)


def _human_confirm_line(binding: dict[str, Any]) -> str:
    """四段式 (3) 仅保留开关；细则统一在 SKILL §1.2，避免与动态段重复。"""
    return "**开启**（细则见本 SKILL §1.2）" if binding.get("human_confirm") else "**关闭**（细则见本 SKILL §1.2）"


def _format_section_order(order: dict[str, Any]) -> str:
    if not order:
        return "（无工单数据）"
    lines: list[str] = []
    if order.get("id"):
        lines.append(f"- 单号：`{order['id']}`")
    if order.get("title"):
        lines.append(f"- 标题：{order['title']}")
    if order.get("prod"):
        lines.append(f"- 产品标识（prod）：`{order['prod']}`")
    if order.get("scope_type") and order.get("scope_id"):
        lines.append(f"- 范围：{order['scope_type']} / `{order['scope_id']}`")
    desc = str(order.get("description") or "").strip()
    if desc:
        lines.append(f"- 说明：{desc}")
    impact = str(order.get("impact") or "").strip()
    if impact:
        lines.append(f"- 影响范围：{impact}")
    return "\n".join(lines) if lines else "（无工单字段）"


def _format_section_product(product: dict[str, Any]) -> str:
    if not product:
        return "（无产品数据）"
    lines: list[str] = []
    code = str(product.get("locator_code") or "").strip()
    msg = str(product.get("locator_message") or "").strip()
    if code or msg:
        lines.append(f"- 定位：{code or '—'} — {msg or '—'}")
    if product.get("prod"):
        lines.append(f"- prod：`{product['prod']}`")
    if product.get("version"):
        lines.append(f"- version：`{product['version']}`")
    repos = product.get("repos")
    if isinstance(repos, list) and repos:
        lines.append(f"- 关联仓库（{len(repos)}）：")
        for r in repos:
            if isinstance(r, dict):
                lines.append(f"  - `{r.get('repo_name') or r.get('repo_url') or '?'}`")
    docs = product.get("docs")
    if isinstance(docs, list) and docs:
        lines.append(f"- 文档槽位：{len(docs)}")
    return "\n".join(lines) if lines else "（无产品字段）"


def _format_section_system(system: dict[str, Any]) -> str:
    if not system:
        return "（无系统参数）"
    lines: list[str] = []
    for key, label in (
        ("synapse_url", "统一服务（Synapse）"),
        ("gitnexus_url", "GitNexus 服务"),
        ("gnx_cache_base_dir", "GNX 缓存根目录"),
        ("gnx_cache_dir", "GNX 缓存目录（本仓库）"),
        ("work_order_dir", "工单工作目录"),
        ("archive_dir", "本节点归档目录"),
    ):
        val = str(system.get(key) or "").strip()
        if val:
            lines.append(f"- {label}：`{val}`")
    return "\n".join(lines) if lines else "（无系统字段）"


def build_dynamic_meeting_context(
    *,
    binding: dict[str, Any],
    init_data: dict[str, Any] | None = None,
    scope_type: ScopeType = "demand",
    scope_id: str = "",
    sop_node_display: str = "",
) -> str:
    """四段式动态上下文 Markdown（注入 SKILL `{DYNAMIC_MEETING_CONTEXT}`）。"""
    sid = (scope_id or "").strip()
    nid = str(binding.get("node_id") or "").strip()
    data = normalize_node_init_log_data(
        init_data
        if init_data is not None
        else build_node_init_log_data(scope_type, sid, node_id=nid)
    )
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    product = data.get("product") if isinstance(data.get("product"), dict) else {}
    system = dict(data.get("system")) if isinstance(data.get("system"), dict) else {}
    stage_id = int(binding.get("stage_id") or 0)
    if sid and nid and not system.get("archive_dir"):
        system["archive_dir"] = str(archive_root(sid) / str(stage_id) / nid)
    stage_name = str(binding.get("stage_name") or "").strip()
    node_name = str(binding.get("node_name") or node_display_name(nid))
    sop_node = (sop_node_display or node_name or nid or "—").strip()
    intent = str(binding.get("node_intent") or binding.get("intent") or "").strip() or "（未配置 node_intent）"

    host_id = str(binding.get("host_profile_id") or "default").strip()
    worker_endpoint = str(binding.get("worker_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY)
    worker_lines: list[str] = []
    for wid in binding.get("worker_profile_ids") or []:
        w = str(wid).strip()
        if not w or w == host_id:
            continue
        profile = resolve_agent_profile(w)
        if profile is None:
            worker_lines.append(f"**{w}**\n- 简介：未在 Profile 库中找到")
        else:
            worker_lines.append(_format_worker_block(profile, llm_endpoint=worker_endpoint))
    workers_body = "\n\n".join(worker_lines) if worker_lines else "（本节点未配置协作智能体）"

    supplement = str(binding.get("prompt_supplement") or "").strip()
    supplement_block = f"\n\n**运营补充**：{supplement}" if supplement else ""

    parts = [
        "## 一、本 SOP 环节工作信息（最重要）",
        "",
        f"(1) **会议节点**：阶段 `{stage_id}`"
        + (f" · {stage_name}" if stage_name else "")
        + f" · SOP 节点 `{sop_node}`（node_id=`{nid or '—'}`）",
        "",
        "(2) **会议目标**：",
        intent,
        "",
        f"(3) **人工确认（human_confirm）**：{_human_confirm_line(binding)}",
        "",
        "(4) **协作智能体**：",
        workers_body,
        supplement_block,
        "",
        "## 二、工单信息（继承节点初始化）",
        "",
        _format_section_order(order),
        "",
        "## 三、产品信息（继承节点初始化）",
        "",
        _format_section_product(product),
        "",
        "## 四、系统信息（继承节点初始化）",
        "",
        _format_section_system(system),
    ]
    return "\n".join(parts).strip()


def build_meeting_user_turn_prompt() -> str:
    """主控首轮 user 消息：仅触发执行，上下文已在 SKILL 动态段。"""
    return (
        "请依据系统提示中的「研发会议室通用规范」与「本场会议动态上下文（四段式）」"
        "开始本 SOP 节点：先 `submit_meeting_work_plan`，再按能力边界委派协作智能体。"
    )
