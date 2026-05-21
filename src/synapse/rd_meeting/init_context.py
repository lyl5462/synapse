"""会议室节点初始化：从 userwork 汇总工单 / 产品 / 系统信息（仅流程日志，不含主控 prompt）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.api.routes.dev_iwhalecloud import _snapshot_norm_id
from synapse.rd_meeting.paths import scope_dir
from synapse.rd_meeting.runtime_context import (
    _resolve_gitnexus_url,
    _resolve_gnx_cache_dir,
    _resolve_repo_name,
    _resolve_synapse_url,
)
from synapse.rd_meeting.userwork_sync import _load_userwork_list, _scope_row
from synapse.rd_sop.nodes import node_display_name

ScopeType = Literal["demand", "task"]

_STANDARD_PRODUCT_DOCS = (
    "FUNCTIONAL_ARCH.md",
    "TECH_ARCH.md",
    "PRODUCT_DEV.md",
)


def get_userwork_row(scope_type: ScopeType, scope_id: str) -> dict[str, Any] | None:
    """读取 userwork.json 中当前 scope 对应行（需求单或研发子单合并视图）。"""
    return _scope_row(scope_type, scope_id)


def _truncate(text: str, limit: int = 1200) -> str:
    t = (text or "").strip().replace("\r\n", "\n")
    if len(t) <= limit:
        return t or "（空）"
    return t[:limit] + "…"


def _collect_repos(row: dict[str, Any], scope_type: ScopeType) -> list[str]:
    repos: list[str] = []
    if scope_type == "task":
        ru = str(row.get("repo_url") or "").strip()
        if ru:
            repos.append(ru)
    owned = row.get("owned_work_items")
    if isinstance(owned, list):
        for item in owned:
            if not isinstance(item, dict):
                continue
            ru = str(item.get("repo_url") or "").strip()
            if ru and ru not in repos:
                repos.append(ru)
    return repos


def _collect_local_docs(scope_id: str) -> list[str]:
    root = scope_dir(scope_id)
    found: list[str] = []
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.rglob("*.md")):
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = p.name
            found.append(rel)
    for name in _STANDARD_PRODUCT_DOCS:
        if (root / name).is_file() and name not in found:
            found.append(name)
    return found


def _collect_history_demands(row: dict[str, Any], *, scope_id: str, limit: int = 8) -> list[str]:
    pvc = str(row.get("product_version_code") or "").strip()
    if not pvc:
        return []
    cur = _snapshot_norm_id(scope_id)
    out: list[str] = []
    for demand in _load_userwork_list():
        if not isinstance(demand, dict):
            continue
        if str(demand.get("product_version_code") or "").strip() != pvc:
            continue
        dn = _snapshot_norm_id(demand.get("demand_no"))
        if not dn or dn == cur:
            continue
        title = str(demand.get("demand_title") or dn).strip()
        out.append(f"{dn} · {title[:80]}")
        if len(out) >= limit:
            break
    return out


def collect_meeting_init_sections(
    scope_type: ScopeType,
    scope_id: str,
    *,
    node_id: str = "",
) -> dict[str, Any]:
    """汇总节点初始化三块信息（来源以 userwork 为主）。"""
    sid = (scope_id or "").strip()
    row = get_userwork_row(scope_type, sid) if sid else None
    wo: dict[str, str] = {}
    if row:
        from synapse.rd_meeting.userwork_sync import load_scope_work_order_context

        wo = load_scope_work_order_context(scope_type, sid)

    order_id = str(wo.get("demand_no") or wo.get("task_no") or sid or "（未知）")
    order_title = str(wo.get("demand_title") or wo.get("task_title") or "（未知）")
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

    repos = _collect_repos(row or {}, scope_type)
    local_docs = _collect_local_docs(sid) if sid else []
    product_code = str(row.get("product_version_code") if row else "" or wo.get("product_version_code") or "")
    product_id = row.get("product_version_id") if row else None
    history = _collect_history_demands(row or {}, scope_id=sid)

    synapse_url = _resolve_synapse_url()
    gitnexus_url = _resolve_gitnexus_url()
    repo_name = _resolve_repo_name(wo)
    gnx_cache = _resolve_gnx_cache_dir(repo_name)

    return {
        "node_id": node_id,
        "node_name": node_display_name(node_id) if node_id else "",
        "order": {
            "id": order_id,
            "title": order_title,
            "description": order_desc,
            "impact": str(wo.get("demand_impact") or (row.get("demand_impact") if row else "") or ""),
            "scope_type": scope_type,
        },
        "product": {
            "product_version_code": product_code or "（未配置）",
            "product_version_id": product_id if product_id is not None else "（未配置）",
            "standard_docs": list(_STANDARD_PRODUCT_DOCS),
            "local_docs": local_docs,
            "repos": repos,
            "history_demands": history,
        },
        "system": {
            "synapse_url": synapse_url or "（未配置）",
            "gitnexus_url": gitnexus_url or "（未配置）",
            "repo_name": repo_name or "（未配置）",
            "gnx_cache_dir": gnx_cache or "（未配置）",
            "work_order_dir": str(scope_dir(sid)) if sid else "（未解析）",
        },
    }


def format_node_init_log(
    scope_type: ScopeType,
    scope_id: str,
    *,
    node_id: str,
) -> str:
    """节点初始化流程日志正文（不含小鲸主持提示词）。"""
    sec = collect_meeting_init_sections(scope_type, scope_id, node_id=node_id)
    order = sec["order"]
    product = sec["product"]
    system = sec["system"]
    node_name = sec["node_name"] or node_id

    lines = [
        f"节点：{node_name}（{node_id}）",
        "",
        "【工单信息】",
        f"- 工单ID：{order['id']}",
        f"- 工单标题：{order['title']}",
        f"- 工单描述：{_truncate(str(order['description']))}",
    ]
    if order.get("impact"):
        lines.append(f"- 需求影响：{_truncate(str(order['impact']), 400)}")

    lines.extend(
        [
            "",
            "【产品信息】",
            f"- 产品版本编码：{product['product_version_code']}",
            f"- 产品版本ID：{product['product_version_id']}",
            f"- 标准产品文档（约定名）：{', '.join(product['standard_docs'])}",
        ]
    )
    local_docs = product.get("local_docs") or []
    lines.append(
        f"- 工单目录已有文档：{', '.join(local_docs) if local_docs else '（暂无，待 get_doc 或技能拉取）'}"
    )
    repos = product.get("repos") or []
    lines.append(f"- 关联仓库：{'; '.join(repos) if repos else '（userwork 未配置 repo_url）'}")
    history = product.get("history_demands") or []
    if history:
        lines.append("- 同产品历史工单：")
        for h in history:
            lines.append(f"  · {h}")
    else:
        lines.append("- 同产品历史工单：（无或未配置 product_version_code）")

    lines.extend(
        [
            "",
            "【系统信息】",
            f"- 统一服务地址（Synapse）：{system['synapse_url']}",
            f"- GitNexus 地址：{system['gitnexus_url']}",
            f"- 解析仓库名：{system['repo_name']}",
            f"- GitNexus 缓存目录：{system['gnx_cache_dir']}",
            f"- 工单工作目录：{system['work_order_dir']}",
        ]
    )
    return "\n".join(lines)
