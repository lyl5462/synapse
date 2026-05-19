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
