"""会议室节点初始化：工单（userwork）+ 产品定位（统一服务）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.flow_log import flow_log_to_text
from synapse.rd_meeting.product_context import resolve_product_for_meeting
from synapse.rd_meeting.userwork_sync import _scope_row

ScopeType = Literal["demand", "task"]


def get_userwork_row(scope_type: ScopeType, scope_id: str) -> dict[str, Any] | None:
    """读取 userwork.json 中当前 scope 对应行。"""
    return _scope_row(scope_type, scope_id)


def _collect_order_section(
    scope_type: ScopeType,
    scope_id: str,
) -> dict[str, Any]:
    sid = (scope_id or "").strip()
    row = _scope_row(scope_type, sid) if sid else None
    wo: dict[str, str] = {}
    if row:
        from synapse.rd_meeting.userwork_sync import load_scope_work_order_context

        wo = load_scope_work_order_context(scope_type, sid)

    order_id = str(wo.get("demand_no") or wo.get("task_no") or sid or "")
    order_title = str(
        wo.get("demand_title")
        or wo.get("task_title")
        or (row.get("demand_title") if row else "")
        or (row.get("task_title") if row else "")
        or ""
    )
    if row:
        order_desc = str(
            wo.get("demand_desc")
            or row.get("demand_desc")
            or row.get("task_desc")
            or row.get("comments")
            or ""
        )
    else:
        order_desc = str(wo.get("demand_desc") or "")

    return {
        "id": order_id,
        "title": order_title,
        "description": order_desc,
        "impact": str(wo.get("demand_impact") or (row.get("demand_impact") if row else "") or ""),
        "prod": str(wo.get("prod") or (row.get("prod") if row else "") or "").strip(),
        "scope_type": scope_type,
        "scope_id": sid,
    }


def build_node_init_log_data(
    scope_type: ScopeType,
    scope_id: str,
    *,
    node_id: str = "",
) -> dict[str, Any]:
    """节点初始化日志：order + product（统一服务定位）+ system。"""
    _ = node_id
    order = _collect_order_section(scope_type, scope_id)
    product, system = resolve_product_for_meeting(scope_type, scope_id)
    sid = (scope_id or "").strip()
    if sid:
        from synapse.rd_meeting.product_assets import (
            assets_system_fields,
            enrich_product_with_assets,
            load_product_assets_from_pipeline,
        )

        assets = load_product_assets_from_pipeline(sid)
        product = enrich_product_with_assets(product, assets)
        system = {**system, **assets_system_fields(assets)}
    return {
        "order": order,
        "product": product,
        "system": system,
    }


def collect_meeting_init_sections(
    scope_type: ScopeType,
    scope_id: str,
    *,
    node_id: str = "",
) -> dict[str, Any]:
    """兼容旧调用。"""
    return build_node_init_log_data(scope_type, scope_id, node_id=node_id)


def normalize_node_init_log_data(data: dict[str, Any]) -> dict[str, Any]:
    """规范旧版 node_init JSON（去掉 history_demands / node 等）。"""
    out = dict(data)
    out.pop("node", None)
    out.pop("history_demands", None)
    product = out.get("product")
    if isinstance(product, dict):
        p = dict(product)
        p.pop("history_demands", None)
        p.pop("standard_docs", None)
        p.pop("local_docs", None)
        legacy = str(p.get("function") or "").strip()
        if legacy:
            p["prod_feature"] = legacy
        out["product"] = p
    system = out.get("system")
    if isinstance(system, dict):
        s = dict(system)
        # work_order_dir / product_code_root / product_doc_root 由 room_opened 落盘注入，保留供四段式与 SKILL 使用
        s.pop("repo_name", None)
        s.pop("gitnexus_url", None)
        s.pop("gnx_cache_base_dir", None)
        s.pop("gnx_cache_dir", None)
        out["system"] = s
    if "order" in out:
        return out
    return out


def format_node_init_log(
    scope_type: ScopeType,
    scope_id: str,
    *,
    node_id: str,
) -> str:
    return flow_log_to_text(build_node_init_log_data(scope_type, scope_id, node_id=node_id))


def node_init_payload(
    scope_type: ScopeType,
    scope_id: str,
    *,
    node_id: str,
) -> dict[str, Any]:
    return build_node_init_log_data(scope_type, scope_id, node_id=node_id)
