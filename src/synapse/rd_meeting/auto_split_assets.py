"""自动拆单：从 userwork 与研发云门户同步研发子单清单。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from synapse.rd_meeting.product_assets import _now_iso
from synapse.rd_meeting.userwork_sync import _load_userwork_list, _scope_row

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]


def _norm_id(raw: str) -> str:
    from synapse.api.routes.dev_iwhalecloud import _snapshot_norm_id

    return _snapshot_norm_id(raw)


def _resolve_demand_no(scope_type: ScopeType, scope_id: str) -> str:
    sid = _norm_id(scope_id)
    if scope_type == "demand":
        return sid
    row = _scope_row(scope_type, scope_id)
    if row:
        dn = _norm_id(str(row.get("demand_no") or ""))
        if dn:
            return dn
    return sid


def _local_owned_tasks(demand_no: str) -> list[dict[str, Any]]:
    dn = _norm_id(demand_no)
    for demand in _load_userwork_list():
        if _norm_id(str(demand.get("demand_no") or "")) != dn:
            continue
        owned = demand.get("owned_work_items")
        if not isinstance(owned, list):
            return []
        return [t for t in owned if isinstance(t, dict)]
    return []


def _fetch_portal_task_nos(demand_no: str) -> tuple[list[str], str]:
    """调用研发云门户任务列表 API，返回 (taskNo 列表, 错误说明)。"""
    from synapse.api.routes.dev_iwhalecloud import (
        GetTaskListFromDemandRequest,
        _get_task_list_from_demand,
    )

    async def _run() -> dict:
        return await _get_task_list_from_demand(GetTaskListFromDemandRequest(demandNo=demand_no))

    try:
        resp = asyncio.run(_run())
    except Exception as exc:
        logger.warning("auto_split portal fetch failed demand=%s: %s", demand_no, exc)
        return [], f"门户 API 异常: {exc}"

    if not isinstance(resp, dict):
        return [], "门户 API 返回格式无效"
    code = resp.get("code")
    try:
        ok = int(code) == 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        ok = False
    if not ok:
        return [], str(resp.get("message") or resp.get("error") or "门户 API 失败")

    data = resp.get("data")
    if not isinstance(data, list):
        return [], "门户 API data 非列表"

    nos: list[str] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        tn = str(row.get("taskNo") or "").strip()
        if tn:
            nos.append(tn)
    return nos, ""


def bootstrap_auto_split(
    scope_type: ScopeType,
    scope_id: str,
) -> dict[str, Any]:
    """汇总本地 userwork 子单与门户任务列表，生成拆单摘要。"""
    sid = (scope_id or "").strip()
    demand_no = _resolve_demand_no(scope_type, sid)
    result: dict[str, Any] = {
        "scope_type": scope_type,
        "scope_id": sid,
        "demand_no": demand_no,
        "local_tasks": [],
        "portal_task_nos": [],
        "portal_error": "",
        "status": "ok",
        "errors": [],
        "materialized_at": _now_iso(),
    }

    if not sid or not demand_no:
        result["status"] = "failed"
        result["errors"].append("scope_id 或 demand_no 为空")
        return result

    local = _local_owned_tasks(demand_no)
    result["local_tasks"] = [
        {
            "task_no": str(t.get("task_no") or ""),
            "task_title": str(t.get("task_title") or ""),
            "sop_node": str(t.get("sop_node") or ""),
            "local_process_state": str(t.get("local_process_state") or ""),
        }
        for t in local
    ]

    portal_nos, portal_err = _fetch_portal_task_nos(demand_no)
    result["portal_task_nos"] = portal_nos
    result["portal_error"] = portal_err

    local_nos = {_norm_id(str(t.get("task_no") or "")) for t in local if t.get("task_no")}
    portal_norm = {_norm_id(n) for n in portal_nos}
    only_portal = sorted(portal_norm - local_nos - {""})
    only_local = sorted(local_nos - portal_norm - {""})

    result["only_in_portal"] = only_portal
    result["only_in_local"] = only_local

    if portal_err and not local:
        result["status"] = "failed"
        result["errors"].append(portal_err)
    elif portal_err:
        result["status"] = "partial"
        result["errors"].append(portal_err)
    elif not local and not portal_nos:
        result["status"] = "partial"
        result["errors"].append("本地与门户均无研发子单，请确认需求单是否已拆分")

    return result


def format_auto_split_report(assets: dict[str, Any], *, node_name: str) -> str:
    """生成 ``研发子单拆分清单.md`` 正文。"""
    lines = [
        f"# {node_name} — 研发子单拆分清单",
        "",
        "本节点由系统脚本执行（userwork + 研发云门户同步），未调用大模型与人工确认。",
        "",
        f"- **需求单号**：{assets.get('demand_no') or '—'}",
        f"- **同步时间**：{assets.get('materialized_at') or '—'}",
        f"- **总体状态**：{assets.get('status') or '—'}",
        "",
        "## 本地 userwork 子单",
        "",
    ]
    local = assets.get("local_tasks") if isinstance(assets.get("local_tasks"), list) else []
    if not local:
        lines.append("（无）")
    else:
        for row in local:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- **{row.get('task_no') or '—'}** {row.get('task_title') or ''} "
                f"— sop={row.get('sop_node') or '—'} / {row.get('local_process_state') or '—'}"
            )

    portal = assets.get("portal_task_nos") if isinstance(assets.get("portal_task_nos"), list) else []
    lines.extend(["", "## 门户任务列表", ""])
    if assets.get("portal_error"):
        lines.append(f"（门户同步失败：{assets.get('portal_error')}）")
    elif not portal:
        lines.append("（无）")
    else:
        for tn in portal:
            lines.append(f"- {tn}")

    only_p = assets.get("only_in_portal") or []
    only_l = assets.get("only_in_local") or []
    if only_p or only_l:
        lines.extend(["", "## 差异", ""])
        if only_p:
            lines.append(f"- 仅门户：{', '.join(only_p)}")
        if only_l:
            lines.append(f"- 仅本地：{', '.join(only_l)}")

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "自动拆单已完成：已汇总本地与门户研发子单，可进入沙箱构建等后续节点。",
            "",
        ]
    )
    return "\n".join(lines)
