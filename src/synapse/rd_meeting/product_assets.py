"""会议室开门：落盘产品代码（git）与文档（统一服务 get_doc）。

目录约定（与 ``paths`` 一致）::

    work/<scope>/code/<repo_name>/   # git clone
    work/<scope>/doc/<doc_type>/      # get_doc 落盘
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

from synapse.rd_meeting.convert_to_utf8 import convert_directory_to_utf8
from synapse.rd_meeting.devservice import read_devservice_host, unified_service_base_url
from synapse.rd_meeting.paths import (
    meeting_pipeline_path,
    product_code_dir,
    product_code_root,
    product_doc_dir,
    product_doc_root,
    scope_dir,
)
from synapse.rd_meeting.product_context import (
    _normalize_product_wire,
    _repo_name_from_url,
    match_prod_row_by_prod,
)
from synapse.rd_meeting.room_runtime import read_json_file, write_json_file

logger = logging.getLogger(__name__)

GET_DOC_PATH = "/dev/iwhalecloud/synapse/get_doc"
_DOC_DONE_STATE = frozenset({"D", "d"})


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _safe_filename(name: str) -> str:
    base = (name or "").strip() or "document.md"
    return re.sub(r'[<>:"/\\|?*]', "_", base)


def _branch_from_wire(repo_branch: str) -> str:
    """``branchVersionId|branchName`` → 分支名。"""
    v = (repo_branch or "").strip()
    if not v:
        return ""
    if "|" in v:
        tail = v.split("|", 1)[-1].strip()
        return tail or v
    return v


def _git_remote_url(repo_url: str) -> str:
    """解析可 clone 的远程 URL（兼容 ``name@@https://...``）。"""
    ru = (repo_url or "").strip()
    if not ru:
        return ""
    if "@@" in ru:
        left, right = ru.split("@@", 1)
        right = right.strip()
        if right.startswith("http") or right.startswith("git@"):
            return right
        if left.startswith("http") or left.startswith("git@"):
            return left.strip()
    return ru


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: float = 600.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "git 命令超时"
    except FileNotFoundError:
        return False, "未找到 git 可执行文件"
    except OSError as exc:
        return False, str(exc)
    out = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        return False, out or f"exit {proc.returncode}"
    return True, out


def _convert_repo_to_utf8(dest: Path) -> None:
    """git 落盘后将仓库内文本文件统一转为 UTF-8（失败仅记日志，不影响落盘状态）。"""
    try:
        result = convert_directory_to_utf8(dest)
    except Exception as exc:
        logger.warning("repo utf8 convert failed for %s: %s", dest, exc)
        return
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    converted = int(stats.get("converted") or 0)
    errors = int(stats.get("error") or 0)
    if converted or errors:
        logger.info(
            "repo utf8 convert %s: converted=%s already_utf8=%s skip_binary=%s errors=%s",
            dest,
            converted,
            stats.get("already_utf8", 0),
            stats.get("skip_binary", 0),
            errors,
        )
    for rel, msg in (result.get("errors") or [])[:5]:
        logger.warning("repo utf8 convert file failed %s/%s: %s", dest, rel, msg)


def _materialize_repo(
    scope_id: str,
    repo: dict[str, Any],
) -> dict[str, Any]:
    repo_name = str(repo.get("repo_name") or "").strip() or _repo_name_from_url(str(repo.get("repo_url") or ""))
    remote = _git_remote_url(str(repo.get("repo_url") or ""))
    branch = _branch_from_wire(str(repo.get("repo_branch") or ""))
    dest = product_code_dir(scope_id, repo_name)
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
            _run_git(["git", "-C", str(dest), "pull", "--ff-only", "origin", branch], timeout=300.0)
        elif ok:
            _run_git(["git", "-C", str(dest), "pull", "--ff-only"], timeout=300.0)
        entry["status"] = "ok" if ok else "failed"
        entry["error"] = "" if ok else detail
        if ok:
            _convert_repo_to_utf8(dest)
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
    if ok:
        _convert_repo_to_utf8(dest)
    return entry


def _parse_get_doc_response(body: Any) -> tuple[int, str, list[dict[str, str]]]:
    if not isinstance(body, dict):
        return -1, "invalid_response", []
    code_raw = body.get("code")
    try:
        code = int(code_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        code = -1
    message = str(body.get("message") or "")
    data = body.get("data")
    if not isinstance(data, dict):
        return code, message, []
    raw_docs = data.get("doc_content")
    if not isinstance(raw_docs, list):
        return code, message, []
    out: list[dict[str, str]] = []
    for row in raw_docs:
        if not isinstance(row, dict):
            continue
        name = str(row.get("doc_name") or "").strip() or "document.md"
        content = str(row.get("content") or "")
        out.append({"doc_name": name, "content": content})
    return code, message, out


def fetch_prod_doc(prod: str, doc_type: str, *, timeout: float = 120.0) -> tuple[list[dict[str, str]], str]:
    """调用统一服务 get_doc。返回 (doc_content, 错误说明)。"""
    base = unified_service_base_url()
    if not base:
        return [], "未配置 devservice.ip"
    url = f"{base}{GET_DOC_PATH}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json={"prod": prod, "doc_type": doc_type})
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        logger.warning("get_doc failed prod=%s doc_type=%s: %s", prod, doc_type, exc)
        return [], f"HTTP/网络异常: {exc}"

    code, message, docs = _parse_get_doc_response(body)
    if code != 0:
        return [], message or f"get_doc code={code}"
    return docs, ""


def _materialize_doc(
    scope_id: str,
    prod: str,
    doc: dict[str, Any],
) -> dict[str, Any]:
    doc_type = str(doc.get("doc_type") or "").strip()
    state = str(doc.get("doc_process_state") or "").strip()
    dest = product_doc_dir(scope_id, doc_type)
    entry: dict[str, Any] = {
        "doc_type": doc_type,
        "doc_process_state": state,
        "local_path": str(dest),
        "files": [],
        "status": "skipped",
        "error": "",
    }
    if not doc_type:
        entry["status"] = "failed"
        entry["error"] = "缺少 doc_type"
        return entry
    if state not in _DOC_DONE_STATE:
        entry["error"] = f"文档未就绪（doc_process_state={state or '空'}，仅 D 可拉取正文）"
        return entry

    docs, err = fetch_prod_doc(prod, doc_type)
    if err:
        entry["status"] = "failed"
        entry["error"] = err
        return entry
    if not docs:
        entry["status"] = "failed"
        entry["error"] = "get_doc 返回空 doc_content"
        return entry

    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for row in docs:
        fname = _safe_filename(row.get("doc_name") or "document.md")
        path = dest / fname
        try:
            path.write_text(str(row.get("content") or ""), encoding="utf-8")
            written.append(fname)
        except OSError as exc:
            entry["status"] = "failed"
            entry["error"] = f"写入 {path} 失败: {exc}"
            entry["files"] = written
            return entry
    entry["files"] = written
    entry["status"] = "ok"
    return entry


def bootstrap_product_assets(
    scope_id: str,
    prod: str,
    *,
    wire_row: dict[str, Any] | None = None,
    catalog_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """拉取并落盘产品代码与文档，返回摘要（写入 pipeline context）。"""
    sid = (scope_id or "").strip()
    prod_key = (prod or "").strip()
    scope_dir(sid).mkdir(parents=True, exist_ok=True)
    code_root = product_code_root(sid)
    doc_root = product_doc_root(sid)
    code_root.mkdir(parents=True, exist_ok=True)
    doc_root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "prod": prod_key,
        "work_order_dir": str(scope_dir(sid)),
        "code_root": str(code_root),
        "doc_root": str(doc_root),
        "repos": [],
        "docs": [],
        "status": "ok",
        "errors": [],
        "materialized_at": _now_iso(),
        "devservice_host": read_devservice_host() or "",
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
        result["errors"].append(f"产品「{prod_key}」不在 catalog 中，无法落盘资产")
        return result

    normalized = _normalize_product_wire(hit)
    repo_entries = [r for r in (normalized.get("repos") or []) if isinstance(r, dict)]
    doc_entries = [d for d in (normalized.get("docs") or []) if isinstance(d, dict)]

    for repo in repo_entries:
        if not isinstance(repo, dict):
            continue
        row = _materialize_repo(sid, repo)
        result["repos"].append(row)
        if row.get("status") == "failed":
            result["errors"].append(f"代码 {row.get('repo_name')}: {row.get('error')}")

    for doc in doc_entries:
        if not isinstance(doc, dict):
            continue
        row = _materialize_doc(sid, prod_key, doc)
        result["docs"].append(row)
        if row.get("status") == "failed":
            result["errors"].append(f"文档 {row.get('doc_type')}: {row.get('error')}")

    if result["errors"]:
        has_ok = any(r.get("status") == "ok" for r in result["repos"]) or any(
            d.get("status") == "ok" for d in result["docs"]
        )
        result["status"] = "partial" if has_ok else "failed"
    return result


def save_product_assets_to_pipeline(scope_id: str, assets: dict[str, Any]) -> None:
    sid = (scope_id or "").strip()
    if not sid:
        return
    path = meeting_pipeline_path(sid)
    raw = read_json_file(path)
    if not isinstance(raw, dict):
        return
    ctx = raw.get("context")
    if not isinstance(ctx, dict):
        ctx = {}
    ctx["product_assets"] = assets
    raw["context"] = ctx
    raw["updated_at"] = _now_iso()
    write_json_file(path, raw)


def load_product_assets_from_pipeline(scope_id: str) -> dict[str, Any] | None:
    raw = read_json_file(meeting_pipeline_path((scope_id or "").strip()))
    if not isinstance(raw, dict):
        return None
    ctx = raw.get("context")
    if not isinstance(ctx, dict):
        return None
    assets = ctx.get("product_assets")
    return assets if isinstance(assets, dict) else None


def enrich_product_with_assets(product: dict[str, Any], assets: dict[str, Any] | None) -> dict[str, Any]:
    """将落盘路径合并进 product / system 段供 prompt 使用。"""
    if not assets:
        return product
    out = dict(product)
    out["work_order_dir"] = str(assets.get("work_order_dir") or "")
    out["code_root"] = str(assets.get("code_root") or "")
    out["doc_root"] = str(assets.get("doc_root") or "")
    out["assets_status"] = str(assets.get("status") or "")

    repo_by_name = {
        str(r.get("repo_name") or ""): r for r in (assets.get("repos") or []) if isinstance(r, dict)
    }
    repos_out: list[dict[str, Any]] = []
    source_repos = out.get("repos") or []
    if not source_repos and repo_by_name:
        source_repos = list(repo_by_name.values())
    for r in source_repos:
        if not isinstance(r, dict):
            continue
        merged = dict(r)
        hit = repo_by_name.get(str(r.get("repo_name") or ""))
        if hit:
            merged["local_path"] = hit.get("local_path")
            merged["materialize_status"] = hit.get("status")
        repos_out.append(merged)
    if repos_out:
        out["repos"] = repos_out

    doc_by_type = {
        str(d.get("doc_type") or ""): d for d in (assets.get("docs") or []) if isinstance(d, dict)
    }
    docs_out: list[dict[str, Any]] = []
    source_docs = out.get("docs") or []
    if not source_docs and doc_by_type:
        source_docs = list(doc_by_type.values())
    for d in source_docs:
        if not isinstance(d, dict):
            continue
        merged = dict(d)
        hit = doc_by_type.get(str(d.get("doc_type") or ""))
        if hit:
            merged["local_path"] = hit.get("local_path")
            merged["files"] = hit.get("files") or []
            merged["materialize_status"] = hit.get("status")
        docs_out.append(merged)
    if docs_out:
        out["docs"] = docs_out
    return out


def assets_system_fields(assets: dict[str, Any] | None) -> dict[str, str]:
    """供 init_context system 段注入的路径键值。"""
    if not assets:
        return {}
    fields: dict[str, str] = {}
    wo = str(assets.get("work_order_dir") or "").strip()
    if wo:
        fields["work_order_dir"] = wo
    code_root = str(assets.get("code_root") or "").strip()
    if code_root:
        fields["product_code_root"] = code_root
    doc_root = str(assets.get("doc_root") or "").strip()
    if doc_root:
        fields["product_doc_root"] = doc_root
    return fields
