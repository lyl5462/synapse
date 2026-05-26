"""研发会议室四段式动态上下文（唯一数据注入点，由 meeting-room SKILL 加载）。"""

from __future__ import annotations

import sys
from typing import Any, Literal

from synapse.rd_meeting.devservice import (
    gitnexus_service_base_url,
    gnx_cache_base_dir,
    gnx_cache_dir_for_repo,
    unified_service_base_url,
)
from synapse.rd_meeting.init_context import build_node_init_log_data, normalize_node_init_log_data
from synapse.rd_meeting.paths import archive_node_dir
from synapse.rd_sop.nodes import node_display_name, stage_name_for_id

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
    if product.get("prod"):
        lines.append(f"- PROD：`{product['prod']}`")
    if product.get("prod_feature"):
        lines.append(f"- PROD_FEATURE：{product['prod_feature']}")
    if product.get("version"):
        lines.append(f"- version：`{product['version']}`")
    repos = product.get("repos")
    if isinstance(repos, list) and repos:
        lines.append(f"- 关联仓库（{len(repos)}）：")
        for r in repos:
            if isinstance(r, dict):
                name = r.get("repo_name") or r.get("repo_url") or "?"
                local = str(r.get("local_path") or "").strip()
                st = str(r.get("materialize_status") or "").strip()
                suffix = f" → `{local}`" if local else ""
                if st and st != "ok":
                    suffix += f"（{st}）"
                lines.append(f"  - `{name}`{suffix}")
  
    return "\n".join(lines) if lines else "（无产品字段）"


def _detect_current_os_type() -> Literal["WINDOWS", "LINUX", "MACOS"]:
    """识别当前操作系统，供本地脚本/命令选择对应平台指令。"""
    if sys.platform == "win32":
        return "WINDOWS"
    if sys.platform == "darwin":
        return "MACOS"
    if sys.platform.startswith("linux"):
        return "LINUX"
    return "LINUX"


def _format_section_system(system: dict[str, Any]) -> str:
    """系统段：服务 URL、当前 OS 与路径；URL 优先读 system，缺失时按 devservice.ip 拼接。"""
    sys = system if isinstance(system, dict) else {}
    lines: list[str] = []

    current_os = str(sys.get("current_os") or _detect_current_os_type()).strip().upper()
    if current_os not in {"WINDOWS", "LINUX", "MACOS"}:
        current_os = _detect_current_os_type()
    lines.append(f"- CURRENT_OS：`{current_os}` 请使用该操作系统对应的命令, 不要尝试非本操作系统的命令")

    synapse_url = str(sys.get("synapse_url") or unified_service_base_url() or "").strip()
    if synapse_url:
        lines.append(f"- SYNAPSE_URL：`{synapse_url}`")

    gitnexus_url = str(sys.get("gitnexus_url") or gitnexus_service_base_url() or "").strip()
    if gitnexus_url:
        lines.append(f"- GITNEXUS_URL：`{gitnexus_url}`")

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
    stage_name = str(binding.get("stage_name") or stage_name_for_id(stage_id)).strip()
    if sid and nid and not system.get("archive_dir"):
        system["archive_dir"] = str(archive_node_dir(sid, stage_name, nid))
    repos = product.get("repos") if isinstance(product.get("repos"), list) else []
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_name = str(repo.get("repo_name") or "").strip()
        if not repo_name:
            continue
        gnx_dir = gnx_cache_dir_for_repo(repo_name)
        if gnx_dir:
            system["gnx_cache_dir"] = gnx_dir
        break
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
        "## 一、工单信息",
        "",
        _format_section_order(order),
        "",
        "## 二、产品信息",
        "",
        _format_section_product(product),
        "",
        "## 三、系统信息",
        "",
        _format_section_system(system),
    ]
    parts = (sections_overview + sections_data) if include_overview else sections_data
    return "\n".join(parts).strip()


def build_meeting_user_turn_prompt() -> str:
    """主控首轮 user 消息：仅触发执行，上下文已在 SKILL 动态段。"""
    return (
        "请严格参考系统提示词中的各项内容，按照会议室流程与规则开始本 SOP 节点工作，委派的所有任务不应该随机生成，必须围绕上下文(工单内容、用户反馈内容、协作智能体反馈内容)处理。需要注意，先 `submit_meeting_work_plan`，再按能力边界委派协作智能体。"
    )
