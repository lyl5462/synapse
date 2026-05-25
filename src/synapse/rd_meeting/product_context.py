"""会议室产品定位：统一服务 get_prod_info → 匹配工单产品 → 会话缓存。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from synapse.api.routes.dev_iwhalecloud import _snapshot_norm_id
from synapse.rd_meeting.devservice import read_devservice_host, unified_service_base_url
from synapse.rd_meeting.paths import meeting_pipeline_path
from synapse.rd_meeting.room_runtime import read_json_file, write_json_file
from synapse.rd_meeting.userwork_sync import _scope_row

logger = logging.getLogger(__name__)

ScopeType = Literal["demand", "task"]


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
GET_PROD_INFO_PATH = "/dev/iwhalecloud/synapse/get_prod_info"


@dataclass(frozen=True)
class GetProdInfoResponse:
    """与前台 ``GetProdInfoResponse`` / ``rdUnifiedService.getProdInfo`` 一致。"""

    code: int
    message: str
    total: int
    data: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return self.code == 0


def _parse_unified_code(raw: Any) -> int:
    """将响应 ``code`` 规范为 int（与 TS ``number`` 比较一致）。"""
    if raw is None:
        return -1
    if isinstance(raw, bool):
        return 0 if raw else 1
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    try:
        return int(str(raw).strip())
    except ValueError:
        return -1


def parse_get_prod_info_response(body: Any) -> GetProdInfoResponse:
    """解析统一服务 JSON，规则对齐 ``ProductManager`` + ``getProdInfo``。"""
    if not isinstance(body, dict):
        return GetProdInfoResponse(-1, "invalid_response", 0, [])

    code = _parse_unified_code(body.get("code"))
    message = str(body.get("message") or "")
    total_raw = body.get("total")
    total = int(total_raw) if isinstance(total_raw, (int, float)) else 0

    raw_data = body.get("data")
    if isinstance(raw_data, list):
        rows = [x for x in raw_data if isinstance(x, dict)]
    else:
        rows = []

    return GetProdInfoResponse(code=code, message=message, total=total, data=rows)


def _version_display_code(version_raw: Any) -> str:
    """与前台 ``displayIdPipeName`` 一致：``id|code`` 取右侧 code。"""
    v = str(version_raw or "").strip()
    if not v:
        return ""
    if "|" in v:
        tail = v.split("|", 1)[-1].strip()
        return tail or v
    return v


def _version_matches_code(version_raw: Any, product_version_code: str) -> bool:
    """工单 ``product_version_code`` 与 get_prod_info 行的 ``version`` / ``prod`` 对齐。"""
    code = _snapshot_norm_id(product_version_code)
    if not code:
        return False
    v = _snapshot_norm_id(version_raw)
    if not v:
        return False
    if v == code:
        return True
    if _snapshot_norm_id(_version_display_code(version_raw)) == code:
        return True
    if "|" in v:
        for part in v.split("|"):
            if _snapshot_norm_id(part) == code:
                return True
    return False


def _prod_wire_matches_module_name(row: dict[str, Any], product_module_name: str) -> bool:
    """对齐 ``prodWireMatchesWorkItemModuleName``。"""
    mod_name = (product_module_name or "").strip()
    if not mod_name:
        return False
    m = str(row.get("module") or "").strip()
    if m == mod_name:
        return True
    if "|" in m and _version_display_code(m) == mod_name:
        return True
    repos_raw = row.get("repo_info")
    if not isinstance(repos_raw, list):
        return False
    for repo in repos_raw:
        if not isinstance(repo, dict):
            continue
        rm = str(repo.get("repo_module") or "").strip()
        if not rm:
            continue
        if rm == mod_name or _version_display_code(rm) == mod_name:
            return True
    return False


def _repo_name_from_url(repo_url: str) -> str:
    ru = (repo_url or "").strip()
    if not ru:
        return ""
    if "@@" in ru:
        return ru.split("@@", 1)[0].strip()
    if "/" in ru:
        tail = ru.rstrip("/").split("/")[-1]
        if tail.endswith(".git"):
            return tail[:-4]
        return tail
    return ru


def _normalize_repo_entry(raw: dict[str, Any]) -> dict[str, Any]:
    url = str(raw.get("repo_url") or "").strip()
    return {
        "repo_name": _repo_name_from_url(url),
        "repo_url": url,
        "repo_branch": str(raw.get("repo_branch") or "").strip(),
        "prod_branch": str(raw.get("prod_branch") or "").strip(),
        "repo_module": str(raw.get("repo_module") or "").strip(),
        "code_path": str(raw.get("code_path") or "").strip(),
        "repo_func": str(raw.get("repo_func") or "").strip(),
        "repo_master": str(raw.get("repo_master") or "").strip(),
    }


def _normalize_doc_entry(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_type": str(raw.get("doc_type") or "").strip(),
        "doc_process_state": str(raw.get("doc_process_state") or "").strip(),
        "doc_process_time": raw.get("doc_process_time"),
    }


def _normalize_product_wire(row: dict[str, Any]) -> dict[str, Any]:
    repos_raw = row.get("repo_info")
    repos: list[dict[str, Any]] = []
    if isinstance(repos_raw, list):
        for item in repos_raw:
            if isinstance(item, dict):
                repos.append(_normalize_repo_entry(item))
    docs_raw = row.get("doc_process")
    docs: list[dict[str, Any]] = []
    if isinstance(docs_raw, list):
        for item in docs_raw:
            if isinstance(item, dict):
                docs.append(_normalize_doc_entry(item))
    prod_feature = str(row.get("prod_feature") or row.get("function") or "").strip()
    return {
        "prod": str(row.get("prod") or "").strip(),
        "version": str(row.get("version") or "").strip(),
        "module": str(row.get("module") or "").strip(),
        "space": str(row.get("space") or "").strip(),
        "function": prod_feature,
        "prod_feature": prod_feature,
        "prod_desc": str(row.get("prod_desc") or "").strip(),
        "owner": str(row.get("owner") or "").strip(),
        "repos": repos,
        "docs": docs,
    }


def fetch_all_prod_info(*, timeout: float = 60.0) -> tuple[list[dict[str, Any]], str, str, GetProdInfoResponse | None]:
    """调用 get_prod_info。返回 (data, 错误码, 说明, 原始响应对象)。"""
    base = unified_service_base_url()
    if not base:
        return [], "missing_devservice_ip", "未配置 devservice.ip", None
    url = f"{base}{GET_PROD_INFO_PATH}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json={})
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        logger.warning("get_prod_info failed: %s", exc)
        return [], "fetch_failed", f"HTTP/网络异常: {exc}", None

    parsed = parse_get_prod_info_response(body)

    if not parsed.ok:
        detail = f"get_prod_info 失败: code={parsed.code}"
        if parsed.message:
            detail += f", message={parsed.message}"
        if parsed.data:
            detail += f"（另有 data 长度 {len(parsed.data)}，与前台契约不符：code 须为 0）"
        return [], "api_error", detail, parsed

    if not parsed.data:
        detail = "get_prod_info code=0 但 data 为空"
        if parsed.message:
            detail += f", message={parsed.message}"
        return [], "empty_data", detail, parsed

    if parsed.total != len(parsed.data):
        logger.info(
            "get_prod_info: total=%s != data.length=%s",
            parsed.total,
            len(parsed.data),
        )
    return parsed.data, "", parsed.message, parsed


def match_prod_row_by_prod(
    rows: list[dict[str, Any]],
    prod: str,
) -> dict[str, Any] | None:
    """用 userwork ``prod`` 与 get_prod_info 行的 ``prod`` 精确匹配（唯一键）。"""
    key = _snapshot_norm_id(prod)
    if not key:
        return None
    for row in rows:
        if _snapshot_norm_id(row.get("prod")) == key:
            return row
    return None


def load_prod_catalog_from_pipeline(scope_id: str) -> list[dict[str, Any]] | None:
    """读取 open_meeting 阶段缓存的产品全量列表。"""
    raw = read_json_file(meeting_pipeline_path((scope_id or "").strip()))
    if not isinstance(raw, dict):
        return None
    ctx = raw.get("context")
    if not isinstance(ctx, dict):
        return None
    catalog = ctx.get("prod_catalog")
    if not isinstance(catalog, list):
        return None
    return [x for x in catalog if isinstance(x, dict)]


def save_prod_catalog_to_pipeline(scope_id: str, rows: list[dict[str, Any]], *, selected_prod: str = "") -> None:
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
    ctx["prod_catalog"] = rows
    if selected_prod:
        ctx["selected_prod"] = selected_prod
    raw["context"] = ctx
    raw["updated_at"] = _now_iso()
    write_json_file(path, raw)


def ensure_prod_in_catalog(prod: str) -> tuple[list[dict[str, Any]], str]:
    """拉取 get_prod_info 并校验 ``prod`` 存在。返回 (rows, 错误说明)。"""
    key = (prod or "").strip()
    if not key:
        return [], "未指定产品 prod"
    rows, err, detail, _parsed = fetch_all_prod_info()
    if err:
        return [], detail or err
    if not match_prod_row_by_prod(rows, key):
        samples = [str(r.get("prod") or "").strip() for r in rows[:8] if r.get("prod")]
        return [], f"产品「{key}」不在统一服务产品列表中；示例: {', '.join(samples) or '（无）'}"
    return rows, ""


def save_product_session_cache(scope_id: str, cache: dict[str, Any]) -> None:
    """写入当前会议 scope 的 ``meeting_pipeline.json`` → ``context.product``。"""
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
    ctx["product"] = cache
    raw["context"] = ctx
    raw["updated_at"] = _now_iso()
    write_json_file(path, raw)


def load_product_session_cache(scope_id: str) -> dict[str, Any] | None:
    raw = read_json_file(meeting_pipeline_path((scope_id or "").strip()))
    if not isinstance(raw, dict):
        return None
    ctx = raw.get("context")
    if not isinstance(ctx, dict):
        return None
    product = ctx.get("product")
    return product if isinstance(product, dict) else None


def resolve_product_for_meeting(
    scope_type: ScopeType,
    scope_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """node_init：按 userwork ``prod`` 与 get_prod_info 的 ``prod`` 匹配产品。"""
    sid = (scope_id or "").strip()
    row = _scope_row(scope_type, sid) if sid else None  # type: ignore[arg-type]
    prod_key = str(row.get("prod") or "").strip() if row else ""

    system = {
        "synapse_url": unified_service_base_url(),
        "devservice_host": read_devservice_host() or "",
    }

    product: dict[str, Any] = {
        "locator_code": "pending",
        "locator_status": "产品定位中",
        "prod": prod_key,
    }

    if not prod_key:
        product["locator_code"] = "no_prod"
        product["locator_status"] = "工单缺少产品"
        product["locator_message"] = "userwork 无 prod，请先在一键开会时选择产品"
        return product, system

    rows = load_prod_catalog_from_pipeline(sid)
    parsed: GetProdInfoResponse | None = None
    if rows is None:
        rows, err, detail, parsed = fetch_all_prod_info()
        if err:
            product["locator_code"] = err
            product["locator_status"] = "产品查询失败"
            product["locator_message"] = detail or err
            if parsed is not None:
                product["api_code"] = parsed.code
                product["api_message"] = parsed.message
                product["api_total"] = parsed.total
            return product, system

    hit = match_prod_row_by_prod(rows, prod_key)
    if not hit:
        samples = [str(r.get("prod") or "").strip() for r in rows[:8] if r.get("prod")]
        product["locator_code"] = "not_matched"
        product["locator_status"] = "产品未匹配"
        product["locator_message"] = (
            f"userwork.prod={prod_key} 与产品列表无匹配；"
            f"示例 prod: {', '.join(samples) or '（无）'}"
        )
        product["prod_info_total"] = len(rows)
        save_product_session_cache(sid, {**product, "fetched_at": _now_iso()})
        return product, system

    normalized = _normalize_product_wire(hit)
    api_message = (parsed.message if parsed else "") or "产品查询成功"
    product = {
        "locator_code": "ok",
        "locator_status": "产品查询成功",
        "locator_message": api_message,
        "prod": prod_key,
        "api_code": 0,
        "api_total": parsed.total if parsed else len(rows),
        **normalized,
    }
    cache_payload = {
        "locator_code": "ok",
        "locator_status": "产品查询成功",
        "locator_message": api_message,
        "prod": prod_key,
        "matched_at": _now_iso(),
        "prod_info_total": parsed.total if parsed else len(rows),
        "api_response": {
            "code": parsed.code if parsed else 0,
            "message": parsed.message if parsed else "",
            "total": parsed.total if parsed else len(rows),
        },
        "wire": hit,
        **normalized,
    }
    save_product_session_cache(sid, cache_payload)

    from synapse.rd_meeting.product_assets import (
        assets_system_fields,
        enrich_product_with_assets,
        load_product_assets_from_pipeline,
    )

    assets = load_product_assets_from_pipeline(sid)
    product = enrich_product_with_assets(product, assets)
    system = {**system, **assets_system_fields(assets)}
    return product, system
