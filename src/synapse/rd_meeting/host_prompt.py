"""第三步：组装研发会议室主控（小鲸）提示词，并生成协作会议流展示文案。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.init_context import build_node_init_log_data, normalize_node_init_log_data
from synapse.rd_meeting.participants import resolve_profile_display_name
from synapse.rd_meeting.paths import scope_dir
from synapse.rd_meeting.room_skill import (
    build_room_skill_prompt,
    load_meeting_skill_body,
    make_context,
    meeting_skill_preview,
)
from synapse.rd_sop.nodes import node_display_name, stage_id_for_node_id

ScopeType = Literal["demand", "task"]


def _format_node_init_sections_markdown(data: dict[str, Any]) -> str:
    """将 node_init 的 order/product/system 转为可读 Markdown。"""
    norm = normalize_node_init_log_data(data)
    lines: list[str] = []

    order = norm.get("order") if isinstance(norm.get("order"), dict) else {}
    if order:
        lines.append("### 工单信息")
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
            lines.append(f"- 说明：{desc[:1200]}{'…' if len(desc) > 1200 else ''}")
        impact = str(order.get("impact") or "").strip()
        if impact:
            lines.append(f"- 影响范围：{impact[:600]}{'…' if len(impact) > 600 else ''}")
        lines.append("")

    product = norm.get("product") if isinstance(norm.get("product"), dict) else {}
    if product:
        lines.append("### 产品定位（统一服务）")
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
            lines.append(f"- 仓库数：{len(repos)}")
            for r in repos[:5]:
                if isinstance(r, dict):
                    lines.append(f"  - `{r.get('repo_name') or r.get('repo_url') or '?'}`")
        docs = product.get("docs")
        if isinstance(docs, list) and docs:
            lines.append(f"- 文档槽位：{len(docs)}")
        lines.append("")

    system = norm.get("system") if isinstance(norm.get("system"), dict) else {}
    if system:
        lines.append("### 系统接入")
        for key in (
            "synapse_url",
            "gitnexus_url",
            "gnx_cache_base_dir",
            "gnx_cache_dir",
            "work_order_dir",
        ):
            val = str(system.get(key) or "").strip()
            if val:
                lines.append(f"- {key}：`{val}`")
        lines.append("")

    return "\n".join(lines).strip() or "（无工单/产品上下文）"


def _format_binding_node_markdown(binding: dict[str, Any]) -> str:
    node_id = str(binding.get("node_id") or "")
    name = str(binding.get("node_name") or node_display_name(node_id))
    lines = [
        "### 会议节点",
        f"- 节点：`{node_id}` · {name}",
        f"- 阶段：{binding.get('stage_name') or '—'}（stage_id={binding.get('stage_id')}）",
        f"- 类型：{binding.get('type') or 'ai'}",
        f"- 人工确认门控：{'开启' if binding.get('human_confirm') else '关闭'}",
    ]
    intent = str(binding.get("node_intent") or binding.get("intent") or "").strip()
    if intent:
        lines.append(f"- 会议目标：{intent}")
    host_id = str(binding.get("host_profile_id") or "default")
    lines.append(
        f"- 主控：{resolve_profile_display_name(host_id)} (`{host_id}`) · "
        f"端点 `{binding.get('host_llm_endpoint_key') or 'default'}`"
    )
    workers = [str(w).strip() for w in (binding.get("worker_profile_ids") or []) if str(w).strip()]
    if workers:
        lines.append("- 协作智能体：")
        for wid in workers:
            if wid == host_id:
                continue
            lines.append(
                f"  - {resolve_profile_display_name(wid)} (`{wid}`) · "
                f"端点 `{binding.get('worker_llm_endpoint_key') or 'default'}`"
            )
    skill_id = str(binding.get("meeting_skill_id") or "").strip()
    if skill_id:
        preview = meeting_skill_preview(skill_id)
        exists = "已加载" if preview.get("exists") else "缺失（使用兜底）"
        lines.append(f"- 会议室 SKILL：`{skill_id}`（{exists}，约 {preview.get('length', 0)} 字）")
    supplement = str(binding.get("prompt_supplement") or "").strip()
    if supplement:
        lines.append(f"- 运营补充：{supplement}")
    return "\n".join(lines)


def assemble_host_prompt_bundle(
    *,
    scope_type: ScopeType,
    scope_id: str,
    node_id: str,
    binding: dict[str, Any] | None = None,
    ticket_title: str = "",
) -> dict[str, Any]:
    """组装主控智能体完整提示词（系统注入 + 本节点 user prompt）。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    bind = dict(binding) if binding else resolve_node_binding(
        nid,
        scope_type=scope_type,
        scope_id=sid,
        ticket_title=ticket_title,
    )
    bind["node_id"] = nid
    stg = int(bind.get("stage_id") or stage_id_for_node_id(nid))

    skill_body = load_meeting_skill_body(str(bind.get("meeting_skill_id") or ""))
    ctx = make_context(
        role="host",
        binding=bind,
        scope_type=scope_type,
        scope_id=sid,
        ticket_title=ticket_title,
        archive_dir=str(scope_dir(sid) / str(stg) / nid) if sid and nid else "",
    )
    system_prompt_suffix = build_room_skill_prompt(ctx, skill_body=skill_body)
    from synapse.rd_meeting.orchestrator import build_node_prompt

    user_prompt = build_node_prompt(
        scope_type=scope_type,
        scope_id=sid,
        node_id=nid,
        binding=bind,
        ticket_title=ticket_title,
    )
    init_data = build_node_init_log_data(scope_type, sid, node_id=nid)

    host_id = str(bind.get("host_profile_id") or "default")
    worker_ids = [
        str(w).strip()
        for w in (bind.get("worker_profile_ids") or [])
        if str(w).strip() and str(w).strip() != host_id
    ]

    return {
        "scope_type": scope_type,
        "scope_id": sid,
        "node_id": nid,
        "node_name": str(bind.get("node_name") or node_display_name(nid)),
        "host_profile_id": host_id,
        "worker_profile_ids": worker_ids,
        "meeting_skill_id": str(bind.get("meeting_skill_id") or ""),
        "system_prompt_suffix": system_prompt_suffix,
        "user_prompt": user_prompt,
        "init_context": init_data,
        "binding_summary": _format_binding_node_markdown(bind),
    }


def format_host_prompt_markdown(bundle: dict[str, Any]) -> str:
    """协作会议流：完整展示主控提示词（节点 / 工单 / SKILL 注入）。"""
    init_md = _format_node_init_sections_markdown(
        bundle.get("init_context") if isinstance(bundle.get("init_context"), dict) else {}
    )
    binding_md = str(bundle.get("binding_summary") or "").strip()
    system_txt = str(bundle.get("system_prompt_suffix") or "").strip()
    user_txt = str(bundle.get("user_prompt") or "").strip()

    parts = [
        "【步骤 3/3】主控智能体（小鲸）提示词已组装",
        "",
        "以下内容为即将注入主控会话的**系统提示后缀（SKILL + 能力卡片 + 运行时）**"
        "与**本节点 user 议程**，供审阅；实际推理在「调度节点执行」后启动。",
        "",
        "## 一、会议节点与绑定",
        binding_md or "（无）",
        "",
        "## 二、工单 / 产品 / 系统（与节点初始化一致）",
        init_md,
        "",
        "## 三、本节点 User Prompt（议程要点）",
        "```markdown",
        user_txt or "（空）",
        "```",
        "",
        "## 四、系统提示注入（SKILL · 能力卡片 · 运行时 · ask-user）",
        "```markdown",
        system_txt or "（空）",
        "```",
        "",
        "---",
        f"统计：系统注入 {len(system_txt)} 字 · user 议程 {len(user_txt)} 字 · "
        f"skill `{bundle.get('meeting_skill_id') or '—'}`",
    ]
    return "\n".join(parts)


def save_host_prompt_snapshot(scope_id: str, bundle: dict[str, Any]) -> str:
    """落盘完整快照，便于排查（返回文件路径字符串）。"""
    sid = (scope_id or "").strip()
    if not sid:
        return ""
    path = scope_dir(sid) / "host_prompt_snapshot.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_host_prompt_markdown(bundle), encoding="utf-8")
    return str(path)
