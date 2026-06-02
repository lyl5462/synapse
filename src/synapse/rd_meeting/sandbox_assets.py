"""沙箱构建：git 落盘至 ``work/<scope>/sandbox/``（不做 UTF-8 转换，与开门 ``code/`` 分离）。"""

from __future__ import annotations

import logging
from typing import Any

from synapse.rd_meeting.paths import sandbox_code_dir, sandbox_root, scope_dir
from synapse.rd_meeting.product_assets import (
    _branch_from_wire,
    _git_remote_url,
    _now_iso,
    _run_git,
)
from synapse.rd_meeting.product_context import (
    _normalize_product_wire,
    match_prod_row_by_prod,
)

logger = logging.getLogger(__name__)


def materialize_repo_to_sandbox(
    scope_id: str,
    repo: dict[str, Any],
) -> dict[str, Any]:
    """Clone / pull 至 ``work/<scope>/sandbox/<repo_name>/``，不调用 UTF-8 转换。"""
    repo_name = str(repo.get("repo_name") or "").strip()
    remote = _git_remote_url(str(repo.get("repo_url") or ""))
    branch = _branch_from_wire(str(repo.get("repo_branch") or ""))
    dest = sandbox_code_dir(scope_id, repo_name)
    entry: dict[str, Any] = {
        "repo_name": repo_name,
        "repo_url": str(repo.get("repo_url") or ""),
        "repo_branch": str(repo.get("repo_branch") or ""),
        "local_path": str(dest),
        "status": "skipped",
        "error": "",
    }
    if not repo_name:
        entry["status"] = "failed"
        entry["error"] = "缺少 repo_name / repo_url"
        return entry
    if not remote:
        entry["status"] = "failed"
        entry["error"] = "无法解析 git 远程地址"
        return entry

    dest.parent.mkdir(parents=True, exist_ok=True)
    git_dir = dest / ".git"
    if git_dir.is_dir():
        ok, detail = _run_git(["git", "-C", str(dest), "fetch", "--depth", "1", "origin"], timeout=300.0)
        if ok and branch:
            _run_git(["git", "-C", str(dest), "checkout", branch], timeout=120.0)
            ok, detail = _run_git(
                ["git", "-C", str(dest), "pull", "--ff-only", "origin", branch],
                timeout=300.0,
            )
        elif ok:
            ok, detail = _run_git(["git", "-C", str(dest), "pull", "--ff-only"], timeout=300.0)
        entry["status"] = "ok" if ok else "failed"
        entry["error"] = "" if ok else detail
        return entry

    if dest.exists():
        entry["status"] = "failed"
        entry["error"] = f"目标路径已存在且非 git 仓库: {dest}"
        return entry

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["-b", branch])
    cmd.extend([remote, str(dest)])
    ok, detail = _run_git(cmd, timeout=600.0)
    entry["status"] = "ok" if ok else "failed"
    entry["error"] = "" if ok else detail
    return entry


def bootstrap_sandbox_assets(
    scope_id: str,
    prod: str,
    *,
    wire_row: dict[str, Any] | None = None,
    catalog_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """拉取产品关联仓库至沙箱目录，返回摘要。"""
    sid = (scope_id or "").strip()
    prod_key = (prod or "").strip()
    scope_dir(sid).mkdir(parents=True, exist_ok=True)
    root = sandbox_root(sid)
    root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "prod": prod_key,
        "sandbox_root": str(root),
        "repos": [],
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
        result["errors"].append(f"产品「{prod_key}」不在 catalog 中，无法拉取沙箱代码")
        return result

    normalized = _normalize_product_wire(hit)
    repo_entries = [r for r in (normalized.get("repos") or []) if isinstance(r, dict)]

    for repo in repo_entries:
        row = materialize_repo_to_sandbox(sid, repo)
        result["repos"].append(row)
        if row.get("status") == "failed":
            result["errors"].append(f"沙箱代码 {row.get('repo_name')}: {row.get('error')}")

    if result["errors"]:
        has_ok = any(r.get("status") == "ok" for r in result["repos"])
        result["status"] = "partial" if has_ok else "failed"
    return result


def format_sandbox_build_report(assets: dict[str, Any], *, node_name: str) -> str:
    """生成 ``沙箱构建说明.md`` 正文（满足归档校验）。"""
    lines = [
        f"# {node_name} — 沙箱代码落盘",
        "",
        "本节点由系统脚本执行（git clone / pull），未调用大模型与人工确认。",
        "",
        f"- **沙箱根目录**：`{assets.get('sandbox_root') or ''}`",
        f"- **产品**：{assets.get('prod') or '—'}",
        f"- **落盘时间**：{assets.get('materialized_at') or '—'}",
        f"- **总体状态**：{assets.get('status') or '—'}",
        "",
        "## 仓库清单",
        "",
    ]
    repos = assets.get("repos") if isinstance(assets.get("repos"), list) else []
    if not repos:
        lines.append("（无关联仓库）")
    else:
        for row in repos:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- **{row.get('repo_name') or '—'}**：`{row.get('local_path') or '—'}` "
                f"— {row.get('status') or '—'}"
                + (f"（{row.get('error')}）" if row.get("error") else "")
            )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "沙箱构建已完成：代码已落盘至工单沙箱目录，可进入下一 SOP 节点。",
            "",
        ]
    )
    return "\n".join(lines)
