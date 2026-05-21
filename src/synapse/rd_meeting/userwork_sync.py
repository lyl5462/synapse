"""会议室 → userwork.json：回写 local_process_state / sop_node / prod。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock

from synapse.api.routes.dev_iwhalecloud import (
    _atomic_write_json_file,
    _owner_order_file_lock_path,
    _owner_order_file_name,
    _snapshot_norm_id,
    load_owner_order_snapshot_from_file,
)

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]


def _load_userwork_list() -> list[dict[str, Any]]:
    snap = load_owner_order_snapshot_from_file()
    if not snap or not isinstance(snap.get("list"), list):
        return []
    return [x for x in snap["list"] if isinstance(x, dict)]


def patch_userwork_summary(
    *,
    scope_type: ScopeType,
    scope_id: str,
    sop_node: str | None = None,
    local_process_state: str | None = None,
    task_sop_node: str | None = None,
    prod: str | None = None,
) -> dict[str, str]:
    """更新 userwork 摘要字段。返回本次写入的字段（键为 userwork 字段名）。"""
    path: Path = _owner_order_file_name()
    if not path.is_file():
        return {}

    dn = _snapshot_norm_id(scope_id)
    if not dn:
        return {}

    lock = FileLock(str(_owner_order_file_lock_path()), timeout=30)
    with lock:
        try:
            raw = path.read_text(encoding="utf-8")
            prev = json.loads(raw)
            if not isinstance(prev, dict):
                return {}
            existing_list = prev.get("list")
            if not isinstance(existing_list, list):
                return {}
        except (OSError, json.JSONDecodeError):
            return {}

        modified = False
        applied: dict[str, str] = {}
        for demand in existing_list:
            if not isinstance(demand, dict):
                continue
            if scope_type == "demand":
                if _snapshot_norm_id(demand.get("demand_no")) != dn:
                    continue
                if sop_node is not None:
                    demand["sop_node"] = sop_node
                    applied["sop_node"] = sop_node
                    modified = True
                if local_process_state is not None:
                    demand["local_process_state"] = local_process_state
                    applied["local_process_state"] = local_process_state
                    modified = True
                if prod is not None:
                    demand["prod"] = prod
                    applied["prod"] = prod
                    modified = True
                break
            # task scope
            owned = demand.get("owned_work_items")
            if not isinstance(owned, list):
                continue
            for task in owned:
                if not isinstance(task, dict):
                    continue
                if _snapshot_norm_id(task.get("task_no")) != dn:
                    continue
                node_val = task_sop_node if task_sop_node is not None else sop_node
                if node_val is not None:
                    task["sop_node"] = node_val
                    applied["sop_node"] = node_val
                    modified = True
                if local_process_state is not None:
                    task["local_process_state"] = local_process_state
                    applied["local_process_state"] = local_process_state
                    modified = True
                if prod is not None:
                    task["prod"] = prod
                    applied["prod"] = prod
                    modified = True
                break
            if modified:
                break

        if not modified:
            return {}

        payload = {
            "list": existing_list,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _atomic_write_json_file(path, payload)
        return applied


def load_scope_work_order_context(
    scope_type: ScopeType,
    scope_id: str,
) -> dict[str, str]:
    """从 userwork 快照读取工单上下文（P1 运行时注入）。"""
    row = _scope_row(scope_type, scope_id)
    if not row:
        return {}
    out: dict[str, str] = {
        "demand_title": str(row.get("demand_title") or row.get("task_title") or ""),
        "demand_desc": str(row.get("demand_desc") or row.get("comments") or ""),
        "demand_impact": str(row.get("demand_impact") or ""),
        "product_version_code": str(row.get("product_version_code") or row.get("branch") or ""),
        "repo_url": str(row.get("repo_url") or row.get("branch") or ""),
    }
    if scope_type == "task":
        out["task_title"] = str(row.get("task_title") or "")
        out["task_no"] = str(row.get("task_no") or scope_id)
    else:
        out["demand_no"] = str(row.get("demand_no") or scope_id)
    prod_val = str(row.get("prod") or "").strip()
    if prod_val:
        out["prod"] = prod_val
    return {k: v for k, v in out.items() if v}


def _scope_row(scope_type: ScopeType, scope_id: str) -> dict[str, Any] | None:
    from synapse.api.routes.dev_iwhalecloud import _snapshot_norm_id

    sid = _snapshot_norm_id(scope_id)
    for demand in _load_userwork_list():
        if scope_type == "demand":
            if _snapshot_norm_id(demand.get("demand_no")) == sid:
                return demand
            continue
        owned = demand.get("owned_work_items")
        if not isinstance(owned, list):
            continue
        for task in owned:
            if isinstance(task, dict) and _snapshot_norm_id(task.get("task_no")) == sid:
                merged = dict(demand)
                merged.update(task)
                merged["scope_type"] = "task"
                return merged
    return None


def build_title_index() -> dict[str, dict[str, str]]:
    """scope_id → { title, branch?, scope_type }，从 userwork 只读构建。"""
    index: dict[str, dict[str, str]] = {}
    for demand in _load_userwork_list():
        dn = _snapshot_norm_id(demand.get("demand_no"))
        if dn:
            index[dn] = {
                "title": str(demand.get("demand_title") or dn),
                "scope_type": "demand",
                "branch": str(demand.get("product_version_code") or ""),
            }
        owned = demand.get("owned_work_items")
        if not isinstance(owned, list):
            continue
        for task in owned:
            if not isinstance(task, dict):
                continue
            tn = _snapshot_norm_id(task.get("task_no"))
            if not tn:
                continue
            index[tn] = {
                "title": str(task.get("task_title") or tn),
                "scope_type": "task",
                "branch": str(task.get("repo_url") or ""),
            }
    return index
