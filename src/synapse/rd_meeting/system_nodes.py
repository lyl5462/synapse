"""SOP 系统节点：纯代码执行（无 LLM / 无人工确认）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from synapse.rd_meeting.paths import archive_node_dir, meeting_pipeline_path
from synapse.rd_meeting.room_runtime import read_json_file, write_json_file
from synapse.rd_sop.manifest import node_output_artifacts
from synapse.rd_sop.nodes import node_display_name, stage_name_for_id

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]
SYSTEM_PROFILE_ID = "system"

SystemNodeHandler = Callable[..., dict[str, Any]]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_system_participants() -> list[dict[str, str]]:
    return [
        {
            "profile_id": SYSTEM_PROFILE_ID,
            "role": "system",
            "display_name": "系统",
        }
    ]


def is_system_binding(binding: dict[str, Any]) -> bool:
    return str(binding.get("type") or "").strip() == "system"


def _resolve_prod(scope_id: str, dev: dict[str, Any], pipe: Any) -> str:
    mr = dev.get("meeting_room") if isinstance(dev.get("meeting_room"), dict) else {}
    prod = str(mr.get("prod") or "").strip()
    if prod:
        return prod
    if pipe is not None:
        pctx = pipe._data.get("context") if isinstance(pipe._data.get("context"), dict) else {}
        prod = str(pctx.get("selected_prod") or "").strip()
        if prod:
            return prod
    return ""


def _load_catalog_rows(scope_id: str, pipe: Any) -> list[dict[str, Any]]:
    from synapse.rd_meeting.product_context import load_prod_catalog_from_pipeline

    rows = load_prod_catalog_from_pipeline(scope_id)
    if rows:
        return rows
    if pipe is not None:
        pctx = pipe._data.get("context") if isinstance(pipe._data.get("context"), dict) else {}
        catalog = pctx.get("prod_catalog")
        if isinstance(catalog, list):
            return [r for r in catalog if isinstance(r, dict)]
    raw = read_json_file(meeting_pipeline_path(scope_id))
    if isinstance(raw, dict):
        ctx = raw.get("context") if isinstance(raw.get("context"), dict) else {}
        catalog = ctx.get("prod_catalog")
        if isinstance(catalog, list):
            return [r for r in catalog if isinstance(r, dict)]
    return []


def _write_system_archive(
    scope_id: str,
    node_id: str,
    stage_name: str,
    body: str,
) -> list[dict[str, Any]]:
    dest = archive_node_dir(scope_id, stage_name, node_id)
    dest.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for name in node_output_artifacts(node_id):
        if not name or name.startswith("（") or not name.lower().endswith(".md"):
            continue
        path = dest / name
        path.write_text(body, encoding="utf-8")
        artifacts.append({"name": name, "path": str(path)})
    return artifacts


def _save_pipeline_context_assets(scope_id: str, key: str, assets: dict[str, Any]) -> None:
    sid = (scope_id or "").strip()
    if not sid:
        return
    path = meeting_pipeline_path(sid)
    raw = read_json_file(path)
    if not isinstance(raw, dict):
        return
    ctx = raw.get("context") if isinstance(raw.get("context"), dict) else {}
    ctx[key] = assets
    raw["context"] = ctx
    raw["updated_at"] = _now_iso()
    write_json_file(path, raw)


def _save_sandbox_assets_to_pipeline(scope_id: str, assets: dict[str, Any]) -> None:
    _save_pipeline_context_assets(scope_id, "sandbox_assets", assets)


def handle_sandbox_build(
    *,
    scope_type: ScopeType,
    scope_id: str,
    node_id: str,
    dev: dict[str, Any],
    pipe: Any = None,
) -> dict[str, Any]:
    """沙箱构建：git 落盘至 ``work/<scope>/sandbox/``。"""
    _ = scope_type
    sid = scope_id.strip()
    prod = _resolve_prod(sid, dev, pipe)
    if not prod:
        return {
            "status": "failed",
            "error": "未配置产品 prod，无法拉取沙箱代码",
            "sandbox_root": "",
            "repos": [],
        }

    from synapse.rd_meeting.product_context import match_prod_row_by_prod
    from synapse.rd_meeting.sandbox_assets import (
        bootstrap_sandbox_assets,
        format_sandbox_build_report,
    )

    catalog_rows = _load_catalog_rows(sid, pipe)
    wire_hit = match_prod_row_by_prod(catalog_rows, prod) if catalog_rows else None
    assets = bootstrap_sandbox_assets(sid, prod, wire_row=wire_hit, catalog_rows=catalog_rows)
    _save_sandbox_assets_to_pipeline(sid, assets)

    node_name = node_display_name(node_id)
    report_body = format_sandbox_build_report(assets, node_name=node_name)
    stage_name = stage_name_for_id(int(dev.get("stage_id") or 0))
    artifacts = _write_system_archive(sid, node_id, stage_name, report_body)

    ok = assets.get("status") in ("ok", "partial") and any(
        r.get("status") == "ok" for r in (assets.get("repos") or []) if isinstance(r, dict)
    )
    if not ok and assets.get("status") == "failed":
        return {
            "status": "failed",
            "error": "; ".join(assets.get("errors") or []) or "沙箱代码拉取失败",
            "sandbox_root": assets.get("sandbox_root"),
            "repos": assets.get("repos") or [],
            "artifacts": artifacts,
            "report_body": report_body,
        }

    return {
        "status": "ok" if assets.get("status") == "ok" else "partial",
        "sandbox_root": assets.get("sandbox_root"),
        "repos": assets.get("repos") or [],
        "artifacts": artifacts,
        "report_body": report_body,
        "prod": prod,
    }


def handle_auto_split(
    *,
    scope_type: ScopeType,
    scope_id: str,
    node_id: str,
    dev: dict[str, Any],
    pipe: Any = None,
) -> dict[str, Any]:
    """自动拆单：同步 userwork 与门户研发子单清单。"""
    _ = pipe
    sid = scope_id.strip()
    from synapse.rd_meeting.auto_split_assets import bootstrap_auto_split, format_auto_split_report

    assets = bootstrap_auto_split(scope_type, sid)
    _save_pipeline_context_assets(sid, "auto_split_assets", assets)

    node_name = node_display_name(node_id)
    report_body = format_auto_split_report(assets, node_name=node_name)
    stage_name = stage_name_for_id(int(dev.get("stage_id") or 0))
    artifacts = _write_system_archive(sid, node_id, stage_name, report_body)

    if assets.get("status") == "failed":
        return {
            "status": "failed",
            "error": "; ".join(assets.get("errors") or []) or "自动拆单失败",
            "demand_no": assets.get("demand_no"),
            "local_tasks": assets.get("local_tasks") or [],
            "portal_task_nos": assets.get("portal_task_nos") or [],
            "artifacts": artifacts,
            "report_body": report_body,
        }

    return {
        "status": assets.get("status") or "ok",
        "demand_no": assets.get("demand_no"),
        "local_tasks": assets.get("local_tasks") or [],
        "portal_task_nos": assets.get("portal_task_nos") or [],
        "artifacts": artifacts,
        "report_body": report_body,
    }


def handle_env_pregen(
    *,
    scope_type: ScopeType,
    scope_id: str,
    node_id: str,
    dev: dict[str, Any],
    pipe: Any = None,
) -> dict[str, Any]:
    """环境预生成：文档 + 控熵落盘至 ``work/<scope>/env/``。"""
    _ = scope_type
    sid = scope_id.strip()
    prod = _resolve_prod(sid, dev, pipe)
    if not prod:
        return {
            "status": "failed",
            "error": "未配置产品 prod，无法执行环境预生成",
            "env_root": "",
            "docs": [],
            "entropy": {},
        }

    from synapse.rd_meeting.env_pregen_assets import bootstrap_env_pregen, format_env_pregen_report
    from synapse.rd_meeting.product_context import match_prod_row_by_prod

    catalog_rows = _load_catalog_rows(sid, pipe)
    wire_hit = match_prod_row_by_prod(catalog_rows, prod) if catalog_rows else None
    assets = bootstrap_env_pregen(sid, prod, wire_row=wire_hit, catalog_rows=catalog_rows)
    _save_pipeline_context_assets(sid, "env_pregen_assets", assets)

    node_name = node_display_name(node_id)
    report_body = format_env_pregen_report(assets, node_name=node_name)
    stage_name = stage_name_for_id(int(dev.get("stage_id") or 0))
    artifacts = _write_system_archive(sid, node_id, stage_name, report_body)

    ok = assets.get("status") in ("ok", "partial") and (
        any(d.get("status") == "ok" for d in (assets.get("docs") or []) if isinstance(d, dict))
        or (assets.get("entropy") or {}).get("status") == "ok"
        or (assets.get("product_doc_mirror") or {}).get("status") == "ok"
    )
    if not ok and assets.get("status") == "failed":
        return {
            "status": "failed",
            "error": "; ".join(assets.get("errors") or []) or "环境预生成失败",
            "env_root": assets.get("env_root"),
            "docs": assets.get("docs") or [],
            "entropy": assets.get("entropy") or {},
            "artifacts": artifacts,
            "report_body": report_body,
        }

    return {
        "status": "ok" if assets.get("status") == "ok" else "partial",
        "env_root": assets.get("env_root"),
        "docs": assets.get("docs") or [],
        "entropy": assets.get("entropy") or {},
        "artifacts": artifacts,
        "report_body": report_body,
        "prod": prod,
    }


SYSTEM_NODE_HANDLERS: dict[str, SystemNodeHandler] = {
    "auto_split": handle_auto_split,
    "sandbox_build": handle_sandbox_build,
    "env_pregen": handle_env_pregen,
}


def run_system_node(
    node_id: str,
    *,
    scope_type: ScopeType,
    scope_id: str,
    dev: dict[str, Any],
    pipe: Any = None,
) -> dict[str, Any]:
    """执行已注册的系统节点 handler。"""
    nid = (node_id or "").strip()
    handler = SYSTEM_NODE_HANDLERS.get(nid)
    if handler is None:
        return {
            "status": "failed",
            "error": f"系统节点 {nid} 尚未注册代码 handler",
        }
    started = time.monotonic()
    try:
        out = handler(
            scope_type=scope_type,
            scope_id=scope_id,
            node_id=nid,
            dev=dev,
            pipe=pipe,
        )
    except Exception as exc:
        logger.exception("system node handler failed node=%s scope=%s", nid, scope_id)
        return {
            "status": "failed",
            "error": str(exc),
            "duration_seconds": int(time.monotonic() - started),
        }
    if isinstance(out, dict):
        out.setdefault("duration_seconds", int(time.monotonic() - started))
        return out
    return {"status": "failed", "error": "handler 返回格式无效"}
