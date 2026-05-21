"""Phase 1：room_state.json、room_history.jsonl、archive/ 读写。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock

from synapse.rd_meeting.paths import (
    archive_root,
    room_history_path,
    room_state_lock_path,
    room_state_path,
)
from synapse.rd_sop.nodes import ALL_NODES, node_display_name

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]
RoomStatus = Literal["processing", "human_intervention", "completed", "failed"]
ROOM_STATE_SCHEMA_VERSION = 1
DEFAULT_TOKEN_BUDGET = 150_000


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_room_state(
    *,
    room_id: str,
    scope_type: ScopeType,
    scope_id: str,
    stage_id: int,
    current_node_id: str,
    status: RoomStatus = "processing",
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": ROOM_STATE_SCHEMA_VERSION,
        "room_id": room_id,
        "scope": {"type": scope_type, "id": scope_id},
        "stage_id": stage_id,
        "current_node_id": current_node_id,
        "status": status,
        "metrics": {
            "stage_started_at": now,
            "stage_seconds": 0,
            "tokens": 0,
            "token_budget": DEFAULT_TOKEN_BUDGET,
        },
        "node_metrics": {},
        "agents_active": [],
        "updated_at": now,
    }


def read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 JSON 失败 %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = _now_iso()
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def load_room_state(scope_id: str) -> dict[str, Any] | None:
    return read_json_file(room_state_path(scope_id))


def save_room_state(scope_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = room_state_path(scope_id)
    lock = FileLock(str(room_state_lock_path(scope_id)), timeout=30)
    with lock:
        write_json_file(path, payload)
    return payload


def sync_room_state_from_dev(
    scope_id: str,
    *,
    room_id: str,
    scope_type: ScopeType,
    stage_id: int,
    current_node_id: str,
    local_process_state: str,
) -> dict[str, Any]:
    """打开/推进会议时，将 dev.status 光标同步进 room_state（保留既有 metrics）。"""
    status: RoomStatus = "processing"
    if local_process_state == "已完成":
        status = "completed"
    elif local_process_state not in ("处理中",):
        status = "human_intervention"

    lock = FileLock(str(room_state_lock_path(scope_id)), timeout=30)
    with lock:
        existing = read_json_file(room_state_path(scope_id))
        if existing is None or str(existing.get("room_id") or "") != room_id:
            payload = default_room_state(
                room_id=room_id,
                scope_type=scope_type,
                scope_id=scope_id,
                stage_id=stage_id,
                current_node_id=current_node_id,
                status=status,
            )
        else:
            payload = dict(existing)
            payload["stage_id"] = stage_id
            payload["current_node_id"] = current_node_id
            payload["status"] = status
            scope = payload.get("scope")
            if not isinstance(scope, dict):
                payload["scope"] = {"type": scope_type, "id": scope_id}
            else:
                payload["scope"] = {"type": scope_type, "id": scope_id}
            metrics = payload.get("metrics")
            if not isinstance(metrics, dict):
                payload["metrics"] = default_room_state(
                    room_id=room_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    stage_id=stage_id,
                    current_node_id=current_node_id,
                )["metrics"]
            if "token_budget" not in payload["metrics"]:
                payload["metrics"]["token_budget"] = DEFAULT_TOKEN_BUDGET
            if not isinstance(payload.get("node_metrics"), dict):
                payload["node_metrics"] = {}
            if not isinstance(payload.get("agents_active"), list):
                payload["agents_active"] = []
        write_json_file(room_state_path(scope_id), payload)
    return payload


def append_history_event(scope_id: str, event: dict[str, Any]) -> dict[str, Any]:
    path = room_history_path(scope_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(event)
    row.setdefault("ts", _now_iso())
    line = json.dumps(row, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return row


def read_history(scope_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    path = room_history_path(scope_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("读取 room_history 失败 %s: %s", path, exc)
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    if len(rows) > limit:
        return rows[-limit:]
    return rows


def list_archive_index(scope_id: str) -> list[dict[str, Any]]:
    root = archive_root(scope_id)
    if not root.is_dir():
        return []
    index: list[dict[str, Any]] = []
    for stage_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if not stage_dir.is_dir():
            continue
        try:
            stage_id = int(stage_dir.name)
        except ValueError:
            continue
        for node_dir in sorted(stage_dir.iterdir(), key=lambda p: p.name):
            if not node_dir.is_dir():
                continue
            files: list[dict[str, Any]] = []
            for f in sorted(node_dir.iterdir(), key=lambda p: p.name):
                if f.is_file():
                    rel = f.relative_to(root).as_posix()
                    files.append(
                        {
                            "name": f.name,
                            "relative_path": rel,
                            "size": f.stat().st_size,
                        }
                    )
            if files:
                index.append(
                    {
                        "stage_id": stage_id,
                        "node_id": node_dir.name,
                        "node_name": node_display_name(node_dir.name),
                        "files": files,
                    }
                )
    return index


def _flat_node_index() -> dict[str, int]:
    return {str(n["id"]): i for i, n in enumerate(ALL_NODES)}


def derive_node_states(current_node_id: str) -> dict[str, str]:
    order = _flat_node_index()
    cur = order.get(current_node_id, -1)
    states: dict[str, str] = {}
    for node in ALL_NODES:
        nid = str(node["id"])
        idx = order.get(nid, 9999)
        if cur < 0:
            states[nid] = "pending"
        elif idx < cur:
            states[nid] = "completed"
        elif idx == cur:
            states[nid] = "processing"
        else:
            states[nid] = "pending"
    return states


def build_meeting_summary_nodes(
    dev_status: dict[str, Any] | None,
    room_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    current_node_id = "pending"
    if dev_status:
        current_node_id = str(dev_status.get("current_node_id") or "pending")
    elif room_state:
        current_node_id = str(room_state.get("current_node_id") or "pending")

    node_states = derive_node_states(current_node_id)
    node_metrics = {}
    if room_state and isinstance(room_state.get("node_metrics"), dict):
        node_metrics = room_state["node_metrics"]

    nodes: list[dict[str, Any]] = []
    for node in ALL_NODES:
        nid = str(node["id"])
        nm = node_metrics.get(nid) if isinstance(node_metrics.get(nid), dict) else {}
        nodes.append(
            {
                "node_id": nid,
                "node_name": node_display_name(nid),
                "stage_id": int(node.get("stage_id") or 0),
                "stage_name": str(node.get("stage_name") or ""),
                "status": node_states.get(nid, "pending"),
                "metrics": {
                    "deal_seconds": int(nm.get("seconds") or 0),
                    "tokens": int(nm.get("tokens") or 0),
                    "started_at": nm.get("started_at"),
                    "completed_at": nm.get("completed_at"),
                },
            }
        )
    return nodes


def history_to_chat_logs(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """会议室 UI 用的简化聊天流（Phase 1：来自 history 事件）。"""
    logs: list[dict[str, Any]] = []
    for i, ev in enumerate(history):
        et = str(ev.get("event") or "")
        if et in (
            "chat_message",
            "human_intervene",
            "room_opened",
            "system",
            "delegation_started",
            "delegation_finished",
            "node_failed",
            "hitl_approved",
            "hitl_rejected",
            "node_pending_confirm",
        ):
            text = str(ev.get("text") or ev.get("message") or "").strip()
            if not text and et == "room_opened":
                text = "会议室已开启"
            if not text:
                continue
            logs.append(
                {
                    "id": str(ev.get("id") or f"hist-{i}"),
                    "agentId": str(ev.get("agent_id") or ("user" if et == "human_intervene" else "system")),
                    "text": text,
                    "timestamp": _format_ts_hms(str(ev.get("ts") or "")),
                    "type": str(ev.get("log_type") or ("user" if et == "human_intervene" else "info")),
                }
            )
    return logs


def _format_ts_hms(iso: str) -> str:
    if not iso:
        return datetime.now().strftime("%H:%M:%S")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except ValueError:
        return iso[:8] if len(iso) >= 8 else iso
