"""会议室运行时系统参数自动注入（无需在 meeting_room_config 人工配置）。"""

from __future__ import annotations

import os
from typing import Any

from synapse.rd_meeting.paths import archive_root, scope_dir
from synapse.rd_meeting.userwork_sync import load_scope_work_order_context
from synapse.rd_sop.nodes import stage_id_for_node_id


def build_meeting_runtime_context_section(
    *,
    scope_type: str,
    scope_id: str,
    ticket_title: str = "",
    node_id: str = "",
    stage_id: int | None = None,
) -> str:
    """生成注入 host/worker prompt 的运行时系统参数段。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    stg = int(stage_id if stage_id is not None else (stage_id_for_node_id(nid) if nid else 0))
    work_dir = str(scope_dir(sid)) if sid else ""
    archive_dir = ""
    if sid and nid:
        archive_dir = str(archive_root(sid) / str(stg) / nid)

    wo = load_scope_work_order_context(scope_type, sid) if sid else {}
    synapse_url = _resolve_synapse_url()
    gitnexus_url = _resolve_gitnexus_url()
    repo_name = _resolve_repo_name(wo)
    gnx_cache = _resolve_gnx_cache_dir(repo_name)

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
    if work_dir:
        lines.append(f"- WORK_ORDER_DIR: {work_dir}")
    if archive_dir:
        lines.append(f"- ARCHIVE_DIR: {archive_dir}")
    lines.append(f"- SYNAPSE_URL: {synapse_url or '（未配置）'}")
    lines.append(f"- GITNEXUS_URL: {gitnexus_url or '（未配置）'}")
    lines.append(f"- REPO_NAME: {repo_name or '（未配置）'}")
    lines.append(f"- GNX_CACHE_DIR: {gnx_cache or '（未配置）'}")
    if wo.get("repo_url") and wo.get("repo_url") != repo_name:
        lines.append(f"- REPO_URL: {wo['repo_url']}")
    return "\n".join(lines)


def _resolve_synapse_url() -> str:
    try:
        from synapse.config import settings

        host = str(getattr(settings, "api_host", "") or "127.0.0.1").strip()
        port = int(getattr(settings, "api_port", 0) or 16185)
        return f"http://{host}:{port}"
    except Exception:
        return ""


def _resolve_gitnexus_url() -> str:
    for key in ("GITNEXUS_URL", "SYNAPSE_GITNEXUS_URL", "GITNEXUS_BASE_URL"):
        val = os.environ.get(key, "").strip()
        if val:
            return val.rstrip("/")
    try:
        from synapse.config import settings

        val = str(getattr(settings, "gitnexus_url", "") or "").strip()
        if val:
            return val.rstrip("/")
    except Exception:
        pass
    return ""


def _resolve_repo_name(wo: dict[str, str]) -> str:
    repo_url = (wo.get("repo_url") or "").strip()
    if repo_url and "@@" in repo_url:
        return repo_url.split("@@", 1)[0].strip()
    if repo_url and "/" in repo_url:
        tail = repo_url.rstrip("/").split("/")[-1]
        if tail.endswith(".git"):
            tail = tail[:-4]
        return tail
    code = (wo.get("product_version_code") or "").strip()
    return code


def _resolve_gnx_cache_dir(repo_name: str) -> str:
    if not repo_name:
        return ""
    try:
        from synapse.config import settings

        base = settings.synapse_home / "tmp" / "gitnexus" / repo_name
        return str(base)
    except Exception:
        return ""


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
