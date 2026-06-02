"""work/<scope_id>/ 路径与目录名规范化（对齐 setup-center rdWorkOrderPaths）。"""

from __future__ import annotations

import re
from pathlib import Path

from synapse.config import settings

MAX_SEGMENT_LEN = 120
_SKIP_WORK_ROOT_NAMES = frozenset({"userwork.json", "userwork.json.lock"})
# Windows / POSIX 路径非法字符（保留中文等 Unicode 目录名）
_FS_UNSAFE_SEGMENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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


def sanitize_fs_segment(raw: str, *, fallback: str = "default") -> str:
    """路径段规范化：保留中文等 Unicode，仅去掉文件系统非法字符。

    用于 ``doc_type``（如 ``产品架构``）、``repo_name`` 等可能含非 ASCII 的段。
    ``sanitize_work_order_segment`` 仅保留 ``[a-zA-Z0-9_-]``，会把中文滤成空串 → ``default``。
    """
    t = (raw or "").strip() or fallback
    base = t.replace("\\", "/").split("/")[-1] or t
    s = _FS_UNSAFE_SEGMENT_RE.sub("_", base)
    s = re.sub(r"_+", "_", s).strip("_").strip()
    if not s or s in (".", ".."):
        s = fallback
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


def room_history_path(scope_id: str, node_id: str = "pending") -> Path:
    """SOP 节点级协作流：``work/<scope>/agents/<node_id>/room_history.jsonl``。"""
    return agent_sop_node_dir(scope_id, node_id) / "room_history.jsonl"


def meeting_pipeline_path(scope_id: str) -> Path:
    """研发会议室主流程状态（按工单/会议 scope 缓存）。"""
    return scope_dir(scope_id) / "meeting_pipeline.json"


def archive_root(scope_id: str) -> Path:
    return scope_dir(scope_id) / "archive"


def archive_stage_segment(stage_name: str) -> str:
    """归档路径阶段段：``archive/<stage_name>/``（保留中文阶段名）。"""
    return sanitize_fs_segment(stage_name or "待处理", fallback="待处理")


def archive_node_dir(scope_id: str, stage_name: str, node_id: str) -> Path:
    """节点归档目录：``work/<scope>/archive/<stage_name>/<node_id>/``。"""
    stg = archive_stage_segment(stage_name)
    nid = (node_id or "pending").strip() or "pending"
    return archive_root(scope_id) / stg / nid


def product_code_root(scope_id: str) -> Path:
    """产品仓库代码根目录：``work/<scope>/code/``。"""
    return scope_dir(scope_id) / "code"


def product_code_dir(scope_id: str, repo_name: str) -> Path:
    """单仓库代码目录：``work/<scope>/code/<repo_name>/``。"""
    seg = sanitize_work_order_segment(repo_name or "default")
    return product_code_root(scope_id) / seg


def product_doc_root(scope_id: str) -> Path:
    """产品文档根目录：``work/<scope>/doc/``。"""
    return scope_dir(scope_id) / "doc"


def product_doc_dir(scope_id: str, doc_type: str) -> Path:
    """单类文档目录：``work/<scope>/doc/<doc_type>/``（保留中文 doc_type，如 ``产品架构``）。"""
    seg = sanitize_fs_segment(doc_type or "default")
    return product_doc_root(scope_id) / seg


def sandbox_root(scope_id: str) -> Path:
    """沙箱代码根目录：``work/<scope>/sandbox/``（系统节点落盘，与 ``code/`` 开门拉取分离）。"""
    return scope_dir(scope_id) / "sandbox"


def sandbox_code_dir(scope_id: str, repo_name: str) -> Path:
    """沙箱单仓库目录：``work/<scope>/sandbox/<repo_name>/``。"""
    seg = sanitize_work_order_segment(repo_name or "default")
    return sandbox_root(scope_id) / seg


def env_root(scope_id: str) -> Path:
    """环境预生成根目录：``work/<scope>/env/``。"""
    return scope_dir(scope_id) / "env"


def env_entropy_dir(scope_id: str) -> Path:
    """控熵文件落盘：``work/<scope>/env/entropy/``。"""
    return env_root(scope_id) / "entropy"


def env_doc_root(scope_id: str) -> Path:
    """环境预生成文档根目录：``work/<scope>/env/doc/``。"""
    return env_root(scope_id) / "doc"


def env_doc_dir(scope_id: str, doc_type: str) -> Path:
    """单类文档目录：``work/<scope>/env/doc/<doc_type>/``。"""
    seg = sanitize_fs_segment(doc_type or "default")
    return env_doc_root(scope_id) / seg


def agents_root(scope_id: str) -> Path:
    """工单维度的智能体沉淀根目录：``work/<scope>/agents/``。"""
    return scope_dir(scope_id) / "agents"


def agent_dir(scope_id: str, profile_id: str) -> Path:
    """Legacy 路径：``work/<scope>/agents/<profile_id>/``（仅兼容旧数据读取，新写入请用 :func:`agent_sop_profile_dir`）。"""
    seg = sanitize_work_order_segment(profile_id or "default")
    return agents_root(scope_id) / seg


def agent_node_dir(scope_id: str, profile_id: str, node_id: str) -> Path:
    """智能体节点目录（trace / conversation / meta）：``work/<scope>/agents/<node_id>/<profile_id>/``。"""
    return agent_sop_profile_dir(scope_id, node_id, profile_id)


def agent_sop_node_dir(scope_id: str, node_id: str) -> Path:
    """SOP 节点目录：``work/<scope>/agents/<node_id>/``。"""
    nseg = sanitize_work_order_segment(node_id or "pending")
    return agents_root(scope_id) / nseg


def agent_sop_profile_dir(scope_id: str, node_id: str, profile_id: str) -> Path:
    """智能体节点活动目录：``work/<scope>/agents/<node_id>/<profile_id>/``。"""
    pseg = sanitize_work_order_segment(profile_id or "default")
    return agent_sop_node_dir(scope_id, node_id) / pseg


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
