"""会议室运行时系统参数自动注入（无需在 meeting_room_config 人工配置）。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.devservice import (
    gnx_cache_base_dir,
    gnx_cache_dir_for_repo,
    gitnexus_service_base_url,
    unified_service_base_url,
)
from synapse.rd_meeting.paths import archive_root
from synapse.rd_meeting.product_context import load_product_session_cache
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
    gitnexus_url = gitnexus_service_base_url()
    gnx_base = gnx_cache_base_dir()
    resolved_repo = (repo_name or "").strip()
    if not resolved_repo and sid:
        cached = load_product_session_cache(sid)
        if isinstance(cached, dict):
            repos = cached.get("repos")
            if isinstance(repos, list) and repos:
                first = repos[0]
                if isinstance(first, dict):
                    resolved_repo = str(first.get("repo_name") or "").strip()
    gnx_cache = gnx_cache_dir_for_repo(resolved_repo) if resolved_repo else ""

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
    if wo.get("product_version_code"):
        lines.append(f"- PRODUCT_VERSION: {wo['product_version_code']}")
    if archive_dir:
        lines.append(f"- ARCHIVE_DIR: {archive_dir}")
    lines.append(f"- UNIFIED_SERVICE_URL: {synapse_url or '（未配置 devservice.ip）'}")
    lines.append(f"- GITNEXUS_URL: {gitnexus_url or '（未配置 devservice.ip）'}")
    if resolved_repo:
        lines.append(f"- REPO_NAME: {resolved_repo}")
    if gnx_cache:
        lines.append(f"- GNX_CACHE_DIR: {gnx_cache}")
    elif gnx_base:
        lines.append(f"- GNX_CACHE_BASE_DIR: {gnx_base}")
    if wo.get("repo_url") and wo.get("repo_url") != resolved_repo:
        lines.append(f"- REPO_URL: {wo['repo_url']}")
    return "\n".join(lines)


def _resolve_synapse_url() -> str:
    """兼容：统一服务地址（:10001）。"""
    return unified_service_base_url()


def _resolve_gitnexus_url() -> str:
    return gitnexus_service_base_url()


def _resolve_repo_name(wo: dict[str, str]) -> str:
    from synapse.rd_meeting.product_context import _repo_name_from_url

    repo_url = (wo.get("repo_url") or "").strip()
    if repo_url:
        return _repo_name_from_url(repo_url)
    code = (wo.get("product_version_code") or "").strip()
    return code


def _resolve_gnx_cache_dir(repo_name: str) -> str:
    return gnx_cache_dir_for_repo(repo_name)


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
