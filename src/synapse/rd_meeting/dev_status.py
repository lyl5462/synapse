"""work/<scope_id>/dev.status 读写与 schema。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock

from synapse.rd_meeting.paths import dev_status_lock_path, dev_status_path

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]
DEV_STATUS_SCHEMA_VERSION = 1
ACTIVE_LOCAL_STATES = frozenset({"处理中"})


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_dev_status(
    *,
    scope_type: ScopeType,
    scope_id: str,
    local_process_state: str = "待处理",
    stage_id: int = 0,
    current_node_id: str = "pending",
    sop_node_display: str = "",
    pipeline_enabled: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": DEV_STATUS_SCHEMA_VERSION,
        "scope": {"type": scope_type, "id": scope_id},
        "local_process_state": local_process_state,
        "stage_id": stage_id,
        "current_node_id": current_node_id,
        "sop_node_display": sop_node_display,
        "pipeline_enabled": pipeline_enabled,
        "meeting_room": {"active": False, "room_id": ""},
        "updated_at": _now_iso(),
    }


def read_dev_status_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 dev.status 失败 %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_dev_status_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = _now_iso()
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def load_dev_status(scope_id: str) -> dict[str, Any] | None:
    return read_dev_status_file(dev_status_path(scope_id))


def save_dev_status(scope_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = dev_status_path(scope_id)
    lock = FileLock(str(dev_status_lock_path(scope_id)), timeout=30)
    with lock:
        write_dev_status_file(path, payload)
    return payload


def load_or_create_dev_status(
    scope_id: str,
    *,
    scope_type: ScopeType,
    **defaults: Any,
) -> dict[str, Any]:
    path = dev_status_path(scope_id)
    lock = FileLock(str(dev_status_lock_path(scope_id)), timeout=30)
    with lock:
        existing = read_dev_status_file(path)
        if existing is not None:
            return existing
        payload = default_dev_status(scope_type=scope_type, scope_id=scope_id, **defaults)
        write_dev_status_file(path, payload)
        return payload


def should_list_in_meeting_rooms(data: dict[str, Any]) -> bool:
    local = str(data.get("local_process_state") or "").strip()
    if local in ACTIVE_LOCAL_STATES:
        return True
    if data.get("pipeline_enabled") is True:
        return True
    mr = data.get("meeting_room")
    if isinstance(mr, dict) and mr.get("active") is True:
        return True
    return False


def ensure_room_id(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    mr = out.get("meeting_room")
    if not isinstance(mr, dict):
        mr = {}
    scope = out.get("scope") if isinstance(out.get("scope"), dict) else {}
    scope_type = str(scope.get("type") or "demand")
    scope_id = str(scope.get("id") or "")
    stage_id = int(out.get("stage_id") or 0)
    prefix = "mr_d" if scope_type == "demand" else "mr_t"
    room_id = str(mr.get("room_id") or "").strip()
    if not room_id and scope_id:
        room_id = f"{prefix}_{scope_id}_s{stage_id}"
    mr = {**mr, "room_id": room_id}
    if mr.get("active") is not True and str(out.get("local_process_state") or "").strip() in ACTIVE_LOCAL_STATES:
        mr["active"] = True
    out["meeting_room"] = mr
    return out
