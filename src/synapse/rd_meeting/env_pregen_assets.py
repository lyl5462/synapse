"""环境预生成：文档落盘 + 控熵归档至 ``work/<scope>/env/``。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from synapse.rd_meeting.paths import (
    archive_node_dir,
    env_doc_dir,
    env_doc_root,
    env_entropy_dir,
    env_root,
    product_doc_root,
    scope_dir,
)
from synapse.rd_meeting.product_assets import (
    _materialize_doc,
    _now_iso,
)
from synapse.rd_meeting.product_context import (
    _normalize_product_wire,
    match_prod_row_by_prod,
)
from synapse.rd_sop.nodes import stage_name_for_id

logger = logging.getLogger(__name__)

_ENTROPY_SOURCE_NODE = "entropy_gen"
_ENTROPY_SOURCE_STAGE_ID = 2


def _copy_tree_files(src: Path, dest: Path) -> list[str]:
    """递归复制 ``src`` 下文件至 ``dest``，返回相对路径列表。"""
    copied: list[str] = []
    if not src.is_dir():
        return copied
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, target)
            copied.append(str(rel).replace("\\", "/"))
        except OSError as exc:
            logger.warning("env copy failed %s -> %s: %s", path, target, exc)
    return copied


def _materialize_doc_to_env(
    scope_id: str,
    prod: str,
    doc: dict[str, Any],
) -> dict[str, Any]:
    """拉取文档至 ``env/doc/<doc_type>/``。"""
    doc_type = str(doc.get("doc_type") or "").strip()
    entry = _materialize_doc(scope_id, prod, doc)
    if entry.get("status") != "ok":
        env_dest = env_doc_dir(scope_id, doc_type)
        entry["env_local_path"] = str(env_dest)
        return entry

    src_dir = Path(str(entry.get("local_path") or ""))
    env_dest = env_doc_dir(scope_id, doc_type)
    env_files = _copy_tree_files(src_dir, env_dest) if src_dir.is_dir() else []
    entry["env_local_path"] = str(env_dest)
    entry["env_files"] = env_files
    return entry


def _copy_entropy_from_archive(scope_id: str) -> dict[str, Any]:
    """从 ``archive/<需求设计>/entropy_gen/`` 复制控熵文件至 ``env/entropy/``。"""
    stage_name = stage_name_for_id(_ENTROPY_SOURCE_STAGE_ID)
    src = archive_node_dir(scope_id, stage_name, _ENTROPY_SOURCE_NODE)
    dest = env_entropy_dir(scope_id)
    entry: dict[str, Any] = {
        "source_dir": str(src),
        "local_path": str(dest),
        "files": [],
        "status": "skipped",
        "error": "",
    }
    if not src.is_dir():
        entry["error"] = f"控熵归档目录不存在: {src}"
        return entry
    files = _copy_tree_files(src, dest)
    if not files:
        entry["error"] = "控熵归档目录为空"
        return entry
    entry["files"] = files
    entry["status"] = "ok"
    return entry


def _copy_docs_from_product_root(scope_id: str) -> dict[str, Any]:
    """若开门已落盘 ``doc/``，同步复制至 ``env/doc/``（补充 get_doc 未就绪项）。"""
    src_root = product_doc_root(scope_id)
    dest_root = env_doc_root(scope_id)
    entry: dict[str, Any] = {
        "source_dir": str(src_root),
        "local_path": str(dest_root),
        "doc_types": [],
        "status": "skipped",
        "error": "",
    }
    if not src_root.is_dir():
        entry["error"] = "产品文档根目录不存在"
        return entry
    copied_types: list[str] = []
    for sub in sorted(src_root.iterdir()):
        if not sub.is_dir():
            continue
        dest = dest_root / sub.name
        files = _copy_tree_files(sub, dest)
        if files:
            copied_types.append(sub.name)
    if not copied_types:
        entry["error"] = "产品文档目录为空"
        return entry
    entry["doc_types"] = copied_types
    entry["status"] = "ok"
    return entry


def bootstrap_env_pregen(
    scope_id: str,
    prod: str,
    *,
    wire_row: dict[str, Any] | None = None,
    catalog_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """环境预生成：文档 + 控熵落盘至 ``work/<scope>/env/``。"""
    sid = (scope_id or "").strip()
    prod_key = (prod or "").strip()
    scope_dir(sid).mkdir(parents=True, exist_ok=True)
    root = env_root(sid)
    root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "prod": prod_key,
        "env_root": str(root),
        "docs": [],
        "entropy": {},
        "product_doc_mirror": {},
        "status": "ok",
        "errors": [],
        "materialized_at": _now_iso(),
    }

    if not sid or not prod_key:
        result["status"] = "failed"
        result["errors"].append("scope_id 或 prod 为空")
        return result

    hit = wire_row
    if hit is None and catalog_rows:
        hit = match_prod_row_by_prod(catalog_rows, prod_key)
    if hit is None:
        result["status"] = "failed"
        result["errors"].append(f"产品「{prod_key}」不在 catalog 中，无法拉取文档")
        return result

    normalized = _normalize_product_wire(hit)
    doc_entries = [d for d in (normalized.get("docs") or []) if isinstance(d, dict)]

    for doc in doc_entries:
        row = _materialize_doc_to_env(sid, prod_key, doc)
        result["docs"].append(row)
        if row.get("status") == "failed":
            result["errors"].append(f"文档 {row.get('doc_type')}: {row.get('error')}")

    mirror = _copy_docs_from_product_root(sid)
    result["product_doc_mirror"] = mirror
    if mirror.get("status") == "ok":
        pass  # 补充复制，不计入 errors

    entropy = _copy_entropy_from_archive(sid)
    result["entropy"] = entropy
    if entropy.get("status") != "ok":
        result["errors"].append(f"控熵: {entropy.get('error')}")

    has_doc_ok = any(d.get("status") == "ok" for d in result["docs"])
    has_entropy_ok = entropy.get("status") == "ok"
    has_mirror_ok = mirror.get("status") == "ok"

    if result["errors"]:
        if has_doc_ok or has_entropy_ok or has_mirror_ok:
            result["status"] = "partial"
        else:
            result["status"] = "failed"
    return result


def format_env_pregen_report(assets: dict[str, Any], *, node_name: str) -> str:
    """生成 ``环境预生成报告.md`` 正文。"""
    lines = [
        f"# {node_name} — 环境预生成",
        "",
        "本节点由系统脚本执行（文档拉取 + 控熵归档），未调用大模型与人工确认。",
        "",
        f"- **环境根目录**：`{assets.get('env_root') or ''}`",
        f"- **产品**：{assets.get('prod') or '—'}",
        f"- **落盘时间**：{assets.get('materialized_at') or '—'}",
        f"- **总体状态**：{assets.get('status') or '—'}",
        "",
        "## 文档",
        "",
    ]
    docs = assets.get("docs") if isinstance(assets.get("docs"), list) else []
    if not docs:
        lines.append("（无 catalog 文档项）")
    else:
        for row in docs:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- **{row.get('doc_type') or '—'}**：`{row.get('env_local_path') or row.get('local_path') or '—'}` "
                f"— {row.get('status') or '—'}"
                + (f"（{row.get('error')}）" if row.get("error") else "")
            )

    mirror = assets.get("product_doc_mirror") if isinstance(assets.get("product_doc_mirror"), dict) else {}
    if mirror.get("status") == "ok":
        types = mirror.get("doc_types") or []
        lines.extend(["", f"- **开门文档镜像**：`{mirror.get('local_path') or ''}`（{len(types)} 类）"])

    entropy = assets.get("entropy") if isinstance(assets.get("entropy"), dict) else {}
    lines.extend(["", "## 控熵文件", ""])
    if entropy.get("status") == "ok":
        files = entropy.get("files") or []
        lines.append(f"- **目录**：`{entropy.get('local_path') or ''}`")
        lines.append(f"- **文件数**：{len(files)}")
        for name in files[:20]:
            lines.append(f"  - `{name}`")
        if len(files) > 20:
            lines.append(f"  - …共 {len(files)} 个文件")
    else:
        lines.append(f"（{entropy.get('error') or '未复制'}）")

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "环境预生成已完成：文档与控熵已归档至工单 env 目录，可进入下一 SOP 节点。",
            "",
        ]
    )
    return "\n".join(lines)
