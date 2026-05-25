"""work/<scope_id>/ 路径与目录名规范化（对齐 setup-center rdWorkOrderPaths）。"""

from __future__ import annotations

import re
from pathlib import Path

from synapse.config import settings

MAX_SEGMENT_LEN = 120
_SKIP_WORK_ROOT_NAMES = frozenset({"userwork.json", "userwork.json.lock"})


def work_root() -> Path:
    return settings.synapse_home / "work"


def sanitize_work_order_segment(raw: str) -> str:
    t = (raw or "").strip() or "default"
    base = t.replace("\\", "/").split("/")[-1] or t
    out: list[str] = []
    for c in base:
        if re.match(r"[a-zA-Z0-9_-]", c):
            out.append(c)
        elif c.isspace():
            if out and out[-1] != "_":
                out.append("_")
        elif ord(c) >= 0x20:
            out.append("_")
    s = "".join(out).strip("_")
    if not s or s in (".", ".."):
        s = "default"
    if len(s) > MAX_SEGMENT_LEN:
        s = s[:MAX_SEGMENT_LEN]
    return s


def scope_dir(scope_id: str) -> Path:
    seg = sanitize_work_order_segment(scope_id)
    return work_root() / seg


def dev_status_path(scope_id: str) -> Path:
    return scope_dir(scope_id) / "dev.status"


def dev_status_lock_path(scope_id: str) -> Path:
    return scope_dir(scope_id) / "dev.status.lock"


def room_state_path(scope_id: str) -> Path:
    return scope_dir(scope_id) / "room_state.json"


def room_state_lock_path(scope_id: str) -> Path:
    return scope_dir(scope_id) / "room_state.lock"


def room_history_path(scope_id: str) -> Path:
    return scope_dir(scope_id) / "room_history.jsonl"


def meeting_pipeline_path(scope_id: str) -> Path:
    """研发会议室主流程状态（按工单/会议 scope 缓存）。"""
    return scope_dir(scope_id) / "meeting_pipeline.json"


def archive_root(scope_id: str) -> Path:
    return scope_dir(scope_id) / "archive"


def agents_root(scope_id: str) -> Path:
    """工单维度的智能体沉淀根目录：``work/<scope>/agents/``。"""
    return scope_dir(scope_id) / "agents"


def agent_dir(scope_id: str, profile_id: str) -> Path:
    """单个智能体目录：``work/<scope>/agents/<profile_id>/``。

    ``profile_id`` 经 :func:`sanitize_work_order_segment` 规范化，避免越权写盘。
    """
    seg = sanitize_work_order_segment(profile_id or "default")
    return agents_root(scope_id) / seg


def agent_node_dir(scope_id: str, profile_id: str, node_id: str) -> Path:
    """智能体按节点分桶的目录：``.../<profile_id>/nodes/<node_id>/``。"""
    nseg = sanitize_work_order_segment(node_id or "pending")
    return agent_dir(scope_id, profile_id) / "nodes" / nseg


def is_work_order_directory(path: Path, *, work: Path | None = None) -> bool:
    root = work or work_root()
    if not path.is_dir():
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    name = path.name
    if name.startswith(".") or name in _SKIP_WORK_ROOT_NAMES:
        return False
    return True


def iter_work_order_directories() -> list[Path]:
    root = work_root()
    if not root.is_dir():
        return []
    dirs: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if is_work_order_directory(entry, work=root):
            dirs.append(entry)
    return dirs
