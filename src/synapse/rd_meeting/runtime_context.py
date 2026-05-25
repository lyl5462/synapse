"""会议室运行时系统参数自动注入（无需在 meeting_room_config 人工配置）。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.devservice import unified_service_base_url
from synapse.rd_meeting.paths import archive_root
from synapse.rd_meeting.product_assets import load_product_assets_from_pipeline
from synapse.rd_meeting.userwork_sync import load_scope_work_order_context
from synapse.rd_sop.nodes import stage_id_for_node_id


def build_meeting_runtime_context_section(
    *,
    scope_type: str,
    scope_id: str,
    ticket_title: str = "",
    node_id: str = "",
    stage_id: int | None = None,
    repo_name: str = "",
) -> str:
    """生成注入 host/worker prompt 的运行时系统参数段。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    stg = int(stage_id if stage_id is not None else (stage_id_for_node_id(nid) if nid else 0))
    archive_dir = ""
    if sid and nid:
        archive_dir = str(archive_root(sid) / str(stg) / nid)

    wo = load_scope_work_order_context(scope_type, sid) if sid else {}
    synapse_url = unified_service_base_url()
    assets = load_product_assets_from_pipeline(sid) if sid else None

    lines = [
        "## 运行时系统参数（自动注入，勿臆造）",
        f"- SCOPE: {scope_type}/{sid}" if sid else "- SCOPE: （未解析）",
    ]
    title = ticket_title or wo.get("demand_title") or wo.get("task_title") or ""
    if title:
        lines.append(f"- TICKET_TITLE: {title}")
    if wo.get("demand_desc"):
        lines.append(f"- DEMAND_DESC: {wo['demand_desc'][:2000]}")
    if wo.get("demand_impact"):
        lines.append(f"- DEMAND_IMPACT: {wo['demand_impact'][:800]}")
    if wo.get("prod"):
        lines.append(f"- PROD: {wo['prod']}")
    elif wo.get("product_version_code"):
        lines.append(f"- PRODUCT_VERSION: {wo['product_version_code']}")
    if archive_dir:
        lines.append(f"- ARCHIVE_DIR: {archive_dir}")
    lines.append(f"- UNIFIED_SERVICE_URL: {synapse_url or '（未配置 devservice.ip）'}")
    if isinstance(assets, dict):
        wo_dir = str(assets.get("work_order_dir") or "").strip()
        code_root = str(assets.get("code_root") or "").strip()
        doc_root = str(assets.get("doc_root") or "").strip()
        if wo_dir:
            lines.append(f"- WORK_ORDER_DIR: {wo_dir}")
        if code_root:
            lines.append(f"- PRODUCT_CODE_ROOT: {code_root}")
        if doc_root:
            lines.append(f"- PRODUCT_DOC_ROOT: {doc_root}")
        resolved_repo = (repo_name or "").strip()
        if not resolved_repo:
            repos = assets.get("repos")
            if isinstance(repos, list) and repos:
                first = repos[0]
                if isinstance(first, dict):
                    resolved_repo = str(first.get("repo_name") or "").strip()
        if resolved_repo and code_root:
            lines.append(f"- REPO_NAME: {resolved_repo}")
    return "\n".join(lines)


def _resolve_synapse_url() -> str:
    """兼容：统一服务地址（:10001）。"""
    return unified_service_base_url()


def runtime_context_for_binding(
    binding: dict[str, Any],
    *,
    scope_type: str,
    scope_id: str,
    ticket_title: str = "",
) -> str:
    node_id = str(binding.get("node_id") or "")
    stage_id = int(binding.get("stage_id") or 0)
    return build_meeting_runtime_context_section(
        scope_type=scope_type,
        scope_id=scope_id,
        ticket_title=ticket_title,
        node_id=node_id,
        stage_id=stage_id or None,
    )
