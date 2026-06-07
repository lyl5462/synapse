"""Phase 1：room_state.json、agents/<node_id>/room_history.jsonl、archive/ 读写。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock

from synapse.rd_meeting.paths import (
    agents_root,
    archive_root,
    room_history_path,
    room_state_lock_path,
    room_state_path,
    scope_dir,
)
from synapse.rd_sop.nodes import ALL_NODES, node_display_name, stage_id_for_name

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]
RoomStatus = Literal["processing", "human_intervention", "completed", "failed", "stopped"]
ROOM_STATE_SCHEMA_VERSION = 1
DEFAULT_TOKEN_BUDGET = 20_000_000  # 整场会议 token 预算（看板卡片）
DEFAULT_NODE_TOKEN_BUDGET = 3_000_000  # 单个 SOP 节点 token 预算（会议室顶栏）


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def compute_node_metrics_seconds(started_at: str, completed_at: str) -> int:
    """节点墙钟耗时：completed_at − started_at（秒）。"""
    start = _parse_iso_datetime(started_at)
    end = _parse_iso_datetime(completed_at)
    if start is None or end is None:
        return 0
    return max(1, int((end - start).total_seconds()))


def compute_stage_elapsed_seconds(stage_started_at: str, *, end_at: str | None = None) -> int:
    """会议墙钟耗时：当前时刻（或 end_at）− stage_started_at（秒）。"""
    return compute_node_metrics_seconds(stage_started_at, end_at or _now_iso())


def finalize_node_metrics(
    room_state: dict[str, Any],
    *,
    scope_id: str,
    node_id: str,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """归档 ``room_state.node_metrics[node_id]``：completed_at、seconds、tokens（activity 汇总）。"""
    from synapse.rd_meeting.agent_activity import aggregate_node_activity_tokens

    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    now = completed_at or _now_iso()

    node_metrics = room_state.get("node_metrics")
    if not isinstance(node_metrics, dict):
        node_metrics = {}
    prev = node_metrics.get(nid) if isinstance(node_metrics.get(nid), dict) else {}
    started = str(prev.get("started_at") or now)
    tokens = aggregate_node_activity_tokens(sid, nid)
    seconds = compute_node_metrics_seconds(started, now)

    entry = {
        "started_at": started,
        "completed_at": now,
        "seconds": seconds,
        "tokens": tokens,
    }
    node_metrics[nid] = entry
    room_state["node_metrics"] = node_metrics
    return entry


_LEGACY_NODE_TOKEN_PLACEHOLDERS = frozenset({64, 128, 256})


def archived_node_tokens(nm: dict[str, Any]) -> int:
    """节点归档 token（``node_metrics[node_id].tokens``，剔除历史占位值）。"""
    raw = int(nm.get("tokens") or 0)
    return 0 if raw in _LEGACY_NODE_TOKEN_PLACEHOLDERS else raw


def resolve_node_seconds(nm: dict[str, Any], *, node_status: str = "") -> int:
    """节点耗时：``completed_at − started_at``；无 ``completed_at`` 时用当前时刻 − ``started_at``。"""
    _ = node_status
    started = str(nm.get("started_at") or "").strip()
    if not started:
        return 0
    completed = str(nm.get("completed_at") or "").strip()
    if completed:
        return compute_node_metrics_seconds(started, completed)
    return compute_stage_elapsed_seconds(started)


def resolve_node_tokens_live(
    scope_id: str,
    node_id: str,
    nm: dict[str, Any],
    *,
    node_status: str,
) -> int:
    """节点 token 动态值：进行中从 activity.jsonl 汇总，否则用归档 tokens。"""
    static = archived_node_tokens(nm)
    if node_status != "processing":
        return static
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid:
        return static
    from synapse.rd_meeting.agent_activity import aggregate_node_activity_tokens

    live = aggregate_node_activity_tokens(sid, nid)
    return live if live > 0 else static


def resolve_node_summary_metrics(
    scope_id: str,
    node_id: str,
    nm: dict[str, Any],
    *,
    node_status: str,
) -> dict[str, Any]:
    """工单 / 会议室节点指标：``tokens`` 静态归档，``tokens_live`` 含进行中动态刷新。"""
    raw = int(nm.get("tokens") or 0)
    static_tokens = archived_node_tokens(nm)
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if raw in _LEGACY_NODE_TOKEN_PLACEHOLDERS and sid and nid:
        from synapse.rd_meeting.agent_activity import aggregate_node_activity_tokens

        activity_tokens = aggregate_node_activity_tokens(sid, nid)
        if activity_tokens > 0:
            static_tokens = activity_tokens
    live_tokens = resolve_node_tokens_live(sid, nid, nm, node_status=node_status)
    return {
        "deal_seconds": resolve_node_seconds(nm, node_status=node_status),
        "tokens": static_tokens,
        "tokens_live": live_tokens,
        "started_at": nm.get("started_at"),
        "completed_at": nm.get("completed_at"),
    }


def refresh_node_metrics(
    scope_id: str,
    node_id: str,
    *,
    current_node_id: str = "",
) -> int:
    """进行中节点 live 轮询：从 activity.jsonl 汇总 token 并写回 node_metrics。"""
    from synapse.rd_meeting.agent_activity import aggregate_node_activity_tokens

    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid:
        return 0

    rs = load_room_state(sid)
    if not isinstance(rs, dict):
        return aggregate_node_activity_tokens(sid, nid)

    nm = rs.get("node_metrics")
    if not isinstance(nm, dict):
        nm = {}
    entry = dict(nm.get(nid) if isinstance(nm.get(nid), dict) else {})
    cur = (current_node_id or str(rs.get("current_node_id") or "")).strip()
    is_processing = not entry.get("completed_at") and (not cur or nid == cur)

    if not is_processing:
        return archived_node_tokens(entry)

    live_tokens = aggregate_node_activity_tokens(sid, nid)
    tokens = live_tokens if live_tokens > 0 else archived_node_tokens(entry)

    payload = dict(rs)
    nm = dict(nm)
    entry["tokens"] = tokens
    if not entry.get("started_at") and tokens > 0:
        entry["started_at"] = _now_iso()
    nm[nid] = entry
    payload["node_metrics"] = nm
    save_room_state(sid, payload)
    return tokens


def ensure_metrics_token_budget(scope_id: str) -> None:
    """将 ``room_state.metrics.token_budget`` 对齐为当前默认预算（幂等）。"""
    sid = (scope_id or "").strip()
    if not sid:
        return
    rs = load_room_state(sid)
    if not isinstance(rs, dict):
        return
    metrics = rs.get("metrics")
    if not isinstance(metrics, dict):
        return
    if int(metrics.get("token_budget") or 0) == DEFAULT_TOKEN_BUDGET:
        return
    payload = dict(rs)
    m = dict(metrics)
    m["token_budget"] = DEFAULT_TOKEN_BUDGET
    payload["metrics"] = m
    save_room_state(sid, payload)


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


def mark_room_stopped(scope_id: str, *, reason: str = "user_stop") -> dict[str, Any]:
    """将会议室标为 stopped，并记录原因（不清理节点过程数据）。"""
    sid = (scope_id or "").strip()
    rs = dict(load_room_state(sid) or {})
    rs["status"] = "stopped"
    rs["stopped_at"] = _now_iso()
    rs["stopped_reason"] = (reason or "user_stop").strip() or "user_stop"
    return save_room_state(sid, rs)


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
            payload["metrics"]["token_budget"] = DEFAULT_TOKEN_BUDGET
            if not isinstance(payload.get("node_metrics"), dict):
                payload["node_metrics"] = {}
            if not isinstance(payload.get("agents_active"), list):
                payload["agents_active"] = []
        write_json_file(room_state_path(scope_id), payload)
    return payload


def resolve_history_node_id(scope_id: str, event: dict[str, Any]) -> str:
    """解析 history 应写入的 SOP 节点目录。"""
    for key in ("node_id", "current_node_id"):
        val = str(event.get(key) or "").strip()
        if val and val != "pending":
            return val
    rs = load_room_state(scope_id)
    if isinstance(rs, dict):
        cur = str(rs.get("current_node_id") or "").strip()
        if cur and cur != "pending":
            return cur
    try:
        from synapse.rd_meeting.dev_status import load_dev_status

        dev = load_dev_status(scope_id)
        if isinstance(dev, dict):
            cur = str(dev.get("current_node_id") or "").strip()
            if cur and cur != "pending":
                return cur
    except Exception:
        pass
    return "pending"


def _read_history_file(path: Path) -> list[dict[str, Any]]:
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
    return rows


def _merge_history_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for group in groups:
        merged.extend(group)
    merged.sort(key=lambda ev: str(ev.get("ts") or ""))
    return merged


def append_history_event(scope_id: str, event: dict[str, Any]) -> dict[str, Any]:
    from synapse.rd_meeting.flow_log import apply_flow_log_format

    node_id = resolve_history_node_id(scope_id, event)
    path = room_history_path(scope_id, node_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = apply_flow_log_format(dict(event))
    row.setdefault("node_id", node_id)
    row.setdefault("ts", _now_iso())
    line = json.dumps(row, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return row


def extract_skipped_node_ids(history: list[dict[str, Any]]) -> list[str]:
    """从 room_history 提取已跳过的 SOP 节点 id（按出现顺序去重）。"""
    out: list[str] = []
    seen: set[str] = set()
    for ev in history:
        if str(ev.get("event") or "") != "node_skipped":
            continue
        nid = str(ev.get("node_id") or "").strip()
        if nid and nid not in seen:
            seen.add(nid)
            out.append(nid)
    return out


def read_history(
    scope_id: str,
    *,
    node_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """读取协作流 history。

    - ``node_id`` 指定时：只读 ``agents/<node_id>/room_history.jsonl``。
    - ``node_id`` 为 ``None``：合并各 SOP 节点 history（供 summary / 全量 chat 展示）。
    """
    sid = (scope_id or "").strip()
    if not sid:
        return []

    if node_id is not None:
        nid = (node_id or "pending").strip() or "pending"
        rows = _read_history_file(room_history_path(sid, nid))
        if limit and len(rows) > limit:
            return rows[-limit:]
        return rows

    groups: list[list[dict[str, Any]]] = []
    root = agents_root(sid)
    if root.is_dir():
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            hist = entry / "room_history.jsonl"
            if hist.is_file():
                groups.append(_read_history_file(hist))
    rows = _merge_history_rows(*groups) if groups else []

    if limit and len(rows) > limit:
        return rows[-limit:]
    return rows


def list_archive_index(scope_id: str) -> list[dict[str, Any]]:
    root = archive_root(scope_id)
    if not root.is_dir():
        return []
    scope_root = scope_dir(scope_id).resolve()
    index: list[dict[str, Any]] = []
    for stage_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if not stage_dir.is_dir():
            continue
        stage_name = stage_dir.name
        stage_id = stage_id_for_name(stage_name)
        for node_dir in sorted(stage_dir.iterdir(), key=lambda p: p.name):
            if not node_dir.is_dir():
                continue
            files: list[dict[str, Any]] = []
            for f in sorted(node_dir.iterdir(), key=lambda p: p.name):
                if f.is_file():
                    try:
                        rel = f.resolve().relative_to(scope_root).as_posix()
                    except ValueError:
                        rel = f"archive/{f.relative_to(root).as_posix()}"
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
    *,
    scope_id: str = "",
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

    sid = (scope_id or "").strip()
    if not sid and isinstance(room_state, dict):
        scope = room_state.get("scope")
        if isinstance(scope, dict):
            sid = str(scope.get("id") or "").strip()

    nodes: list[dict[str, Any]] = []
    for node in ALL_NODES:
        nid = str(node["id"])
        nm = node_metrics.get(nid) if isinstance(node_metrics.get(nid), dict) else {}
        node_status = node_states.get(nid, "pending")
        nodes.append(
            {
                "node_id": nid,
                "node_name": node_display_name(nid),
                "stage_id": int(node.get("stage_id") or 0),
                "stage_name": str(node.get("stage_name") or ""),
                "status": node_status,
                "metrics": resolve_node_summary_metrics(sid, nid, nm, node_status=node_status),
            }
        )
    return nodes


def history_to_chat_logs(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """会议室 UI 用的结构化聊天流（见 ``chat_display``）。"""
    from synapse.rd_meeting.chat_display import history_to_chat_logs as _structured_logs

    return _structured_logs(history)


def _format_ts_hms(iso: str) -> str:
    if not iso:
        return datetime.now().strftime("%H:%M:%S")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except ValueError:
        return iso[:8] if len(iso) >= 8 else iso
