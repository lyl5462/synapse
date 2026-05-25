"""研发会议室四段式动态上下文（唯一数据注入点，由 meeting-room SKILL 加载）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.init_context import build_node_init_log_data, normalize_node_init_log_data
from synapse.rd_meeting.paths import archive_root
from synapse.rd_sop.nodes import node_display_name

ScopeType = Literal["demand", "task"]


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
        lines.append(f"- DEMAND_DESC：{desc}")
    impact = str(order.get("impact") or "").strip()
    if impact:
        lines.append(f"- DEMAND_IMPACT：{impact}")
    return "\n".join(lines) if lines else "（无工单字段）"


def _format_section_product(product: dict[str, Any]) -> str:
    if not product:
        return "（无产品数据）"
    lines: list[str] = []
    code = str(product.get("locator_code") or "").strip()
    msg = str(product.get("locator_message") or "").strip()
    if product.get("prod"):
        lines.append(f"- PROD`{product['prod']}`")
    if product.get("prod_feature"):
        lines.append(f"- PROD_FEATURE：{product['prod_feature']}")
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


def _format_section_system(
    system: dict[str, Any],
    *,
    stage_name: str = "",
    node_name: str = "",
    node_outputs: list[str] | None = None,
) -> str:
    if not system:
        return "（无系统参数）"
    lines: list[str] = []
    for key, label in (
        ("synapse_url", "SYNAPSE_URL"),
        ("gitnexus_url", "GITNEXUS_URL"),
        ("gnx_cache_base_dir", "TMP_DIR"),
        ("work_order_dir", "工单工作目录"),
    ):
        val = str(system.get(key) or "").strip()
        if val:
            lines.append(f"- {label}：`{val}`")
    archive_val = str(system.get("archive_dir") or "").strip()
    if archive_val:
        friendly = " · ".join(s for s in (stage_name, node_name) if s)
        if friendly:
            lines.append(f"- 本节点归档目录（{friendly}）：`{archive_val}`")
        else:
            lines.append(f"- 本节点归档目录：`{archive_val}`")
    outs = [
        str(n).strip()
        for n in (node_outputs or [])
        if str(n).strip() and not str(n).strip().startswith("（")
    ]
    if outs:
        lines.append("- **会议产出**（与运行时头「会议产出」一致；归档文件名必须逐字匹配以下清单）：")
        for n in outs:
            lines.append(f"  - `{n}`")
    return "\n".join(lines) if lines else "（无系统字段）"


def build_dynamic_meeting_context(
    *,
    binding: dict[str, Any],
    init_data: dict[str, Any] | None = None,
    scope_type: ScopeType = "demand",
    scope_id: str = "",
    sop_node_display: str = "",
    include_overview: bool = True,
) -> str:
    """会议室动态上下文 Markdown。

    - ``include_overview=True``（默认）：四段式，含「一、本 SOP 环节工作信息 / 二、工单 / 三、产品 / 四、系统」。
    - ``include_overview=False``：仅「工单 / 产品 / 系统」三段。

      新版会议室 system prompt 中，「会议节点 / 会议目标 / 人工确认 / 协作智能体」
      已由 ``build_meeting_runtime_header`` 输出，第一段会与之重复，
      因此 ``room_skill.build_room_skill_prompt`` 会传 ``False``。
    """
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
    worker_ids = [
        str(w).strip()
        for w in (binding.get("worker_profile_ids") or [])
        if str(w).strip() and str(w).strip() != host_id
    ]
    if worker_ids:
        workers_summary = (
            f"本节点配置了 {len(worker_ids)} 位协作智能体："
            + "、".join(f"`{w}`" for w in worker_ids)
            + "。**能力边界与端点详见 system prompt 上方「参会能力卡片」段**，本块不再重复列出。"
        )
    else:
        workers_summary = "（本节点未配置协作智能体；小鲸需在自身能力范围内完成本节点。）"

    supplement = str(binding.get("prompt_supplement") or "").strip()
    supplement_block = f"\n\n**运营补充**：{supplement}" if supplement else ""

    sections_overview = [
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
        workers_summary,
        supplement_block,
        "",
    ]
    sections_data = [
        "## 二、工单信息",
        "",
        _format_section_order(order),
        "",
        "## 三、产品信息",
        "",
        _format_section_product(product),
        "",
        "## 四、系统信息",
        "",
        _format_section_system(
            system,
            stage_name=stage_name,
            node_name=node_name,
            node_outputs=list(binding.get("node_outputs") or []),
        ),
    ]
    parts = (sections_overview + sections_data) if include_overview else sections_data
    return "\n".join(parts).strip()


def build_meeting_user_turn_prompt() -> str:
    """主控首轮 user 消息：仅触发执行，上下文已在 SKILL 动态段。"""
    return (
        "请严格参考系统提示词中的各项内容，按照会议室流程与规则开始本 SOP 节点工作，委派的所有任务不应该随机生成，必须围绕上下文(工单内容、用户反馈内容、协作智能体反馈内容)处理。需要注意，先 `submit_meeting_work_plan`，再按能力边界委派协作智能体。"
    )
