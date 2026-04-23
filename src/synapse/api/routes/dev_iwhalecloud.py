from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Tuple

import httpx
from fastapi import APIRouter, Body, Request
from fastapi.background import P
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from synapse.api.schemas import error_response, success_response
from synapse.config import settings

from playwright.sync_api import FrameLocator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


logger = logging.getLogger(__name__)

router = APIRouter()

DEV_IWHALECLOUD_BASE_URL = "https://dev.iwhalecloud.com"  # 研发云地址
DEV_IWHALECLOUD_PRODUCT_ANALYZE_URL = ""

# Playwright 默认超时 30000ms；login 使用 networkidle，易触发超时，故单独放宽（毫秒）
DEV_IWHALECLOUD_LOGIN_PLAYWRIGHT_TIMEOUT_MS = 300_000  # 5 分钟
# 研发云 API 的 Authorization 从 userinfo.encryption 的 token 读取
# DEV_IWHALECLOUD_PROJECT_SAPCE_ID = 562722  # xmjfbss 项目空间ID
# DEV_IWHALECLOUD_ONLINE_PROJECT_ID = 162423 # 在线项目ID [162423]国内-BSS-2026-在线研发-计费-计费账务电信域在线研发项目
# DEV_IWHALECLOUD_CONTRACT_PROJECT_ID = 161616 # 合同项目ID [161616]中国电信2026年北京公司计费中心平台升级研发工程

# 需求单各环节状态ID
DEV_IWHALECLOUD_DEMAND_STAGE_START = 3913 # 需求单-待处理
DEV_IWHALECLOUD_DEMAND_STAGE_AUDIT = 16959 # 需求评审
DEV_IWHALECLOUD_DEMAND_STAGE_CHANGINIG_AUDIT = 72609 # 需求变更评审
DEV_IWHALECLOUD_DEMAND_STAGE_DESIGNING = 10929 # 需求设计
DEV_IWHALECLOUD_DEMAND_STAGE_DEVELOPING = 3914 # 需求开发
DEV_IWHALECLOUD_DEMAND_STAGE_TESTING = 3916 # 需求测试
DEV_IWHALECLOUD_DEMAND_STAGE_TO_CREATOR = 45058 # To Creator
DEV_IWHALECLOUD_DEMAND_STAGE_FINISH = 3915 # 已关闭

# 研发单各环节状态ID
DEV_IWHALECLOUD_TASK_STAGE_START = 3917 # 待处理
DEV_IWHALECLOUD_TASK_STAGE_DESIGNING = 3918 # 设计中
DEV_IWHALECLOUD_TASK_STAGE_DEVELOPING = 3919 # 开发中
DEV_IWHALECLOUD_TASK_STAGE_CODE_AUDIT = 16960 # 代码走查
DEV_IWHALECLOUD_TASK_STAGE_TO_CREATOR = 45059 # To Creator
DEV_IWHALECLOUD_TASK_STAGE_ABNORMAL_CLOSE_AUDIT = 46082 # 异常关闭审核

# 日志打印响应体最大长度
_LOG_HTTPS_RESP_BODY_MAX = 8000


def _load_dev_iwhalecloud_authorization() -> str:
    """研发云 HTTP API 的 Authorization，与 userinfo.encryption 解密后的 token 字段一致。"""
    data = _load_userinfo_plain()
    if not data:
        raise FileNotFoundError(
            f"未找到本地 userinfo：{_userinfo_encryption_path()}，请先调用 /api/dev/iwhalecloud/login 完成引导"
        )
    token = (data.get("token") or "").strip()
    if not token:
        raise ValueError(
            "userinfo 中缺少 token（即研发云 API 的 Authorization），请先完成登录或更新密文"
        )
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def _userinfo_encryption_path() -> Path:
    """浩鲸研发云本地用户信息（姓名、工号、密码、token），CryptHelper 加密存储。"""
    return settings.project_root / "data" / "userinfo.encryption"

def _dev_iwhalecloud_session_path() -> Path:
    """独立的研发云 token 和 cookies 缓存文件。"""
    return settings.project_root / "data" / "iwhalecloud_session.json"

def _load_iwhalecloud_session() -> dict | None:
    path = _dev_iwhalecloud_session_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

def _save_iwhalecloud_session(token: str, cookies: str) -> None:
    path = _dev_iwhalecloud_session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token, "cookies": cookies}, ensure_ascii=False), encoding="utf-8")


def _clear_iwhalecloud_session() -> None:
    """删除门户会话缓存（x-csrf-token + Cookie）；过期或鉴权失败时调用。"""
    path = _dev_iwhalecloud_session_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError as e:
        logger.warning("清理 iwhalecloud_session 失败: %s", e)


def _portal_response_needs_session_refresh(resp: httpx.Response) -> bool:
    """HTTP 层判定门户 Cookie/CSRF 失效，需删缓存并重拉。"""
    return resp.status_code in (401, 403)


def _devservice_ip_path() -> Path:
    """产品公共服务主机地址（纯文本一行 IP 或主机名）。

    固定为 Synapse 用户根目录下 `devservice.ip`（与 Tauri `synapse_root_dir()/devservice.ip` 一致，如 ~/.synapse/devservice.ip）。
    """
    return settings.synapse_home / "devservice.ip"


def _devservice_ip_path_legacy() -> Path:
    """旧版路径：project_root/data/devservice.ip（仅读取回退）。"""
    return settings.project_root / "data" / "devservice.ip"


DEVSERVICE_PROBE_PORTS: tuple[int, ...] = (10001, 11001, 11011, 12001, 12011, 13001, 13011)


def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as e:
        return False, str(e)


def _crypt_helper():
    from foundation.helper.CryptHelper import CryptHelper

    return CryptHelper()


def _load_userinfo_plain() -> dict | None:
    path = _userinfo_encryption_path()
    if not path.is_file():
        return None
    crypt_helper = _crypt_helper()
    enc = path.read_text(encoding="utf-8").strip()
    if not enc:
        return None
    # 避免在 FastAPI 线程池内触发 foundation LogHelper（signal 仅主线程可用）
    plain = crypt_helper.decrypt(enc, False)
    if plain is None:
        logger.error("解密 userinfo.encryption 失败")
        raise ValueError("解密 userinfo.encryption 失败")
    try:
        return json.loads(plain)
    except json.JSONDecodeError:
        logger.exception("userinfo.encryption 解密后不是合法 JSON")
        raise ValueError("userinfo.encryption 解密后不是合法 JSON") from None


def _save_userinfo_encrypted(
    *, name: str, employee_id: str, password: str, token: str, user_id: int = None
) -> tuple[bool, str]:
    crypt_helper = _crypt_helper()
    payload = {
        "name": name,
        "employee_id": employee_id,
        "password": password,
        "token": token,
        "userId": user_id,
    }
    raw = json.dumps(payload, ensure_ascii=False)
    enc = crypt_helper.encrypt(raw, False)
    if enc is None:
        return False, "加密用户信息失败"
    path = _userinfo_encryption_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(enc, encoding="utf-8")
    return True, ""


def _forward_response(resp: httpx.Response) -> dict:
    """统一处理上游响应，返回与 yuque 路由一致的 envelope。"""
    if resp.status_code < 400:
        try:
            data = resp.json()
        except ValueError:
            return error_response(502, f"研发云返回非 JSON：{resp.text}")

        # 研发云业务执行结果：code == "9999" 表示成功
        if isinstance(data, dict) and "code" in data:
            if data.get("code") != "9999":
                msg = data.get("finalMessage") or data.get("msg") or data.get("message") or "研发云执行失败"
                return error_response(502, f"{msg}", error=str(data))

        return success_response(data)

    return error_response(resp.status_code, f"研发云接口调用失败：{resp.text}")


def _headers(content_type: str | None = "application/json") -> dict:
    h = {"Authorization": _load_dev_iwhalecloud_authorization()}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _log_httpx_response(operation: str, resp: httpx.Response) -> None:
    """Debug：打印 httpx 响应（状态码、URL、正文；正文过长则截断）。"""
    text = resp.text
    if len(text) > _LOG_HTTPS_RESP_BODY_MAX:
        text = text[:_LOG_HTTPS_RESP_BODY_MAX] + f"...(truncated, total_len={len(resp.text)})"
    logger.debug("%s httpx resp status=%s url=%s body=%s", operation, resp.status_code, resp.url, text)


class GetProjectListRequest(BaseModel):
    keyword: str = Field("", description="项目关键字，可选；非空时作为查询参数 keyword")
    # x-csrf-token / Cookie 从服务端 data/iwhalecloud_session.json 读取，勿在请求体传递


def _build_get_project_list_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "RrvUefaMDHJF",
        "app-signature": "7c4f3c0de0468554fd4ebbff034c1c3e148ac47079315207d5cff584434228c3",
        "app-timestamp": "1774776513241",
        "menu-id": "auto-987976ee68c07d22",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_project_list")
async def get_project_list(body: GetProjectListRequest) -> dict:
    """
    功能：获取项目空间列表。
    用法：传入关键字keyword，进行全局检索，获取项目空间列表。
    接口类型：研发云界面抓取请求（项目 --> 项目检索）
    返回数据格式：[
        {
            "projectId": 123,
            "projectName": "项目空间名称",
            "projectCode": "项目空间编码",
        }
    ]
    转调：GET /portal/zcm-cmdb/v1/projects/all，无返回码，直接返回数据
    """
    return await _get_project_list(body)

async def _get_project_list(body: GetProjectListRequest) -> dict:
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-cmdb/v1/projects/all"
    params: dict[str, str | int] = {"_": int(datetime.now().timestamp() * 1000)}
    kw = (body.keyword or "").strip()
    if kw:
        params["keyword"] = kw

    logger.debug("get_project_list url:%s params:%s", url, params)
    resp: httpx.Response | None = None
    for attempt in range(2):
        try:
            csrf, cookies = await _ensure_valid_creds_async(force_refresh=(attempt > 0))
        except ValueError as e:
            return error_response(400, str(e))
        headers = _build_get_project_list_headers(csrf, cookies)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers, params=params)
                _log_httpx_response("get_project_list", resp)
        except httpx.RequestError as exc:
            logger.exception("调用研发云获取项目列表接口异常: %s", exc)
            return error_response(503, f"调用研发云接口异常: {exc}")
        if attempt == 0 and _portal_response_needs_session_refresh(resp):
            _clear_iwhalecloud_session()
            continue
        break
    assert resp is not None

    # 检查数据格式
    try:
        raw = resp.json()
        if not isinstance(raw, list):
            return error_response(502, f"研发云返回数据非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")

    # 提取数据
    simplified = [
        {
            "projectId": it.get("projectId"),
            "projectName": it.get("projectName"),
            "projectCode": it.get("projectCode"),
        }
        for it in raw
    ]
    return success_response(simplified)


class GetProductListRequest(BaseModel):
    productNameSearch: str = Field("/", description="产品名称搜索")

@router.post("/api/dev/iwhalecloud/get_product_list")
async def get_product_list(body: GetProductListRequest) -> dict:
    """对外路由：获取产品列表，支持传入产品名模糊匹配，默认获取全量列表（内部复用 _get_product_list）。
    功能：获取产品列表。
    用法：传入产品名称productNameSearch，进行模糊匹配，获取产品列表。
    接口类型：研发云提供标准API接口
    返回数据格式：[
        {
            "productId": 123,
            "productName": "产品名称",
            "productCode": "产品编码",
        }
    ]
    转调：POST /portal/ai-gateway/devspace/rpc/v3/master-data/product-list，返回码code为“9999”表示成功
    """
    return await _get_product_list(body)
    
async def _get_product_list(body: GetProductListRequest) -> dict: 
    """
    内部调用：获取产品列表，支持传入产品名模糊匹配，默认获取全量列表。
    转调：POST /portal/ai-gateway/devspace/rpc/v3/master-data/product-list
    """
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/master-data/product-list"
    payload = {
        "productNameSearch": body.productNameSearch,
        "minMatchLength": 0,
    }
    logger.debug("get_product_list url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("get_product_list", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取产品列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    
    # 检查数据格式
    try:
        raw = resp.json()

        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"研发云获取产品列表失败：{msg}")

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")

    # 提取数据
    simplified = [
        {
            "productId": it.get("productId"),
            "productName": it.get("productName")
        }
        for it in raw.get("data")
    ]

    return success_response(simplified)


class GetRepoDetailRequest(BaseModel):
    userId: int = Field(..., description="用户ID")
    isSuper: bool = Field(False, description="是否超管，默认false")
    projectId: int = Field(..., description="项目空间ID")
    isRecursion: bool = Field(True, description="是否递归，默认true")
    moduleId: int = Field(..., description="应用模块ID（必填）")
    repoNameKeyWord: str = Field("", description="仓库名称关键字（可选）")
    state: str = Field("", description="状态筛选（可选）")
    branchVersionIdList: list[int] = Field(default_factory=list, description="分支版本ID列表（可选）")
    productVersionIdList: list[int] = Field(default_factory=list, description="产品版本ID列表（可选）")
    typeIdList: list[int] = Field(default_factory=list, description="类型ID列表（可选）")


def _build_get_repo_detail_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "yknMgRosoTCR",
        "app-signature": "fe4b9f2fc31b43a8af11108acaac242621cf5084ee3d2506fc9842e7882ea602",
        "app-timestamp": "1775726087151",
        "content-type": "application/json",
        "menu-id": "auto-4ed35e937ba17406",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

def _build_get_repo_detail_payload(body: GetRepoDetailRequest) -> dict:
    return {
        "state": body.state,
        "branchVersionIdList": body.branchVersionIdList,
        "productVersionIdList": body.productVersionIdList,
        "typeIdList": body.typeIdList,
        "moduleIdList": [body.moduleId],
        "repoNameKeyWord": body.repoNameKeyWord,
    }

@router.post("/api/dev/iwhalecloud/get_repo_detail")
async def get_repo_detail(body: GetRepoDetailRequest) -> dict:
    """
    功能：获取代码仓库信息。
    用法：传入项目空间ID、应用模块ID、仓库名称关键字、状态筛选、分支版本ID列表、产品版本ID列表、类型ID列表，获取代码仓库信息。
    接口类型：研发云界面抓取请求（研发平台 --> 仓库管理）
    返回数据格式：[
        {
            "repoName": "仓库名称",
            "repoUrl": "仓库URL",
            "defaultBranch": "默认分支",
        }
    ]
    转调：POST /portal/zcm-devspace/gitea-repo/catalog/-1/repos，返回码code为“9999”表示成功
    """
    return await _get_repo_detail(body)

async def _get_repo_detail(body: GetRepoDetailRequest) -> dict:
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))
    if not body.moduleId:
        return error_response(400, "moduleId 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/gitea-repo/catalog/-1/repos"
    params: dict[str, str | int] = {
        "userId": body.userId,
        "isSuper": "true" if body.isSuper else "false",
        "projectId": body.projectId,
        "isRecursion": "true" if body.isRecursion else "false",
    }
    headers = _build_get_repo_detail_headers(csrf, cookies)
    payload = _build_get_repo_detail_payload(body)

    logger.debug("get_repo_detail url:%s params:%s payload:%s", url, params, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            _log_httpx_response("get_repo_detail", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取代码仓库信息接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云获取代码仓库信息失败：{resp.text}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取代码仓库信息失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取代码仓库信息返回非 JSON：{resp.text}")

    # 提取数据
    simplified = [
        {
            "repoName": it.get("gitRepoDto").get("repoName"),
            "repoUrl": it.get("gitRepoDto").get("repoUrl"),
            "defaultBranch": it.get("gitRepoDto").get("defaultBranch"),
        }
        for it in raw.get("data")
    ]

    return success_response(simplified)


def _repo_ids_equal(a: object, b: object) -> bool:
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return a == b


def _dest_branch_name_from_git_rows(
    second_data: list,
    repository_id: object,
    branch_name: object,
) -> object:
    """在第二接口 data 中按 productModuleDto.repoId 对齐，再在 adBranchVersionGitList 中按 sourceBranchName 取 destBranchName。"""
    for row2 in second_data:
        if not isinstance(row2, dict):
            continue
        pmd = row2.get("productModuleDto")
        if not isinstance(pmd, dict):
            continue
        if not _repo_ids_equal(pmd.get("repoId"), repository_id):
            continue
        git_list = row2.get("adBranchVersionGitList")
        if not isinstance(git_list, list):
            return branch_name
        for g in git_list:
            if not isinstance(g, dict):
                continue
            if g.get("sourceBranchName") != branch_name:
                continue
            dest = g.get("destBranchName")
            return dest if dest is not None else branch_name
        return branch_name
    return branch_name


class GetRepoDetailByProdBranchRequest(BaseModel):
    prod_branch: int = Field(..., description="产品分支版本 ID（对应上游路径中的分支 ID）")
    projectId: int = Field(..., description="项目空间 ID")


def _build_get_repo_detail_by_prod_branch_headers(
    _body: GetRepoDetailByProdBranchRequest, csrf: str, cookies: str
) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "A0AilsWu42pf",
        "app-signature": "c50bf7baa5299c97945c8b018e6f857b333b3cd490432acbc9b8e3a8bab02a1c",
        "app-timestamp": "1773919980126",
        "menu-id": "auto-5e9475286a215757",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }


@router.post("/api/dev/iwhalecloud/get_repo_detail_by_prod_branch")
async def get_repo_detail_by_prod_branch(body: GetRepoDetailByProdBranchRequest) -> dict:
    """按分支版本 ID 聚合模块仓库与 Git 映射，返回 repositoryId、repoUrl、branchName、destBranchName。"""
    return await _get_repo_detail_by_prod_branch(body)


async def _get_repo_detail_by_prod_branch(body: GetRepoDetailByProdBranchRequest) -> dict:
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    headers = _build_get_repo_detail_by_prod_branch_headers(body, csrf, cookies)
    branch_id = body.prod_branch
    ts = str(int(time.time() * 1000))

    url1 = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/module/branch-version/{branch_id}"
    params1: dict[str, str | int] = {
        "projectId": body.projectId,
        "catalogIdList": "",
        "typeIdList": "",
        "_": ts,
    }
    url2 = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/rpc/task/branch-versions/{branch_id}"
    params2: dict[str, str] = {"_": str(int(time.time() * 1000))}

    logger.debug(
        "get_repo_detail_by_prod_branch url1:%s params1:%s url2:%s params2:%s",
        url1,
        params1,
        url2,
        params2,
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp1 = await client.get(url1, headers=headers, params=params1)
            _log_httpx_response("get_repo_detail_by_prod_branch_module", resp1)
            resp2 = await client.get(url2, headers=headers, params=params2)
            _log_httpx_response("get_repo_detail_by_prod_branch_task", resp2)
    except httpx.RequestError as exc:
        logger.exception("调用研发云分支仓库接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp1.status_code >= 400:
        return error_response(resp1.status_code, f"研发云 branch-version 失败：{resp1.text}")
    try:
        payload1 = resp1.json()
    except ValueError:
        return error_response(502, f"研发云 branch-version 返回非 JSON：{resp1.text}")
    if payload1.get("code") != "9999":
        msg = (
            payload1.get("finalMessage")
            or payload1.get("msg")
            or payload1.get("message")
            or "研发云 branch-version 失败"
        )
        return error_response(502, msg, error=str(payload1))

    first_rows = payload1.get("data")
    if not isinstance(first_rows, list):
        first_rows = []

    if resp2.status_code >= 400:
        return error_response(resp2.status_code, f"研发云 branch-versions task 失败：{resp2.text}")
    try:
        payload2 = resp2.json()
    except ValueError:
        return error_response(502, f"研发云 branch-versions task 返回非 JSON：{resp2.text}")
    if payload2.get("code") != "9999":
        msg = (
            payload2.get("finalMessage")
            or payload2.get("msg")
            or payload2.get("message")
            or "研发云 branch-versions task 失败"
        )
        return error_response(502, msg, error=str(payload2))

    second_rows = payload2.get("data")
    if not isinstance(second_rows, list):
        second_rows = []

    out: list[dict] = []
    for row in first_rows:
        if not isinstance(row, dict):
            continue
        rid = row.get("repositoryId")
        repo_url = row.get("repoUrl")
        bname = row.get("branchName")
        dest = _dest_branch_name_from_git_rows(second_rows, rid, bname)
        out.append(
            {
                "repositoryId": rid,
                "repoUrl": repo_url,
                "branchName": bname,
                "destBranchName": dest,
            }
        )

    return success_response(out)


class GetProductVersionIdRequest(BaseModel):
    keyword: str = Field(..., description="产品版本/发布包名称关键字（模糊匹配）")
    minMatchLength: int = Field(0, description="名称最小匹配长度，默认0")

@router.post("/api/dev/iwhalecloud/get_product_version_id")
async def get_product_version_id(body: GetProductVersionIdRequest) -> dict:
    """
    功能：根据产品版本获取产品版本ID。
    用法：传入产品版本/发布包名称关键字keyword，进行模糊匹配，获取产品版本ID。
    接口类型：研发云提供标准API接口
    返回数据格式：[
        {
            "productVersionId": 123,
            "productVersionCode": "产品版本编码",
        }
    ]
    转调：POST /portal/ai-gateway/devspace/rpc/v3/master-data/product-version-list，返回码code为“9999”表示成功
    """
    if not body.keyword or not str(body.keyword).strip():
        return error_response(400, "keyword 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/master-data/product-version-list"
    payload = {
        "keyword": str(body.keyword).strip(),
        "minMatchLength": body.minMatchLength,
    }
    logger.debug("get_product_version_id url:%s, payload:%s", url, payload)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("get_product_version_id", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取产品版本列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云获取产品版本ID失败：{resp.text}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取产品版本ID失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取产品版本ID返回非 JSON：{resp.text}")

    # 提取数据
    simplified = [
        {
            "productVersionId": it.get("productVersionId"),
            "productVersionCode": it.get("productVersionCode")
        }
        for it in raw.get("data")
    ]

    return success_response(simplified)


class GetModuleNameListRequest(BaseModel):
    projectId: int = Field(-1, description="项目空间ID，可选，默认-1；建议前端必选项目空间后传入")
    productVersionId: int = Field(-1, description="产品版本ID，可选，默认-1；前端必选产品版本后传入以过滤模块")

def _build_get_module_name_list_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "A0AilsWu42pf",
        "app-signature": "c50bf7baa5299c97945c8b018e6f857b333b3cd490432acbc9b8e3a8bab02a1c",
        "app-timestamp": "1773919980126",
        "menu-id": "auto-5e9475286a215757",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_module_name_list")
async def get_module_name_list(body: GetModuleNameListRequest) -> dict:
    """对外路由：获取应用模块列表（内部复用 _get_module_name_list）。
    功能：获取应用模块列表。
    用法：传入项目空间ID、产品版本ID，获取应用模块列表。
    接口类型：研发云界面抓取请求（研发平台 -->应用模块 --> 搜索）
    返回数据格式：[
        {
            "productModuleId": 123,
            "moduleChName": "应用模块名称",
            "productVersionId": 123,
            "branchVersionId": 123,
            "productVersionCode": "产品版本编码",
            "branchName": "分支名称",
        }
    ]
    转调：GET /portal/zcm-cicd/module/getModuleList，返回码code为“9999”表示成功
    """
    return await _get_module_name_list(body)

async def _get_module_name_list(body: GetModuleNameListRequest) -> dict:
    """按项目空间与产品版本从研发云拉取模块列表（最多 50000 条）。"""
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-cicd/module/getModuleList"
    params: dict[str, str | int] = {
        "page": 1,
        "size": 50000
    }
    if body.projectId != -1:
        params["projectId"] = body.projectId
    if body.productVersionId != -1:
        params["productVersionId"] = body.productVersionId

    headers = _build_get_module_name_list_headers(csrf, cookies)
    logger.debug("get_module_name_list url:%s, headers:%s, params:%s", url, headers, params)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_module_name_list", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取模块列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云获取模块列表失败：{resp.text}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码    
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取模块列表失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取模块列表返回非 JSON：{resp.text}")

    # 提取数据
    simplified = [
        {
            "productModuleId": it.get("productModuleId"),
            "moduleChName": it.get("moduleChName"),
            "productVersionId": it.get("productVersionId"),
            "branchVersionId": it.get("branchVersionId"),
            "productVersionCode": it.get("productVersionCode"),
            "branchName": it.get("branchName"),
        }
        for it in raw.get("data").get("list")
    ]

    return success_response({"total": len(simplified), "list": simplified})


class GetProductBranchListRequest(BaseModel):
    productVersionId: int = Field(..., description="产品版本 ID（必传）")
    projectId: int | None = Field(
        default=None,
        description="项目空间 ID，可选；不传时与门户一致 query 中 projectId 为空",
    )

def _build_get_product_branch_list_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "A0AilsWu42pf",
        "app-signature": "c50bf7baa5299c97945c8b018e6f857b333b3cd490432acbc9b8e3a8bab02a1c",
        "app-timestamp": "1773919980126",
        "menu-id": "auto-5e9475286a215757",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_product_branch_list")
async def get_product_branch_list(body: GetProductBranchListRequest) -> dict:
    """对外路由：按产品版本查询分支列表（内部复用 _get_product_branch_list）。
    功能：按产品版本查询分支列表。
    用法：传入产品版本ID，获取产品分支列表。
    接口类型：研发云界面抓取请求（研发平台 --> 需求管理 --> 产品版本筛选）
    返回数据格式：{
        "total": 100,
        "list": [
            {
                "branchVersionId": 123,
                "branchName": "分支名称",
            }
        ]
    }
    转调：GET /portal/zcm-cicd/product/branch/qryByConditionWithMain，返回码code为“9999”表示成功
    """
    return await _get_product_branch_list(body)

async def _get_product_branch_list(body: GetProductBranchListRequest) -> dict:
    """
    转调：GET /portal/zcm-cicd/product/branch/qryByConditionWithMain
    （productVersionId 必传；isValid=true；size=2000；page=1；_ 为时间戳）。
    从 data.list 精简为 branchVersionId、branchName。
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-cicd/product/branch/qryByConditionWithMain"
    params: dict[str, str | int] = {
        "productVersionId": body.productVersionId,
        "isValid": "true",
        "size": 2000,
        "page": 1,
        "_": str(int(time.time() * 1000)),
    }
    headers = _build_get_product_branch_list_headers(csrf, cookies)
    logger.debug("get_product_branch_list url:%s, headers:%s, params:%s", url, headers, params)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_product_branch_list", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云产品分支列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云获取产品分支列表失败：{resp.text}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取产品分支列表失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取产品分支列表返回非 JSON：{resp.text}")

    # 提取数据
    page_data = raw.get("data") or {}
    simplified = [  
        {
            "branchVersionId": it.get("branchVersionId"),
            "branchName": it.get("branchName"),
        }
        for it in page_data.get("list")
    ]
    return success_response({"total": page_data.get("total", 0), "list": simplified})


class GetZcmProductListRequest(BaseModel):
    """请求体可为空；兼容旧客户端多传的字段一律忽略。"""

    model_config = ConfigDict(extra="ignore")


def _build_get_zcm_product_list_headers(_body: GetZcmProductListRequest, csrf: str, cookies: str) -> dict:
    """与门户 GET /zcmDomain/getZcmProductList 抓包风格一致（同 get_module_name_list）。"""
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "A0AilsWu42pf",
        "app-signature": "c50bf7baa5299c97945c8b018e6f857b333b3cd490432acbc9b8e3a8bab02a1c",
        "app-timestamp": "1773919980126",
        "menu-id": "auto-5e9475286a215757",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }


@router.post("/api/dev/iwhalecloud/get_zcm_product_list")
async def get_zcm_product_list(body: GetZcmProductListRequest) -> dict:
    """对外路由：获取 ZCM 产品版本列表（内部复用 _get_zcm_product_list）。"""
    return await _get_zcm_product_list(body)


async def _get_zcm_product_list(body: GetZcmProductListRequest) -> dict:
    """
    转调：GET /portal/zcm-cicd/zcmDomain/getZcmProductList?_=timestamp（上游不传 projectId，拉全量）。

    解析上游 data.content；对外每条仅保留 productVersionId、productVersionCode；data.size 为条数。
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-cicd/zcmDomain/getZcmProductList"
    params: dict[str, str] = {"_": str(int(time.time() * 1000))}
    headers = _build_get_zcm_product_list_headers(body, csrf, cookies)
    logger.debug("get_zcm_product_list url:%s, headers:%s, params:%s", url, headers, params)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_zcm_product_list", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云 getZcmProductList 接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云 getZcmProductList 失败：{resp.text}")
    try:
        payload = resp.json()
    except ValueError:
        return error_response(502, f"研发云 getZcmProductList 返回非 JSON：{resp.text}")
    if payload.get("code") != "9999":
        msg = (
            payload.get("finalMessage")
            or payload.get("msg")
            or payload.get("message")
            or "研发云 getZcmProductList 失败"
        )
        return error_response(502, msg, error=str(payload))

    page_data = payload.get("data")
    if not isinstance(page_data, dict):
        page_data = {}

    raw_list = page_data.get("content")
    if not isinstance(raw_list, list):
        raw_list = []

    logger.debug(
        "get_zcm_product_list parsed content_len=%s page_data_keys=%s",
        len(raw_list),
        list(page_data.keys()) if page_data else [],
    )

    out: list[dict] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "productVersionId": item.get("productVersionId"),
                "productVersionCode": item.get("productVersionCode"),
            }
        )

    return success_response({"content": out, "size": len(out)})


class GetPatchVersionRequest(BaseModel):
    userId: int = Field(..., description="用户ID")
    projectId: int = Field(-1, description="项目空间ID，默认-1")
    stateList: list[str] = Field(default_factory=lambda: ["PENDING"], description="版本状态列表，默认PENDING")
    branchVersionIdList: list[str] = Field(..., description="产品分支ID列表，必传")

def _build_get_patch_version_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "pStwjd2FyWQA",
        "app-signature": "29f1e5807eb63e8a1c97db8a4998007eada1799c34267763e6bee76ea6edf339",
        "app-timestamp": "1773923340585",
        "content-type": "application/json",
        "menu-id": "auto-7248672c7ba17406",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

def _build_get_patch_version_payload(body: GetPatchVersionRequest) -> dict:
    return {
        "createUserIdList": [],
        "patchPurposeList": [],
        "stateList": body.stateList,
        "branchVersionIdList": body.branchVersionIdList,
        "productVersionIdList": [],
        "projectIdList": [body.projectId],
        "patchName": "",
        "patchDetailConditionDto": {
            "withProject": True,
            "withZmpProject": True,
            "withUser": True,
            "withPatchGroup": True,
            "withBranchVersion": True,
        },
        "currentProjectId": body.projectId,
    }

@router.post("/api/dev/iwhalecloud/get_patch_version")
async def get_patch_version(body: GetPatchVersionRequest) -> dict:
    """对外路由：根据产品分支版本ID获取模块版本（补丁计划）（内部复用 _get_patch_version）。
    功能：根据产品分支版本ID获取模块版本（补丁计划）。
    用法：传入产品分支版本ID列表，获取模块版本（补丁计划）。
    接口类型：研发云界面抓取请求（研发平台 --> 版本管理 --> 查询）
    返回数据格式：{
        "patchName": "补丁计划名称",
    }
    转调：GET /portal/zcm-devspace/patch/page/list/{userId}?page=1&limit=1000，返回码code为“9999”表示成功
    """
    return await _get_patch_version(body)

async def _get_patch_version(body: GetPatchVersionRequest) -> dict:
    """
    根据产品分支版本ID获取模块版本（补丁计划）。
    转调：POST /portal/zcm-devspace/patch/page/list/{userId}?page=1&limit=1000
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))
    if not body.branchVersionIdList:
        return error_response(400, "branchVersionIdList 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/patch/page/list/{body.userId}"
    params = {"page": 1, "limit": 1000}
    headers = _build_get_patch_version_headers(csrf, cookies)
    payload = _build_get_patch_version_payload(body)

    logger.debug("get_patch_version url:%s, params:%s, payload:%s", url, params, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            _log_httpx_response("get_patch_version", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取补丁计划接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云获取补丁计划失败：{resp.text}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取补丁计划失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取补丁计划返回非 JSON：{resp.text}")

    # 提取数据
    items = ((raw.get("data") or {}).get("list") or [])
    if not items:
        return success_response({"patchName": None}, "未找到补丁计划")
    patch_name = (((items[0] or {}).get("adPatch") or {}).get("patchName"))
    return success_response({"patchName": patch_name})



class GetCiFlowExecutionStatusRequest(BaseModel):
    flowId: int = Field(..., description="流程 ID")
    branchName: str | None = Field(None, description="特性分支名称")

@router.post("/api/dev/iwhalecloud/get_ci_flow_execution_status")
async def get_ci_flow_execution_status(body: GetCiFlowExecutionStatusRequest) -> dict:
    """对外路由：根据构建流程获取CI最新的构建结果（内部复用 _get_ci_flow_execution_status）。
    功能：根据构建流程获取CI最新的构建结果。
    用法：传入流程ID，获取CI最新的构建结果。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "status": "success",
        "stages": [
            {
                "stageName": "阶段名称",
                "stageInstanceId": "阶段实例ID",
                "status": "阶段状态",
            }
        ],
        "resultMsg": "构建结果消息",
    }
    """
    return await _get_ci_flow_execution_status(body)

async def _get_ci_flow_execution_status(body: GetCiFlowExecutionStatusRequest) -> dict:
    """
    内部调用：根据构建流程获取CI最新的构建结果。
    查询指定流程（和分支名）最近一次执行结果（构建成功/失败与分段状态）。
    转调：GET /portal/ai-gateway/cicd/rpc/v3/flow/{flowId}/latest/execution/status
    """
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/cicd/rpc/v3/flow/{body.flowId}/latest/execution/status"
    headers = _headers("application/x-www-form-urlencoded")

    logger.debug("get_ci_flow_execution_status url:%s, headers:%s", url, headers)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            _log_httpx_response("get_ci_flow_execution_status", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取CI执行结果接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云获取CI执行结果失败：{resp.text}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取CI执行结果失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取CI执行结果返回非 JSON：{resp.text}")

    # 提取数据
    flow_data = raw.get("data") or {}
    stages: list[dict] = []
    for item in flow_data.get("nodeInstanceBuildStatuses") or []:
        stages.append(
            {
                "stageName": item.get("stageName"),
                "stageInstanceId": item.get("stageInstanceId"),
                "status": item.get("status"),
            }
        )

    # 默认为构建失败，根据实际状态返回相应消息
    result_msg = "构建失败"
    if flow_data.get("status") == "success":
        result_msg = "构建成功"
    if flow_data.get("status") == "executing":
        result_msg = "构建中"

    return success_response({"status": flow_data.get("status"), "stages": stages}, result_msg)


class GetCiFlowReportRequest(BaseModel):
    flowId: int = Field(..., description="流程 ID")
    branchName: str | None = Field(None, description="特性分支名称")
    nodeTypeIds: list[int] = Field(default=[], description="nodeTypeIds（可选，默认空数组）")

@router.post("/api/dev/iwhalecloud/get_ci_flow_report")
async def get_ci_flow_report(body: GetCiFlowReportRequest) -> dict:
    """对外路由：根据构建流程获取最新的CI报表（内部复用 _get_ci_flow_report）。
    功能：据构建流程获取最新的CI报表。
    用法：传入流程ID，获取最新的CI报表。
    接口类型：研发云提供标准API接口
    返回数据格式：[
		{
			"nodeTypeId": 0,
			"nodeTypeName": "",
			"attachmentList": [
				{
					"attachmentDesc": "",
					"url": "",
					"size": 0
				}
			]
		}
	]
    转调：POST /portal/ai-gateway/cicd/rpc/v3/flow/{flowId}/artifact/report，返回码code为“9999”表示成功
    """
    return await _get_ci_flow_report(body)
    
async def _get_ci_flow_report(body: GetCiFlowReportRequest) -> dict:
    """
    据构建流程获取最新的CI报表（直接返回上游 data）。
    转调：POST /portal/ai-gateway/cicd/rpc/v3/flow/{flowId}/artifact/report
    """
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/cicd/rpc/v3/flow/{body.flowId}/artifact/report"

    # 上游 body 字段名从抓包推断为 nodeTypeIds；若无需可传空数组。
    payload = {"nodeTypeIds": body.nodeTypeIds}

    logger.debug("get_ci_flow_report url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("get_ci_flow_report", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取CI报表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取CI报表失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取CI报表返回非 JSON：{resp.text}")

    # 提取数据
    return success_response(raw.get("data"))


class GetTaskBuildHistoryRequest(BaseModel):
    taskId: int = Field(..., description="任务ID")

def _build_get_task_build_history_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.9,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "Vi6W6mwmxmsn",
        "app-signature": "a432bbe6dc4d03d970c23d8b66be091dcc82abaf4d932675ec78088b24eb4fed",
        "app-timestamp": "1774495938747",
        "menu-id": "auto-4efb52a18be660c520233131353533303039",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_task_build_history")
async def get_task_build_history(body: GetTaskBuildHistoryRequest) -> dict:
    """对外路由：根据任务ID获取任务构建历史（内部复用 _get_task_build_history）。
    功能：根据任务ID获取任务构建历史。
    用法：传入任务ID，获取任务构建历史。
    接口类型：研发云界面抓取请求（研发平台 --> 事务管理 --> 任务详情 --> 代码分支）
    返回数据格式：[
        {
            "ciFlowId": 123,
            "ciFlowInstId": "ciFlowInstId",
            "ciFlowInstBeginDate": "ciFlowInstBeginDate",
            "ciFlowInstEndDate": "ciFlowInstEndDate",
            "ciFlowInstRunState": "ciFlowInstRunState",
        }
    ]
    转调：GET /portal/zcm-devspace/task/{taskId}/build-history，返回码code为“9999”表示成功
    """
    return await _get_task_build_history(body)

async def _get_task_build_history(body: GetTaskBuildHistoryRequest) -> dict:
    """
    内部调用：根据任务ID获取任务构建历史。
    转调：GET /portal/zcm-devspace/task/{taskId}/build-history
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{body.taskId}/build-history"
    params = {"_": int(datetime.now().timestamp() * 1000)}
    headers = _build_get_task_build_history_headers(csrf, cookies)
    logger.debug("get_task_build_history url:%s, params:%s", url, params)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_task_build_history", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取任务构建历史接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取任务构建历史失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取任务构建历史返回非 JSON：{resp.text}")

    # 提取数据
    simplified = [
        {
            "ciFlowId": it.get("ciFlowId"),
            "ciFlowInstId": it.get("ciFlowInstId"),
            "ciFlowInstBeginDate": it.get("ciFlowInstBeginDate"),
            "ciFlowInstEndDate": it.get("ciFlowInstEndDate"),
            "ciFlowInstRunState": it.get("ciFlowInstRunState"),
        }
        for it in raw.get("data").get("featureBuildHisList")
    ]
    return success_response(simplified)



class GetCiFlowBuildResultRequest(BaseModel):
    ciFlowInstId: str = Field(..., description="构建实例ID（ciFlowInstId）")

def _build_get_ci_flow_build_result_headers(body: GetCiFlowBuildResultRequest, csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "t3swOYcGM69y",
        "app-signature": "167682a83e0dfa0c17765441ffa26e3f4205f53a5b14982521bc57259ee6d592",
        "app-timestamp": "1774506232918",
        "menu-id": "auto-34323831377c5a4d44422d666c6f772d6369202f2067845efa538653f2",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_ci_flow_build_result")
async def get_ci_flow_build_result(body: GetCiFlowBuildResultRequest) -> dict:
    f"""对外路由：根据 ciFlowInstId 获取本次构建各环节结果。
    功能：根据 ciFlowInstId 获取本次构建各环节结果。
    用法：传入构建实例ID，获取本次构建各环节结果。
    接口类型：研发云界面抓取请求（研发平台 --> 事务管理 --> 任务详情 --> 代码分支 --> 双击试飞构建历史）
    返回数据格式：[
        {
            "nodeName": "节点名称",
            "stepId": "步骤ID",
            "runResult": "运行结果",
            "url": "URL",
            "attachments": [
                {
                    "fullPath": "附件全路径",
                    "path": "附件路径",
                    "nodeInstanceId": "节点实例ID",
                    "attachmentDesc": "附件描述",
                    "fileSize": "附件大小",
                    "resultType": "附件类型",
                    "createDate": "创建时间",
                }
            ]
        }
    ]
    转调：GET /portal/zcm-cicd/ci/flow/history/qryFlowNodeInstanceDetail/{{ciFlowInstId}}，返回码code为null
    """
    return await _get_ci_flow_build_result(body)

async def _get_ci_flow_build_result(body: GetCiFlowBuildResultRequest) -> dict:
    """
    内部调用：根据 ciFlowInstId 获取本次构建各环节结果。
    转调：GET /portal/zcm-cicd/ci/flow/history/qryFlowNodeInstanceDetail/{ciFlowInstId}
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))
    if not body.ciFlowInstId:
        return error_response(400, "ciFlowInstId 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-cicd/ci/flow/history/qryFlowNodeInstanceDetail/{body.ciFlowInstId}"
    params = {"_": int(datetime.now().timestamp() * 1000)}
    headers = _build_get_ci_flow_build_result_headers(body, csrf, cookies)
    logger.debug("get_ci_flow_build_result url:%s, params:%s", url, params)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_ci_flow_build_result", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取构建结果接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码    
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云获取构建结果失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云获取构建结果返回非 JSON：{resp.text}")

    # 提取数据 
    simplified = [
        {
            "nodeName": it.get("nodeName"),
            "stepId": it.get("stepId"),
            "runResult": it.get("runResult"),
            "url": it.get("url"),
            "attachments": it.get("attachments") or [],
        }
        for it in raw.get("data")
    ]
    return success_response(simplified)


class GetCiFlowBuildStatusRequest(BaseModel):
    taskId: int = Field(..., description="任务ID")

def _parse_dt_for_sort(v: object) -> datetime:
    if not isinstance(v, str) or not v.strip():
        return datetime.min
    s = v.strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.min

def _build_state_desc(v: object) -> str:
    s = "" if v is None else str(v).strip()
    if s == "0":
        return "构建成功"
    if s == "1":
        return "构建失败"
    return "构建中"

@router.post("/api/dev/iwhalecloud/get_ci_flow_build_status")
async def get_ci_flow_build_status(body: GetCiFlowBuildStatusRequest) -> dict:
    """
    根据任务构建历史聚合每个 flowId 的最新状态，并补充本次构建各环节结果。
    1) 调 _get_task_build_history 取 featureBuildHisList
    2) 按 ciFlowId 分组，按 ciFlowInstBeginDate 取最新一条
    3) 每条都调用 _get_ci_flow_build_result(ciFlowInstId)
    4) 返回数据格式：
    {
        "taskId": "任务ID",
        "flowBuildStatusList": [
            {
                "ciFlowId": "CI流程ID",
                "ciFlowInstId": "构建实例ID",
                "ciFlowInstBeginDate": "构建开始时间",
                "ciFlowInstEndDate": "构建结束时间",
                "ciFlowInstRunState": "构建状态",
                "ciFlowInstRunStateDesc": "构建状态描述",
                "buildResult": [
                    {
                        "nodeName": "节点名称",
                        "stepId": "步骤ID",
                        "runResult": "运行结果",
                        "url": "URL",
                        "attachments": [
                            {
                                "fullPath": "附件全路径",
                                "path": "附件路径",
                                "nodeInstanceId": "节点实例ID",
                                "attachmentDesc": "附件描述",
                                "fileSize": "附件大小",
                                "resultType": "附件类型",
                                "createDate": "创建时间",
                            }
                        ]
                    }
                ]
            }
        ]
    }
    """
    try:
        # 1) 先拿到“任务维度”的构建历史（里面包含 featureBuildHisList）
        history_resp = await _get_task_build_history(GetTaskBuildHistoryRequest(taskId=body.taskId))
        # 上游失败则直接透传错误
        if not isinstance(history_resp, dict) or history_resp.get("errorcode") != 0:
            return history_resp if isinstance(history_resp, dict) else error_response(502, "获取构建历史失败")

        # 兜底：无历史数据时直接返回错误（避免后续分组逻辑空指针）
        if not history_resp.get("data") or history_resp.get("data") == []:
            return error_response(502, "获取构建历史失败")

        # 2) 提取构建历史列表（同一个 flowId 可能会有多次构建记录）
        history_data = history_resp.get("data") or []
        # 3) 先按 ciFlowId 分组（一个任务可能挂多个 CI flow；每个 flow 又可能构建多次）
        grouped: dict[str, list[dict]] = {}
        for item in history_data:
            if not isinstance(item, dict):
                continue
            flow_id = item.get("ciFlowId")
            if flow_id is None or str(flow_id).strip() == "":
                continue
            grouped.setdefault(str(flow_id), []).append(item)

        # 4) 每个 flowId 只保留“最新一次”构建（按 ciFlowInstBeginDate 最大值）
        #    目的：确保同一个 flowId 即使构建多次，也只会请求“最新那次”的构建结果
        latest_by_flow: dict[str, dict] = {}
        for flow_id, items in grouped.items():
            latest_by_flow[flow_id] = max(items, key=lambda x: _parse_dt_for_sort(x.get("ciFlowInstBeginDate")))

        # 5) 对每个“最新构建实例”再去查构建节点结果（get_ci_flow_build_result）
        #    同一个 ciFlowInstId 可能重复出现，做缓存避免重复请求
        build_result_cache: dict[str, list[dict]] = {}

        result_list: list[dict] = []
        for _, latest in latest_by_flow.items():
            ci_flow_inst_id = latest.get("ciFlowInstId")
            run_state = latest.get("ciFlowInstRunState")

            node_results: list[dict] = []
            if ci_flow_inst_id is not None and str(ci_flow_inst_id).strip():
                inst_id_str = str(ci_flow_inst_id).strip()
                cached = build_result_cache.get(inst_id_str)
                if cached is not None:
                    # 命中缓存：不重复请求上游
                    node_results = cached
                else:
                    # 未命中缓存：调用上游获取该构建实例的“各节点执行结果”
                    build_result_resp = await _get_ci_flow_build_result(
                        GetCiFlowBuildResultRequest(ciFlowInstId=inst_id_str),
                    )
                    # 上游成功：只抽取前端关心的字段，保持数组结构不变
                    if isinstance(build_result_resp, dict) and build_result_resp.get("errorcode") == 0:
                        br_data = build_result_resp.get("data") or []
                        if isinstance(br_data, list):
                            for n in br_data:
                                if not isinstance(n, dict):
                                    continue
                                node_results.append(
                                    {
                                        "nodeName": n.get("nodeName"),
                                        "stepId": n.get("stepId"),
                                        "runResult": n.get("runResult"),
                                        "url": n.get("url"),
                                        "attachments": n.get("attachments") or [],
                                    }
                                )
                    build_result_cache[inst_id_str] = node_results

            # 6) 拼装每个 flowId 的最终输出：最新构建 + 状态 + 节点结果数组
            result_list.append(
                {
                    "ciFlowId": latest.get("ciFlowId"),
                    "ciFlowInstId": ci_flow_inst_id,
                    "ciFlowInstBeginDate": latest.get("ciFlowInstBeginDate"),
                    "ciFlowInstEndDate": latest.get("ciFlowInstEndDate"),
                    "ciFlowInstRunState": run_state,
                    "ciFlowInstRunStateDesc": _build_state_desc(run_state),
                    "buildResult": node_results,
                }
            )

        # 7) 最终按开始时间倒序，方便前端直接展示“最近的构建”
        result_list.sort(key=lambda x: _parse_dt_for_sort(x.get("ciFlowInstBeginDate")), reverse=True)
        return success_response({"taskId": body.taskId, "flowBuildStatusList": result_list})
    except Exception as e:
        logger.exception("获取构建状态失败: %s", e)
        return error_response(502, f"获取构建状态失败: {e}")



class CreateTaskImpactItem(BaseModel):
    taskImpactId: int = Field(..., description="影响点 ID")
    taskImpactDesc: str = Field(..., description="任务影响描述")

class CreateTaskRequest(BaseModel):
    taskNo: str= Field(..., description="需求单号")
    taskTitle: str = Field(..., description="标题")
    comments: str = Field(..., description="描述信息")
    ownerUserCode: str = Field(..., description="负责人工号")
    projectId: int | None = Field(None, description="项目空间标志:与productModuleName必须二选一传值")
    productModuleName: str | None = Field(None, description="应用模块名称:与projectId必须二选一传值")
    branchVersionName: str | None = Field(None, description="产品分支名称:可以是主产品分支,也可以是Trunk产品分支")
    mainBranchVersionTaskNo: str | None = Field(None, description="Trunk分支关联的主分支单号")
    taskClassification: str | None = Field(None, description="领域:TECH-技术,FUNCTION-功能,SECURITY-安全,PERFORMANCE-性能,USE_OPTIMIZATION-体验,示例值(FUNCTION)")
    taskPri: int | None = Field(None, description="优先级:5-较低,6-普通,7-紧急,8-非常紧急,示例值(5)")
    patchName: str = Field(..., description="补丁计划名称")
    userId: int = Field(..., description="用户ID")
    taskImpactList: list[CreateTaskImpactItem] = Field(..., description="任务影响点（创建后将自动新增并确认）")
    performanceImpact: str = Field(..., description="性能影响")
    functionalImpact: str = Field(..., description="功能影响")
    cfgChangeDescription: str = Field(..., description="配置变更说明")
    upgradeRisk: str = Field(..., description="升级风险")
    securityImpact: str = Field(..., description="安全影响")
    compatibilityImpact: str = Field(..., description="兼容性影响")

def _build_create_task_payload(body: CreateTaskRequest) -> dict:
    payload: dict = {
        "taskTitle": body.taskTitle,
        "comments": body.comments,
        "ownerUserCode": body.ownerUserCode,
    }
    if body.projectId is not None:
        payload["projectId"] = body.projectId
    if body.productModuleName is not None:
        payload["productModuleName"] = body.productModuleName
    if body.branchVersionName is not None:
        payload["branchVersionName"] = body.branchVersionName
    if body.mainBranchVersionTaskNo is not None:
        payload["mainBranchVersionTaskNo"] = body.mainBranchVersionTaskNo
    if body.taskClassification is not None:
        payload["taskClassification"] = body.taskClassification
    if body.taskPri is not None:
        payload["taskPri"] = body.taskPri
    return payload

@router.post("/api/dev/iwhalecloud/create_task")
async def create_task(body: CreateTaskRequest) -> dict:
    """
    功能：需求单拆单。
    用法：传入需求单号、负责人、版本、影响点等，创建需求单。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "taskNo": "任务单号",
        "taskId": "任务ID",
        "branch": {
            "productModuleId": 应用模块ID, 
            "productModuleName": "产品模块名称", 
            "repoId": 仓库ID, 
            "repoName": "仓库名称", 
            "repoUrl": "仓库URL", 
            "branchName": "特性分支名称", 
            "baseBranchName": "来源分支名称", 
        }
    }
    转调：POST /portal/ai-gateway/devspace/rpc/v3/user-story/{body.taskNo}/work-item/inner，返回码code为“9999”表示成功
    """
    # 参数校验：统一入口必须具备负责人、版本、影响点等
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")
    if not body.ownerUserCode:
        return error_response(400, "ownerUserCode 不能为空，不允许创建任务")
    if body.projectId is None and body.productModuleName is None:
        return error_response(400, "projectId 与 productModuleName 必须二选一传值")
    if not body.patchName or not body.productModuleName or not body.branchVersionName:
        return error_response(400, "未传版本名称（补丁计划名称）、应用模块名称、产品分支名称，不允许创建任务单")
    if not body.taskImpactList:
        return error_response(400, "taskImpactList 为空，请传入任务影响点")
    if not body.performanceImpact or not body.functionalImpact or not body.cfgChangeDescription or not body.upgradeRisk or not body.securityImpact or not body.compatibilityImpact:
        return error_response(400, "performanceImpact、functionalImpact、cfgChangeDescription、upgradeRisk、securityImpact、compatibilityImpact 不能为空")
    try:
        await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    # 步骤1：调用创建任务单接口
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/user-story/{body.taskNo}/work-item/inner"
    payload = _build_create_task_payload(body)
    logger.debug("create_task url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("create_task", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云创建任务接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 步骤2：检查创建任务响应
    if resp.status_code != 200:
        return error_response(resp.status_code, f"研发云创建任务失败：{resp.text}")
    try:
        create_json = resp.json()
    except ValueError:
        return error_response(502, f"研发云创建任务返回非 JSON：{resp.text}")

    # 步骤3：校验业务成功（code=9999）
    resp_code = create_json.get("code")
    if resp_code != "9999":
        return error_response(502, f"研发云创建任务失败：{create_json}")

    # 步骤4：获取新任务单号和任务ID
    created_task_no = create_json.get("data", {}).get("taskNo")
    created_task_id = create_json.get("data", {}).get("taskId")
    if not created_task_no or not created_task_id:
        return error_response(502, "研发云创建任务返回缺少 taskNo 或 taskId")

    # 步骤5：更新任务补丁版本（创建时必须同步）
    patch_result = await _update_task_patch(UpdateTaskPatchRequest(taskNo=created_task_no, patchName=body.patchName))
    if isinstance(patch_result, dict) and patch_result.get("errorcode") not in (None, 0):
        return error_response(
            502,
            "任务已创建，但更新补丁计划失败",
            error=str(patch_result),
        )

    # 步骤6：新增任务影响点（必须）
    impact_items = [AddTaskImpactItem(taskImpactId=it.taskImpactId, taskId=created_task_id, taskImpactDesc=it.taskImpactDesc) for it in body.taskImpactList]
    add_impact_body = AddTaskImpactRequest(userId=body.userId, taskImpactList=impact_items)
    add_impact_result = await _add_task_impact(add_impact_body)
    if isinstance(add_impact_result, dict) and add_impact_result.get("errorcode") not in (None, 0):
        return error_response(502, "任务已创建，但新增任务影响点失败", error=str(add_impact_result))

    # 步骤7：自动确认影响点
    confirm_items = [
        TaskImpactConfirmItem(taskImpactId=it.taskImpactId, taskId=created_task_id, confirmResult="Y", confirmRole="DEV")
        for it in impact_items
    ]
    confirm_body = TaskImpactConfirmRequest(userId=body.userId, taskImpactList=confirm_items)
    confirm_result = await _task_impact_confirm(confirm_body)
    if isinstance(confirm_result, dict) and confirm_result.get("errorcode") not in (None, 0):
        return error_response(502, "任务已创建，但影响点确认失败", error=str(confirm_result))

    # 步骤9：更新任务影响评估
    auto_eval = {
        "performanceImpact": body.performanceImpact,
        "functionalImpact": body.functionalImpact,
        "cfgChangeDescription": body.cfgChangeDescription,
        "upgradeRisk": body.upgradeRisk,
        "securityImpact": body.securityImpact,
        "compatibilityImpact": body.compatibilityImpact,
    }
    update_eval_body = UpdateTaskImpactEvaluationRequest(taskId=created_task_id, userId=body.userId, **auto_eval)
    eval_result = await _update_task_impact_evaluation(update_eval_body)
    if isinstance(eval_result, dict) and eval_result.get("errorcode") not in (None, 0):
        return error_response(502, "任务已创建，但研发单影响评估编辑失败", error=str(eval_result))

    # 步骤10：转开发中（仅做状态流转）
    transfer_body = TransferTaskStageRequest(
        taskNo=created_task_no,
        ownerUserCode=body.ownerUserCode,
        operateUserCode=body.ownerUserCode,
        taskFlowStageId=DEV_IWHALECLOUD_TASK_STAGE_DEVELOPING,
        comments="create_task 统一入口：自动转开发中",
    )
    transfer_result = await _transfer_task_stage(transfer_body)
    if isinstance(transfer_result, dict) and transfer_result.get("errorcode") not in (None, 0):
        return error_response(502, "任务已创建，但转开发中失败", error=str(transfer_result))

    # 步骤11：创建特性分支
    branch_result = await _create_feature_branch(CreateFeatureBranchRequest(taskNo=created_task_no, branchName=created_task_no))
    if isinstance(branch_result, dict) and branch_result.get("errorcode") not in (None, 0):
        return error_response(502, "任务已创建，但创建特性分支失败", error=str(branch_result))
    branch_data = branch_result.get("data") if isinstance(branch_result, dict) else None

    return success_response(
        {
            "taskNo": created_task_no,
            "taskId": created_task_id,
            "branch": branch_data,
        },
        "创建任务统一流程执行成功",
    )


class UpdateTaskPatchRequest(BaseModel):
    taskNo: str = Field(..., description="任务单号")
    patchName: str = Field(..., description="补丁计划名称")

@router.post("/api/dev/iwhalecloud/update_task_patch")
async def update_task_patch(body: UpdateTaskPatchRequest) -> dict:
    """对外路由：修改任务的补丁计划（内部复用 _update_task_patch）。
    功能：修改任务的补丁计划。
    用法：传入任务单号和补丁计划名称，修改任务的补丁计划。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "code": "9999",
        "data": true,
        "msg": "",
        "message": "",
        "finalMessage": ""
    }
    转调：POST /portal/ai-gateway/devspace/rpc/v3/task/{body.taskNo}/patch，返回码code为“9999”表示成功
    """
    return await _update_task_patch(body)

async def _update_task_patch(body: UpdateTaskPatchRequest) -> dict:
    """内部调用：修改任务的补丁计划。"""
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task/{body.taskNo}/patch"
    payload = {"patchName": body.patchName}
    logger.debug("_update_task_patch url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("_update_task_patch", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云更新补丁接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    return _forward_response(resp)


class AddTaskImpactItem(BaseModel):
    taskImpactId: int = Field(..., description="影响点 ID")
    taskId: int = Field(..., description="任务 ID")
    taskImpactDesc: str = Field(..., description="任务影响描述")

class AddTaskImpactRequest(BaseModel):
    userId: int = Field(..., description="用户 ID")
    taskImpactList: list[AddTaskImpactItem] = Field(..., description="任务影响点列表")

def _build_add_task_impact_headers(x_csrf_token: str, cookie_header: str | None) -> dict:
    """与浏览器 PUT /task/{id}/impact/detail 抓包一致。"""
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "94jGWGJUIFXh",
        "app-signature": "5f8ee3f89a868edb84d74913181ef56a0a60fe7b3ea6d196a3ef5b98bd562229",
        "app-timestamp": "1774252960272",
        "content-type": "application/json",
        "menu-id": "auto-4efb52a18be660c520233131383334383735",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": x_csrf_token,
        "x-requested-with": "XMLHttpRequest",
    }
    if cookie_header:
        headers["cookie"] = cookie_header
    return headers

@router.post("/api/dev/iwhalecloud/add_task_impact")
async def add_task_impact(body: AddTaskImpactRequest) -> dict:
    """对外路由：新增任务影响点（内部复用 _add_task_impact）。"""
    return await _add_task_impact(body)

async def _add_task_impact(body: AddTaskImpactRequest) -> dict:
    """
    内部调用：新增任务影响点。

    转调：
    PUT /portal/zcm-devspace/task/{taskId}/impact/detail?userId={userId}
    """
    items = body.taskImpactList
    if not items:
        return error_response(400, "taskImpactList 不能为空")

    task_id = items[0].taskId
    for it in items:
        if it.taskId != task_id:
            return error_response(400, "taskImpactList 内 taskId 必须全部一致")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{task_id}/impact/detail"
    params = {"userId": body.userId}
    try:
        csrf, ck = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))
    headers = _build_add_task_impact_headers(csrf, ck)
    payload = [it.model_dump() for it in items]
    logger.debug("add_task_impact url:%s params:%s payload:%s", url, params, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(url, headers=headers, params=params, json=payload)
            _log_httpx_response("add_task_impact", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云新增任务影响点接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    return _forward_response(resp)


class TaskImpactConfirmItem(BaseModel):
    taskImpactId: int = Field(..., description="任务影响ID")
    taskId: int = Field(..., description="任务ID")
    confirmResult: str = Field("Y", description="确认结果，例如 Y/N")
    confirmRole: str = Field("DEV", description="确认角色，例如 DEV")

class TaskImpactConfirmRequest(BaseModel):
    """任务影响确认：userId 与 taskImpactList。"""
    userId: int = Field(..., description="用户ID")
    taskImpactList: list[TaskImpactConfirmItem] = Field(
        ...,
        description="影响确认项列表",
    )

def _build_task_impact_confirm_headers(x_csrf_token: str, cookie_header: str | None) -> dict:
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "gIM4AN5apme4",
        "app-signature": "b4c74d0bb6f9800bdc03c2bb69e9a68fc5600ae283eac187c96586b6eb40beb9",
        "app-timestamp": "1773832125895",
        "content-type": "application/json",
        "menu-id": "auto-4efb52a18be660c520233131383332383139",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": x_csrf_token,
        "x-requested-with": "XMLHttpRequest",
    }
    if cookie_header:
        headers["cookie"] = cookie_header
    return headers

@router.post("/api/dev/iwhalecloud/task_impact_confirm")
async def task_impact_confirm(body: TaskImpactConfirmRequest) -> dict:
    """对外路由：任务影响确认（内部复用 _task_impact_confirm）。"""
    return await _task_impact_confirm(body)

async def _task_impact_confirm(body: TaskImpactConfirmRequest) -> dict:
    """
    内部调用：任务影响确认。

    转调：
    POST /portal/zcm-devspace/task/{taskId}/impact/detail/confirm?userId={userId}
    """
    items = body.taskImpactList
    user_id = body.userId
    if not items:
        return error_response(400, "taskImpactList 不能为空")

    # 上游 URL 只有一个 taskId，要求 taskImpactList 内 taskId 一致
    task_id = items[0].taskId
    for it in items:
        if it.taskId != task_id:
            return error_response(400, "taskImpactList 内 taskId 必须全部一致")

    url = (
        f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{task_id}/"
        f"impact/detail/confirm?userId={user_id}"
    )
    try:
        csrf, ck = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))
    headers = _build_task_impact_confirm_headers(csrf, ck)
    payload = [it.model_dump() for it in items]

    logger.debug("task_impact_confirm url:%s payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            _log_httpx_response("task_impact_confirm", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云任务影响确认接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    return _forward_response(resp)


class UpdateTaskImpactEvaluationRequest(BaseModel):
    taskId: int = Field(..., description="任务单ID")
    performanceImpact: str = Field(..., description="性能影响")
    functionalImpact: str = Field(..., description="功能影响")
    cfgChangeDescription: str = Field(..., description="配置变更说明")
    upgradeRisk: str = Field(..., description="升级风险")
    securityImpact: str = Field(..., description="安全影响")
    compatibilityImpact: str = Field(..., description="兼容性影响")
    userId: int = Field(..., description="用户ID")

def _build_update_task_impact_evaluation_headers(body: UpdateTaskImpactEvaluationRequest, csrf: str, cookies: str) -> dict:
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "gIM4AN5apme4",
        "app-signature": "b4c74d0bb6f9800bdc03c2bb69e9a68fc5600ae283eac187c96586b6eb40beb9",
        "app-timestamp": "1773832125895",
        "content-type": "application/json",
        "menu-id": "auto-4efb52a18be660c520233131383238373539",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }
    return headers

def _build_update_task_impact_evaluation_payload(body: UpdateTaskImpactEvaluationRequest) -> list[dict]:
    payload = [
        {"projectFieldId": 20085, "fieldValue": body.performanceImpact, "fieldValueDesc": body.performanceImpact, "userId": body.userId},
        {"projectFieldId": 20086, "fieldValue": body.functionalImpact, "fieldValueDesc": body.functionalImpact, "userId": body.userId},
        {"projectFieldId": 20087, "fieldValue": body.cfgChangeDescription, "fieldValueDesc": body.cfgChangeDescription, "userId": body.userId},
        {"projectFieldId": 20088, "fieldValue": body.upgradeRisk, "fieldValueDesc": body.upgradeRisk, "userId": body.userId},
        {"projectFieldId": 20089, "fieldValue": body.securityImpact, "fieldValueDesc": body.securityImpact, "userId": body.userId},
        {"projectFieldId": 20413, "fieldValue": body.compatibilityImpact, "fieldValueDesc": body.compatibilityImpact, "userId": body.userId},
    ]
    return payload

@router.post("/api/dev/iwhalecloud/update_task_impact_evaluation")
async def update_task_impact_evaluation(body: UpdateTaskImpactEvaluationRequest) -> dict:
    """对外路由：更新任务影响评估（内部复用 _update_task_impact_evaluation）。"""
    return await _update_task_impact_evaluation(body)

async def _update_task_impact_evaluation(body: UpdateTaskImpactEvaluationRequest) -> dict:
    """
    内部调用：更新任务影响评估。
    转调：POST /portal/zcm-devspace/task/{taskId}/project-fields/batch-modify
    """
    if not body.taskId:
        return error_response(400, "taskId 不能为空")
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{body.taskId}/project-fields/batch-modify"
    headers = _build_update_task_impact_evaluation_headers(body, csrf, cookies)
    payload = _build_update_task_impact_evaluation_payload(body)
    logger.debug("update_task_impact_evaluation url:%s, headers:%s, payload:%s", url, headers, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            _log_httpx_response("update_task_impact_evaluation", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云更新任务影响评估接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    return _forward_response(resp)


class CreateFeatureBranchRequest(BaseModel):
    taskNo: str = Field(..., description="任务单号")
    branchName: str = Field(..., description="特性分支名称")

@router.post("/api/dev/iwhalecloud/create_feature_branch")
async def create_feature_branch(body: CreateFeatureBranchRequest) -> dict:
    """对外路由：创建特性分支（内部复用 _create_feature_branch
    功能：创建特性分支。
    用法：传入任务单号和特性分支名称，创建特性分支。
    接口类型：研发云提供标准API接口
    返回数据格式：{
		"productModuleId": 应用模块ID, 
		"productModuleName": "产品模块名称", 
		"repoId": 仓库ID, 
		"repoName": "仓库名称", 
		"repoUrl": "仓库URL", 
		"branchName": "特性分支名称", 
		"baseBranchName": "来源分支名称", 
	}
    转调：POST /portal/ai-gateway/devspace/rpc/v3/task-branch/feature/create，返回码code为“9999”表示成功
    """
    return await _create_feature_branch(body)

async def _create_feature_branch(body: CreateFeatureBranchRequest) -> dict:
    """内部调用：创建特性分支。"""
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")
    if not body.branchName:
        return error_response(400, "branchName 不能为空")
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task-branch/feature/create"
    payload = {"taskNo": body.taskNo, "branchName": body.branchName}
    logger.debug("_create_feature_branch url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("_create_feature_branch", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云创建特性分支接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云创建特性分支失败"
            return error_response(502, msg, error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云创建特性分支返回非 JSON：{resp.text}")

    # 提取数据返回
    return success_response(
        {
            "productModuleId": raw.get("data").get("productModuleId"),
            "productModuleName": raw.get("data").get("productModuleName"),
            "repoId": raw.get("data").get("repoId"),
            "repoName": raw.get("data").get("repoName"),
            "repoUrl": raw.get("data").get("repoUrl"),
            "branchName": raw.get("data").get("branchName"),
            "baseBranchName": raw.get("data").get("baseBranchName"),
        }
    )


class TransferTaskStageRequest(BaseModel):
    taskNo: str = Field(..., description="任务单号")
    ownerUserCode: str = Field(..., description="目标处理人工号")
    operateUserCode: str = Field(..., description="当前操作人工号")
    taskFlowStageId: int = Field(..., description="目标状态ID")
    comments: str = Field("", description="转单备注")
    
def _build_transfer_task_stage_payload(body: TransferTaskStageRequest) -> dict:
    return {
        "ownerUserCode": body.ownerUserCode,
        "operateUserCode": body.operateUserCode,
        "taskFlowStageId": body.taskFlowStageId,
        "comments": body.comments or "",
    }

@router.post("/api/dev/iwhalecloud/transfer_task_stage")
async def transfer_task_stage(body: TransferTaskStageRequest) -> dict:
    """对外路由：转研发单状态（内部复用 _transfer_task_stage）。"""
    return await _transfer_task_stage(body)

async def _transfer_task_stage(body: TransferTaskStageRequest) -> dict:
    """
    内部调用：转单（将研发单流转到指定状态并指定处理人）。
    功能：将研发单流转到指定状态并指定处理人。
    用法：传入任务单号、目标处理人工号、当前操作人工号、目标状态ID、转单备注，将研发单流转到指定状态并指定处理人。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "code": "9999",
        "data": true,
        "msg": "",
        "message": "",
        "finalMessage": ""
    }
    转调：POST /portal/ai-gateway/devspace/rpc/v3/task/{taskNo}/stage，返回码code为“9999”表示成功
    """
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task/{body.taskNo}/stage"
    payload = _build_transfer_task_stage_payload(body)
    logger.debug("transfer_task_stage url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("transfer_task_stage", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云转单接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    return _forward_response(resp)


class TransferToCodeReviewRequest(BaseModel):
    taskNo: str = Field(..., description="任务单号")
    projectId: int = Field(..., description="项目空间Id")
    planCase: "ExtCreateTPCase" = Field(..., description="测试用例信息")
    ownerUserCode: str = Field(..., description="目标处理人工号")
    operateUserCode: str = Field(..., description="当前操作人工号")
    comments: str = Field("", description="转单备注")

@router.post("/api/dev/iwhalecloud/transfer_to_code_review")
async def transfer_to_code_review(body: TransferToCodeReviewRequest) -> dict:
    """组合接口：先新增测试用例，再将任务单转到代码走查。
    返回数据格式：{}
    """

    # 步骤1：先创建/绑定任务自测用例
    testcase_body = AddTaskTestcaseRequest(
        projectId=body.projectId,
        taskNo=body.taskNo,
        planCase=body.planCase,
    )
    testcase_resp = await _add_task_testcase(testcase_body)
    if isinstance(testcase_resp, dict) and testcase_resp.get("errorcode") not in (None, 0):
        return error_response(502, "新增任务测试用例失败", error=str(testcase_resp))

    # 步骤2：再将任务转到“代码走查”阶段
    transfer_body = TransferTaskStageRequest(
        taskNo=body.taskNo,
        ownerUserCode=body.ownerUserCode,
        operateUserCode=body.operateUserCode,
        taskFlowStageId=DEV_IWHALECLOUD_TASK_STAGE_CODE_AUDIT,
        comments=body.comments,
    )
    transfer_resp = await _transfer_task_stage(transfer_body)
    if isinstance(transfer_resp, dict) and transfer_resp.get("errorcode") not in (None, 0):
        return error_response(502, "转代码走查失败", error=str(transfer_resp))

    return success_response({}, "新增测试用例并转代码走查成功",)


class TransferDemandStageRequest(BaseModel):
    taskNo: str = Field(..., description="需求单号")
    ownerUserCode: str = Field(..., description="目标处理人工号")
    operateUserCode: str = Field(..., description="当前操作人工号")
    taskFlowStageId: int = Field(..., description="目标状态ID")
    comments: str = Field("", description="转单备注")

def _build_transfer_demand_stage_payload(body: TransferDemandStageRequest) -> dict:
    return {
        "ownerUserCode": body.ownerUserCode,
        "operateUserCode": body.operateUserCode,
        "taskFlowStageId": body.taskFlowStageId,
        "comments": body.comments or "",
    }

@router.post("/api/dev/iwhalecloud/transfer_demand_stage")
async def transfer_demand_stage(body: TransferDemandStageRequest) -> dict:
    """
    功能：将需求单流转到指定状态并指定处理人。
    用法：传入需求单号、目标处理人工号、当前操作人工号、目标状态ID、转单备注，将需求单流转到指定状态并指定处理人。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "code": "9999",
        "data": true,
        "msg": "",
        "message": "",
        "finalMessage": ""
    转调：POST /portal/ai-gateway/devspace/rpc/v3/task/{taskNo}/stage，返回码code为“9999”表示成功
    """
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task/{body.taskNo}/stage"
    payload = _build_transfer_demand_stage_payload(body)
    logger.debug("transfer_demand_stage url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("transfer_demand_stage", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云转需求单接口异常: %s", exc)
        return error_response(503, f"调用研发云需求单转单接口异常: {exc}")
    return _forward_response(resp)



class CreateCommentRequest(BaseModel):
    taskNo: str = Field(..., description="任务单号")
    comments: str = Field(..., description="评论内容")

def _build_create_comment_payload(body: CreateCommentRequest) -> dict:
    return {"comments": body.comments}

@router.post("/api/dev/iwhalecloud/create_comment")
async def create_comment(body: CreateCommentRequest):
    """
    功能：新增评论。
    用法：传入任务单号、评论内容，新增评论。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "code": "9999",
        "data": true,
        "msg": "",
        "message": "",
        "finalMessage": ""
    }
    转调：POST /portal/ai-gateway/devspace/rpc/v3/task/task-no/{taskNo}/comment，返回码code为“9999”表示成功
    """
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task/task-no/{body.taskNo}/comment"
    payload = _build_create_comment_payload(body)
    logger.debug("create_comment url:%s, payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("create_comment", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云新增评论接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    return _forward_response(resp)



class GetImpactListFromDemandRequest(BaseModel):
    demandId: int = Field(..., description="需求ID")

def _build_get_impact_list_from_demand_headers(x_csrf_token: str, cookie: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "FNeyD8V9VNGQ",
        "app-signature": "0e4462ed910fc82cc46cdf8cb37ca7b0a132f330313d6652967d2d6429f0e0e8",
        "app-timestamp": "1774182080150",
        "menu-id": "auto-4efb52a18be660c520233131383333373031",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": x_csrf_token,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookie,
    }

def _filter_task_impact_evaluate_y(data: dict) -> list[dict]:
    """仅保留 adTaskImpact.evaluateResult == Y 的项，并抽取指定字段。"""
    rows = data.get("data")
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ad = row.get("adTaskImpact")
        if not isinstance(ad, dict) or ad.get("evaluateResult") != "Y":
            continue
        out.append(
            {
                "taskImpactId": ad.get("taskImpactId"),
                "impactName": ad.get("impactName"),
                "impactDesc": ad.get("impactDesc"),
                "createUserId": ad.get("createUserId"),
            }
        )
    return out

@router.post("/api/dev/iwhalecloud/get_impact_list_from_demand")
async def get_impact_list_from_demand(body: GetImpactListFromDemandRequest) -> dict:
    """对外路由：根据需求单ID获取影响列表（内部复用 _get_impact_list_from_demand）。
    功能：根据需求单ID获取影响列表。
    用法：传入需求单ID，获取影响列表。
    接口类型：研发云界面抓取请求（研发平台 --> 需求管理 --> 需求详情）
    返回数据格式：[
        {
            "taskImpactId": 123,
            "impactName": "影响点名称",
            "impactDesc": "影响点描述",
            "createUserId": "创建人工号",
        }
    ]
    转调：GET /portal/zcm-devspace/task/{demandId}/impact?_=timestamp，返回码code为“9999”表示成功
    """
    return await _get_impact_list_from_demand(body)

async def _get_impact_list_from_demand(body: GetImpactListFromDemandRequest) -> dict:
    """
    内部调用：根据需求单ID获取影响列表。

    转调：GET /portal/zcm-devspace/task/{demandId}/impact?_=timestamp
    返回 data 中为 evaluateResult=Y 的 adTaskImpact 子集，字段：
    taskImpactId, impactName, impactDesc, createUserId
    """
    try:
        csrf, ck = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{body.demandId}/impact"
    params = {"_": str(int(datetime.now().timestamp() * 1000))}
    headers = _build_get_impact_list_from_demand_headers(csrf, ck)
    logger.debug("get_impact_list_from_demand demandId=%s url:%s params:%s headers:%s", body.demandId, url, params, headers)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_impact_list_from_demand", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云任务影响列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云接口调用失败：{resp.text}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")

    # 提取数据
    filtered = _filter_task_impact_evaluate_y(raw)
    return success_response(filtered)


class GetImpactListFromTaskRequest(BaseModel):
    taskId: int = Field(..., description="任务ID（研发单）")

def _build_get_impact_list_from_task_headers(x_csrf_token: str, cookie: str) -> dict:
    """与浏览器 GET /task/{id}/impact/detail 抓包一致。"""
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "1TqvYZA26k8R",
        "app-signature": "6c636637eaa496b530c927b23b76aa51641ff2c6735daafacea17a89387f4ada",
        "app-timestamp": "1774183359579",
        "menu-id": "auto-4efb52a18be660c520233131383333373031",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": x_csrf_token,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookie,
    }

def _map_impact_detail_task_impact_id_desc(data: dict) -> list[dict]:
    """遍历 data，抽取每条 adTaskImpactDetail 的 taskImpactId、impactDesc。"""
    rows = data.get("data")
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        detail = row.get("adTaskImpactDetail")
        if not isinstance(detail, dict):
            continue
        out.append(
            {
                "taskImpactId": detail.get("taskImpactId"),
                "impactDesc": detail.get("impactDesc"),
            }
        )
    return out

@router.post("/api/dev/iwhalecloud/get_impact_list_from_task")
async def get_impact_list_from_task(body: GetImpactListFromTaskRequest) -> dict:
    """对外路由：根据任务ID获取影响列表（内部复用 _get_impact_list_from_task）。
    功能：根据任务ID获取影响列表。
    用法：传入任务ID，获取影响列表。
    接口类型：研发云界面抓取请求（研发平台 --> 事务管理 --> 任务详情）
    返回数据格式：[
        {
            "taskImpactId": 123,
            "impactDesc": "影响点描述",
        }
    ]
    转调：GET /portal/zcm-devspace/task/{taskId}/impact/detail?_=timestamp，返回码code为“9999”表示成功
    """
    return await _get_impact_list_from_task(body)

async def _get_impact_list_from_task(body: GetImpactListFromTaskRequest) -> dict:
    """
    内部调用：根据任务ID获取影响明细列表。

    转调：GET /portal/zcm-devspace/task/{taskId}/impact/detail?_=timestamp
    返回 data 中每条 adTaskImpactDetail 的 taskImpactId、impactDesc 组成的数组。
    """
    try:
        csrf, ck = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{body.taskId}/impact/detail"
    params = {"_": str(int(datetime.now().timestamp() * 1000))}
    headers = _build_get_impact_list_from_task_headers(csrf, ck)
    logger.debug("get_impact_list_from_task taskId=%s url:%s params:%s headers:%s", body.taskId, url, params, headers)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("get_impact_list_from_task", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云任务影响明细列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    if resp.status_code >= 400:
        return error_response(resp.status_code, f"研发云接口调用失败：{resp.text}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))

        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")

    # 提取数据
    mapped = _map_impact_detail_task_impact_id_desc(raw)
    return success_response(mapped)


class GetTaskListFromDemandRequest(BaseModel):
    demandNo: str = Field(..., description="需求单号")

@router.post("/api/dev/iwhalecloud/get_task_list_from_demand")
async def get_task_list_from_demand(body: GetTaskListFromDemandRequest) -> dict:
    """对外路由：根据需求单号获取任务列表，默认不包含弱关联任务（内部复用 _get_task_list_from_demand）。
    功能：根据需求单号获取任务列表，默认不包含弱关联任务。
    用法：传入需求单号，获取任务列表。
    接口类型：研发云提供标准API接口
    返回数据格式：[
        {
            "taskNo": "任务单号"
        }
    ]
    转调：GET /portal/ai-gateway/devspace/rpc/v3/user-story/{demandNo}/work-items，返回码code为“9999”表示成功
    """
    return await _get_task_list_from_demand(body)

async def _get_task_list_from_demand(body: GetTaskListFromDemandRequest) -> dict:
    """内部调用：根据需求单号获取任务列表，默认不包含弱关联任务。"""
    if not body.demandNo:
        return error_response(400, "demandNo 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/user-story/{body.demandNo}/work-items"
    params = {"withWeakRela": "false"}
    headers = _headers("application/x-www-form-urlencoded")
    logger.debug("_get_task_list_from_demand url:%s params:%s headers:%s", url, params, headers)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            _log_httpx_response("_get_task_list_from_demand", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云根据需求单查询任务列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))
            
        if not isinstance(raw.get("data"), list):
            return error_response(502, f"研发云返回数据data非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")
    
    # 提取数据
    simplified = [
        {
            "taskNo": it.get("taskNo")
        }
        for it in raw.get("data")
    ]
    return success_response(simplified)


class GetTaskPatchRequest(BaseModel):
    taskId: int = Field(..., description="任务ID")

def _build_get_task_patch_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "kXGjFr8Pwf58",
        "app-signature": "5b3f412c3fb57ecb73281c5b50aa35de1547a833f64502d6641483bd0897ec83",
        "app-timestamp": "1774343571168",
        "content-type": "application/json",
        "menu-id": "auto-4efb52a18be660c520233130393239333630",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_task_patch")
async def get_task_patch(body: GetTaskPatchRequest) -> dict:
    """对外路由：根据任务ID获取任务版本信息（内部复用 _get_task_patch）。
    功能：根据任务ID获取任务版本信息。
    用法：传入任务ID，获取任务版本信息。
    接口类型：研发云界面抓取请求（研发平台 --> 事务管理 --> 任务详情）
    返回数据格式：{
        "patchName": "补丁计划名称"
    }
    转调：GET /portal/zcm-devspace/task/{taskId}/detail?_=timestamp，返回码code为“9999”表示成功
    """
    return await _get_task_patch(body)

async def _get_task_patch(body: GetTaskPatchRequest) -> dict:
    """内部调用：根据任务ID获取任务版本信息。"""
    if not body.taskId:
        return error_response(400, "taskId 不能为空")
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/{body.taskId}/detail"
    headers = _build_get_task_patch_headers(csrf, cookies)
    payload = {
        "withAttach": True,
        "withBranchVersion": True,
        "withOwnerUser": True,
        "withParticipant": False,
        "withProductModule": True,
        "withProject": True,
        "withRelatedResourceCount": False,
        "withSprint": True,
        "withTag": False,
        "withTaskFlow": True,
        "withTaskFlowStage": True,
        "withTaskType": True,
        "withContractProject": True,
        "withZmpProject": True,
        "withPatch": True,
        "withProjectGroup": True,
        "withProjectSetting": True,
        "withTaskSrc": True,
        "withTaskExtendEdo": False,
        "withParent": True,
    }

    logger.debug("get_task_patch url:%s payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            _log_httpx_response("get_task_patch", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云查询任务版本信息接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))

        if not isinstance(raw.get("data"), dict):
            return error_response(502, f"研发云返回数据data非字典：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")

    # 提取数据
    patch_name = (raw.get("data") or {}).get("adPatch").get("patchName")
    return success_response({"patchName": patch_name})


class GetFlowIdByModuleRequest(BaseModel):
    projectId: int = Field(..., description="项目ID")
    productModuleId: int = Field(..., description="应用模块ID")

def _build_get_flow_id_by_module_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "cZIf1j7FxzJW",
        "app-signature": "f5475ec7247ed9c6dbc177b53932d251f08bff1f0120491b704ec472da07c2df",
        "app-timestamp": "1774345178729",
        "content-type": "application/json",
        "menu-id": "auto-63017eed96c66210",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }
# 
@router.post("/api/dev/iwhalecloud/get_flow_id_by_module")
async def get_flow_id_by_module(body: GetFlowIdByModuleRequest) -> dict:
    """对外路由：根据应用模块ID查询 CI 流程ID列表（内部复用 _get_flow_id_by_module）。
    功能：根据应用模块ID查询 CI 流程ID列表。
    用法：传入项目ID、应用模块ID，获取 CI 流程ID列表。
    接口类型：研发云界面抓取请求（持续构建 --> 按模块过滤 --> 试飞构建）
    返回数据格式：[
        {
            "flowId": "流程ID"
        }
    转调：POST /portal/zcm-cicd/ciFlowController/getCiFlowListByFlowIdOrFlowName，返回码code为“9999”表示成功
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-cicd/ciFlowController/getCiFlowListByFlowIdOrFlowName"
    params = {"page": 1, "limit": 20}
    headers = _build_get_flow_id_by_module_headers(csrf, cookies)
    payload = {
        "async": False,
        "showMask": True,
        "projectID": body.projectId,
        "filterType": 10,
        "filterValue": body.productModuleId,
        "ciCheckFlagList": [1, 4, 5],
        "cicdTypeId": None,
        "orderType": 0,
        "searchType": "0",
    }
    logger.debug("get_flow_id_by_module url:%s params:%s payload:%s", url, params, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            _log_httpx_response("get_flow_id_by_module", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云按模块查询流程ID接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))

        if not isinstance(raw.get("data").get("content"), list):
            return error_response(502, f"研发云返回数据data.content非列表：{resp.text}")
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")
    
    # 提取数据
    simplified = [
        {
            "flowId": it.get("flowId")
        }
        for it in raw.get("data").get("content")
    ]
    return success_response(simplified)



class GetTaskBranchChangesContentRequest(BaseModel):
    taskNo: str = Field(..., description="任务单号")

@router.post("/api/dev/iwhalecloud/get_task_branch_changes_content")
async def get_task_branch_changes_content(body: GetTaskBranchChangesContentRequest) -> dict:
    f"""根据任务单号查询代码变动明细（默认返回文件内容）。
    功能：根据任务单号查询代码变动明细（默认返回文件内容）。
    用法：传入任务单号，查询代码变动明细（默认返回文件内容）。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "branchInfo": {
            "branchName": "分支名称",
            "repoUrl": "仓库URL",
            "productModuleName": "应用模块名称"
        },
        "changeFileDetailList": [
            {
                "filePath": "文件路径",
                "operType": "操作类型",
                "diffContent": "差异内容",
            }
        ]
    }
    转调：POST /portal/ai-gateway/devspace/rpc/v3/task-branch/{body.taskNo}/changes/content，返回码code为“9999”表示成功
    """
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task-branch/{body.taskNo}/changes/content"
    payload = {"withContent": "true"}
    logger.debug("get_task_branch_changes_content url:%s payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("get_task_branch_changes_content", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云查询任务代码变动明细接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))
            
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")
    
    # 提取数据
    branch_info = raw.get("data").get("branchInfo")
    change_file_detail_list = [
        {
            "filePath": it.get("filePath"),
            "operType": it.get("operType"),
            "diffContent": it.get("diffContent"),
        }
        for it in raw.get("data").get("changeFileDetailList")
    ]
    return success_response({"branchInfo": branch_info, "changeFileDetailList": change_file_detail_list})
    

class GetDemandListFromProductRequest(BaseModel):
    projectId: int = Field(..., description="项目空间ID")
    userId: int = Field(..., description="登录用户ID（loginUserId）")
    productVersionIdList: list[str] = Field(..., description="产品版本ID列表（字符串数组）")
    taskFlowStageTypeList: list[str] = Field(default_factory=lambda: ["FINISH"], description="任务阶段类型列表（字符串数组）")
    createdDateFrom: str = Field("", description="创建日期开始时间，格式：yyyy-MM-dd")
    createdDateTo: str = Field("", description="创建日期结束时间，格式：yyyy-MM-dd")

def _build_get_demand_list_from_product_headers(csrf: str, cookies: str) -> dict:
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "app-nonce": "5KUUVcxes0mP",
        "app-signature": "5c5f905d91ad59b161bdfa1f1d448ab126d5b5e177749d6af4e305c38dbf1c5b",
        "app-timestamp": "1774422790264",
        "content-type": "application/json",
        "menu-id": "auto-97006c427ba17406",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-csrf-token": csrf,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookies,
    }

@router.post("/api/dev/iwhalecloud/get_demand_list_from_product")
async def get_demand_list_from_product(body: GetDemandListFromProductRequest) -> dict:
    """对外路由：根据产品版本ID列表查询需求列表（内部复用 _get_demand_list_from_product）。
    功能：根据产品版本ID列表查询需求列表。
    用法：传入项目空间ID、登录用户ID、产品版本ID列表、任务阶段类型列表、创建日期开始时间、创建日期结束时间，查询需求列表。
    接口类型：研发云界面抓取请求（研发平台 --> 需求管理）
    返回数据格式：[
        {
            "taskNo": "需求单号",
            "taskId": "需求ID",
            "taskTitle": "需求名称",
            "comments": "需求描述",
            "taskSrc": "需求类型",
            "taskPriId": "需求优先级",
            "stageName": "任务阶段名称",
            "expectWorkMinutes": "设计工时",
            "sccbWorkMinutes": "预估工时",
            "createdDate": "创建日期",
            "finishDate": "完成日期",
            "designUserDto": {
                "userName": "设计人员名称",
                "userCode": "设计人员工号",
            },
            "devUserDto": {
                "userName": "开发人员名称",
                "userCode": "开发人员工号",
            },
            "patchName": "应用模块版本名称",
            "productVersionId": "产品版本ID",
            "branchName": "产品分支名称",
            "branchVersionId": "产品分支版本ID",
        }
    ]
    转调：POST /portal/zcm-devspace/task/page-list，返回码code为“9999”表示成功
    """
    try:
        csrf, cookies = await _ensure_valid_creds_async()
    except ValueError as e:
        return error_response(400, str(e))
    if not body.projectId:
        return error_response(400, "projectId 不能为空")
    if not body.productVersionIdList:
        return error_response(400, "productVersionIdList 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/zcm-devspace/task/page-list"
    params = {"page": 1, "limit": 100000}
    headers = _build_get_demand_list_from_product_headers(csrf, cookies)
    payload = {
        "sort": "CREATED_DATE_LATEST",
        "tagIdList": [],
        "taskFlowStageTypeList": body.taskFlowStageTypeList,
        "createdDateFrom": body.createdDateFrom,
        "createdDateTo": body.createdDateTo,
        "productVersionIdList": body.productVersionIdList,
        "taskFieldQueryDtoList": [],
        "loginUserId": body.userId,
        "taskFlowStageIdList": [],
        "orderBy": "CREATED_DATE",
        "orderMode": "DESC",
        "taskDetailConditionDto": {
            "withSprint": False,
            "withPatch": True,
            "withTaskFlowStage": True,
            "withTaskType": True,
            "withOwnerUser": True,
            "withProductModule": True,
            "withProductVersion": True,
            "withRelatedResourceCount": True,
            "withTag": True,
            "withProject": True,
            "withParent": True,
            "withZmpProject": True,
            "withProjectSetting": True,
            "withTaskSrc": True,
            "withBranchVersion": True,
            "withTaskPlan": True,
            "withTaskAnalysis": False,
            "withTaskField": False,
            "withTaskExtendEdo": False,
            "withEdoSprint": False,
        },
        "taskTypeCode": "USER_STORY",
        "currentProjectId": body.projectId,
        "projectIdList": None,
    }
    logger.debug("get_demand_list_from_product url:%s params:%s payload:%s", url, params, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            _log_httpx_response("get_demand_list_from_product", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云按产品版本查询需求列表接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    
    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))
            
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")
    
    # 提取数据
    simplified = [
        {
            "taskNo": it.get("taskNo"),
            "taskId": it.get("taskId"),
            "taskTitle": it.get("taskTitle"),
            "comments": it.get("comments"),
            "taskSrc": it.get("taskSrc"),
            "taskPriId": it.get("taskPriId"),
            "stageName": it.get("adTaskFlowStage").get("stageName"),
            "expectWorkMinutes": it.get("expectWorkMinutes"),
            "sccbWorkMinutes": it.get("sccbWorkMinutes"),
            "createdDate": it.get("createdDate"),
            "finishDate": it.get("finishDate"),
            "designUserDto": it.get("designUserDto"),
            "devUserDto": it.get("devUserDto"),
            "patchName": it.get("adPatch").get("patchName"),
            "productVersionId": it.get("adPatch").get("productVersionId"),
            "branchName": it.get("adPatch").get("branchName"),
            "branchVersionId": it.get("adPatch").get("branchVersionId"),
        }
        for it in raw.get("data").get("list")
    ]
    return success_response(simplified)



class ExtCreateTPCaseStep(BaseModel):
    seqId: int = Field(1, description="Index, 用例中的步骤顺序，从1开始")
    stepDesc: str = Field(..., description="用例步骤描述")
    result: str = Field(..., description="测试预期结果")
    actualResult: str = Field(..., description="测试实际结果")
    status: int = Field(1,description="测试步骤状态:0 未执行，1 通过，2 部分通过，3 不通过，4 阻塞，5 跳过；默认 1")

class ExtCreateTPCase(BaseModel):
    caseName: str = Field(..., description="用例名称")
    assignedUserCode: str = Field(..., description="用例负责人工号（如 0027012345）")
    stepList: list[ExtCreateTPCaseStep] = Field(..., description="用例步骤")

    # 用例级别字段（默认值来源于接口说明）
    angle: int = Field(0, description="测试角度:0 开发角度，1 测试角度；默认 0")
    caseType: int = Field(0, description="用例类型: 默认 0（功能）")
    caseState: int = Field(2, description="测试用例状态: 默认 2（通过）")
    caseLevel: int = Field(2, description="测试用例等级: 默认 2（P2）")
    caseCode: str = Field("", description="用例编码")
    enterType: str = Field("text", description="输入模式:text 文本单步骤，step 多步骤，attach 附件描述用例；默认 text")
    precondition: str = Field(..., description="前置条件")
    note: str = Field("智能研发助手自动化测试", description="备注")
    markdownToTiptap: str = Field("N", description="markdownToTiptap: Y 转化为Tiptap格式，N 否；默认 N")

class AddTaskTestcaseRequest(BaseModel):
    projectId: int = Field(..., description="项目空间Id")
    taskNo: str = Field(..., description="绑定的事务单号")
    planCase: ExtCreateTPCase = Field(..., description="测试用例信息")

@router.post("/api/dev/iwhalecloud/add_task_testcase")
async def add_task_testcase(body: AddTaskTestcaseRequest) -> dict:
    """对外路由：给任务新增自测用例（内部复用 _add_task_testcase）。
    功能：给任务新增自测用例。
    用法：传入项目空间Id、任务单号、测试用例信息，给任务新增自测用例。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "code": "9999",
        "data": {},
        "msg": ""
    }
    """
    return await _add_task_testcase(body)

async def _add_task_testcase(body: AddTaskTestcaseRequest) -> dict:
    """内部调用：给任务新增自测用例。"""
    if not body.taskNo:
        return error_response(400, "taskNo 不能为空")

    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/cloudtest/rpc/v3/tm/plan/case/add/rela"
    upstream_payload: dict = {
        "taskNo": body.taskNo,
        "projectId": body.projectId,
        "planCase": body.planCase.model_dump(),
    }
    logger.debug("add_task_testcase url:%s payload:%s", url, upstream_payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=upstream_payload)
            _log_httpx_response("add_task_testcase", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云新增任务自测用例接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    return _forward_response(resp)



class GetOrderDetailRequest(BaseModel):
    orderNo: str = Field(..., description="工单号")

@router.post("/api/dev/iwhalecloud/get_order_detail")
async def get_order_detail(body: GetOrderDetailRequest) -> dict:
    f"""对外路由：根据工单号获取工单详情（内部复用 _get_order_detail）。
    功能：根据工单号获取工单详情。
    用法：传入工单号，获取工单详情。
    接口类型：研发云提供标准API接口
    返回数据格式：{
        "taskId": "任务ID",
        "taskNo": "任务单号",
        "taskTitle": "任务标题",
        "comments": "任务描述",
        "taskPriId": "任务优先级",
        "regressionCount": "回退次数",
        "stageName": "任务阶段名称",
        "expectWorkMinutes": "预计工时",
        "createdDate": "创建日期",
        "finishDate": "完成日期",
        "branchName": "产品分支名称",
        "projectId": "项目空间ID",
        "productModuleDto": {
            "productModuleId": "应用模块ID",
            "productModuleName": "应用模块名称",
        },
        "taskActionDtoList": [
            {
                "fieldName": "修改字段名称",
                "oldValueDesc": "修改之前的旧值描述",
                "newValue": "修改之后的新值",
                "newValueDesc": "修改之后的新值描述",
                "userName": "修改人员名称",
                "userCode": "修改人员工号"
            }
        ]
    }
    转调：POST /portal/ai-gateway/devspace/rpc/v3/work-item/{body.orderNo}/detail，返回码code为“9999”表示成功
    """
    return await _get_order_detail(body)

async def _get_order_detail(body: GetOrderDetailRequest) -> dict:
    """内部调用：根据工单号获取工单详情。"""
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/work-item/{body.orderNo}/detail"
    payload = {
        "withTaskFlowStage": "true",
        "withOwnerUser": "true",
        "withProductModule": "true",
        "withAction": "true",
        "withParent": "true",
        "withTaskDoc": "true",
        "withDevCase": "true",
        "withTestCase": "true",
        "withTaskType": "true",
        "withProductVersion": "true",
        "withBranchVersion": "true",
        "withAttach": "true",
        "withEdo": "true",
        "withTaskImpact": "true",
        "withConfig": "true",
        "withAllTaskType": "true"
    }
    logger.debug("_get_order_detail url:%s payload:%s", url, payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
            _log_httpx_response("_get_order_detail", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云获取工单详情接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")

    # 检查数据格式
    try:
        raw = resp.json()
        # 检查返回码
        if raw.get("code") != "9999":
            msg = raw.get("finalMessage") or raw.get("msg") or raw.get("message") or "研发云执行失败"
            return error_response(502, f"{msg}", error=str(raw))
    except ValueError:
        return error_response(502, f"研发云返回非 JSON：{resp.text}")
    
    # 提取数据
    taskActionDtoList = [
        {
            "fieldName": it.get("adTaskAction").get("fieldName"),
            "oldValueDesc": it.get("adTaskAction").get("oldValueDesc"),
            "newValue": it.get("adTaskAction").get("newValue"),
            "newValueDesc": it.get("adTaskAction").get("newValueDesc"),
            "userName": it.get("createUserDto").get("userName"),
            "userCode": it.get("createUserDto").get("userCode"),
        }
        for it in raw.get("data").get("taskActionDtoList")
    ]

    productModuleDto = None
    # 检查apiProductModule不为None且不为{}
    if raw.get("data").get("apiProductModule") is not None and raw.get("data").get("apiProductModule") != {}:
        productModuleDto = {
            "productModuleId": raw.get("data").get("apiProductModule").get("productModuleId"),
            "productModuleName": raw.get("data").get("apiProductModule").get("productModuleName"),
        }

    simplified = {
        "taskId": raw.get("data").get("apiTask").get("taskId"),
        "taskNo": raw.get("data").get("apiTask").get("taskNo"),
        "taskTitle": raw.get("data").get("apiTask").get("taskTitle"),
        "comments": raw.get("data").get("apiTask").get("comments"),
        "taskPriId": raw.get("data").get("apiTask").get("taskPriId"),
        "regressionCount": raw.get("data").get("apiTask").get("regressionCount"),
        "stageName": raw.get("data").get("apiTaskFlowStage").get("stageName"),
        "expectWorkMinutes": raw.get("data").get("apiTask").get("expectWorkMinutes"),
        "createdDate": raw.get("data").get("apiTask").get("createdDate"),
        "finishDate": raw.get("data").get("apiTask").get("finishDate"),
        "branchName": raw.get("data").get("apiBranchVersionDto").get("branchName"),
        "projectId": raw.get("data").get("apiTask").get("projectId"),
        "productModuleDto": productModuleDto,
        "taskActionDtoList": taskActionDtoList
    }

    return _forward_response(simplified)


async def _get_task_current_stage(task_no: str) -> dict:
    """内部调用：根据任务单号查询任务当前状态。"""
    url = f"{DEV_IWHALECLOUD_BASE_URL}/portal/ai-gateway/devspace/rpc/v3/task/{task_no}/stage"
    logger.debug("_get_task_current_stage url:%s", url)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_headers())
            _log_httpx_response("_get_task_current_stage", resp)
    except httpx.RequestError as exc:
        logger.exception("调用研发云查询任务状态接口异常: %s", exc)
        return error_response(503, f"调用研发云接口异常: {exc}")
    return _forward_response(resp)



################ 研发云代码合并 start ####################
def _git_embed_frame(page: Page) -> FrameLocator:
    """
    研发云把 Git 对比/合并页嵌在 iframe 里（src 含 git 域名与 compare）。
    必须用 frame_locator，在子文档里点按钮；page.locator 永远找不到 iframe 内节点。
    """
    return page.frame_locator("iframe[src*='compare/master']").first

def _wait_git_iframe(page: Page, timeout_ms: int = 90_000) -> None:
    page.locator("iframe[src*='compare/master']").first.wait_for(state="attached", timeout=timeout_ms)
    # iframe 内文档加载
    page.wait_for_timeout(120)

def _find_git_child_frame(page: Page):
    """门户 main 帧之外的 Git 嵌入帧（对比/合并页）。"""
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        u = (fr.url or "").lower()
        if "git-nj.iwhalecloud.com" in u and ("/compare/" in u or "/pulls/" in u):
            return fr
    return None

def _wait_git_frame_network_idle(page: Page, timeout_ms: int = 120_000) -> None:
    """
    在 Git iframe 内操作后应等「子帧」网络空闲。
    page.wait_for_load_state 只针对主框架，iframe 里仍在请求时也会误判为已 idle。
    """
    fr = _find_git_child_frame(page)
    if fr is not None:
        fr.wait_for_load_state("networkidle", timeout=timeout_ms)
    else:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)

def _reload_git_iframe_only(page: Page) -> None:
    """
    只刷新嵌入的 Git 页，不 page.reload()。
    整页刷新会重建门户 SPA，已打开的多 Tab 会丢；仅子 frame reload 可保留 Tab。
    """
    fr = _find_git_child_frame(page)
    if fr is None:
        raise RuntimeError("未找到 Git 嵌入 iframe，无法仅刷新合并分支内容")
    fr.evaluate("location.reload()")
    fr.wait_for_load_state("networkidle", timeout=120_000)

def _page_has_merged_text(target: Page, timeout_ms: int = 800) -> bool:
    """在主页面或子 frame 中检测是否出现「已合并」状态标签或文案。"""
    selectors = [
        "div.issue-state-label:has-text('已合并')",
        ".issue-state-label:has-text('已合并')",
        "div.ui.purple.label:has-text('已合并')",
    ]
    for sel in selectors:
        try:
            loc = target.locator(sel).first
            if loc.count() and loc.is_visible(timeout=timeout_ms):
                return True
        except PlaywrightTimeoutError:
            continue
    try:
        if target.get_by_text("已合并", exact=True).first.is_visible(timeout=timeout_ms):
            return True
    except PlaywrightTimeoutError:
        pass
    return False

def _wait_for_merge_success(page: Page, total_timeout_ms: int = 120_000) -> bool:
    """
    等待合并完成：界面出现「已合并」即成功。

    实现要点（已按你们页面简化）：
    - 「已合并」状态块在 **Git 嵌入 iframe** 内（如 /compare/ 或 /pulls/xxx），主门户 document 里没有该节点。
    - 不再遍历 `page.frames` 与主帧，只通过 `_find_git_child_frame` 定位同一类 Git 帧并轮询检测。
    - 若 iframe 尚未挂上（导航中），本轮跳过，sleep 后继续直到 total_timeout_ms。
    """
    deadline = time.time() + total_timeout_ms / 1000
    while time.time() < deadline:
        fr = _find_git_child_frame(page)
        if fr is not None:
            try:
                if _page_has_merged_text(fr, timeout_ms=800):
                    return True
            except Exception:
                pass
        time.sleep(0.35)
    return False

class CodeMergeRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    taskNo: str = Field(..., description="任务单号")

@router.post("/api/dev/iwhalecloud/code_merge")
def code_merge(body: CodeMergeRequest):
    with sync_playwright() as p:
        # 启动浏览器（headless=True 表示后台运行，不显示界面）
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # 设置请求超时时间为60秒
            context.set_default_timeout(60_000)
            page.set_default_timeout(60_000)
            page.set_default_navigation_timeout(60_000)

            # 访问登录页面
            page.goto(DEV_IWHALECLOUD_BASE_URL) 
            print("打开研发云界面成功")

            # 定位并填写表单
            page.fill('#edt_username', body.username)
            page.fill('#edt_pwd', body.password)
            print("填写用户名和密码成功")

            # 点击登录按钮，进入研发平台界面
            page.click('.loginBtn')
            page.wait_for_load_state("networkidle") 
            print("登录成功")

            # 点击任务单数，进入事务管理界面
            page.locator('span.my-todo-item-pending-count[data-type="WORK_ITEM"]').click()
            page.wait_for_load_state("networkidle") 
            print("进入事务管理界面成功")
            
            # 回填 任务单号，搜索任务
            page.locator("input.task-search-text").fill(body.taskNo)
            page.locator(".search-click-task").click()
            page.wait_for_load_state("networkidle")
            print("搜索任务成功")

            # 点击任务标题，进入任务详情界面
            num = re.sub(r"[^\d]", "", str(body.taskNo))
            page.locator(f'div.task-title[data-taskno="{num}"]').click()
            page.wait_for_load_state("networkidle")
            print("进入任务详情界面成功")
            
            # 点击代码分支，进入代码分支界面
            page.locator('#details-content-tabs a[href="#codeBranchTab"]').click()
            page.wait_for_load_state("networkidle")
            print("进入代码分支界面成功")
            
            # 任务详情-代码分支页面-点击创建合并请求
            page.locator("button.merge-branch-btn").click()
            page.wait_for_load_state("networkidle")
            print("任务详情-代码分支页面-点击创建合并请求成功")
            
            # 合并对比在 iframe 内，先等 iframe 出现再点（page.locator 无法穿透 iframe）
            _wait_git_iframe(page)
            git_frame = _git_embed_frame(page)
            
            # 合并分支界面-第一次点击创建合并请求
            git_frame.locator("button.ui.button.primary.show-form").filter(has_text="创建合并请求").click()
            _wait_git_frame_network_idle(page)
            print("合并分支界面-第一次点击创建合并请求成功")

            # 合并分支界面-第二次点击创建合并请求（表单仍在同一 Git iframe 内）
            git_frame.locator("form#new-issue").get_by_role("button", name="创建合并请求").click()
            _wait_git_frame_network_idle(page)
            print("合并分支界面-第二次点击创建合并请求成功")

            # 研发云合并检查异步跑在 Git 页内；只刷新嵌入 iframe，避免 page.reload 关掉门户内多 Tab
            time.sleep(10)
            _reload_git_iframe_only(page)
            print("研发云代码合并检查等待结束，已仅刷新合并分支（Git iframe）")

            # reload 后 iframe 会重建，需重新等待再操作 Git 内按钮
            _wait_git_iframe(page)
            git_frame = _git_embed_frame(page)

            # 合并分支界面-第一次点击创建合并提交（研发云合并检查通过）
            git_frame.get_by_role("button", name="创建合并提交").click()
            _wait_git_frame_network_idle(page)
            print("合并分支界面-第一次点击创建合并提交成功")

            # 合并分支界面-第二次点击创建合并提交
            git_frame.locator('form[action*="/merge"] button[type="submit"][name="do"][value="merge"]').click()
            _wait_git_frame_network_idle(page)
            print("合并分支界面-第二次点击创建合并提交成功")

            # 界面出现「已合并」表示成功，否则视为合并失败
            if _wait_for_merge_success(page, total_timeout_ms=120_000):
                return success_response(message="代码合并成功")
            return error_response(500, message=f"代码合并失败，请到研发云上根据单号[{body.taskNo}]查看原因")

        except Exception as e:
            logger.exception("研发单[{body.taskNo}]代码合并异常: %s", e)
            return error_response(500, message=f"研发单[{body.taskNo}]代码合并异常: {str(e)}")
        finally:
            browser.close()

################ 研发云代码合并 end ####################




class LoginRequest(BaseModel):
    """浩鲸研发云登录验证。引导验证或密码修改时可传入工号、密码；其余场景从 userinfo.encryption 读取。"""

    purpose: Literal["normal", "guide", "password_change"] = Field(
        "normal",
        description="normal=从 userinfo.encryption 读工号/密码；guide/password_change=使用请求体中的工号/密码",
    )
    name: str | None = Field(None, description="姓名（引导验证建议传入；亦可登录成功后仅更新密文）")
    username: str | None = Field(None, description="工号，与 password 对应；引导或改密时必填")
    password: str | None = Field(None, description="密码；引导或改密时必填")
    token: str | None = Field(None, description="x-csrf-token 等；可选，未传则尝试从页面请求中捕获")

    @model_validator(mode="after")
    def _require_creds_when_guide(self) -> LoginRequest:
        if self.purpose in ("guide", "password_change"):
            if not (self.username and self.password):
                raise ValueError("引导验证或密码修改时 username（工号）、password 必填")
        return self


def _resolve_iwhalecloud_login_creds(body: LoginRequest) -> tuple[str, str, dict | None]:
    """(工号, 密码, 本地已解密 userinfo；guide 为 None，password_change/normal 可能带 dict)。"""
    if body.purpose == "guide":
        return (body.username or "").strip(), body.password or "", None
    if body.purpose == "password_change":
        u = (body.username or "").strip()
        p = body.password or ""
        prev = _load_userinfo_plain()
        return u, p, prev
    data = _load_userinfo_plain()
    if not data:
        raise ValueError("未找到本地凭据，请先使用 purpose=guide 完成引导验证")
    u = (data.get("employee_id") or data.get("username") or "").strip()
    p = data.get("password") or ""
    if not u or not p:
        raise ValueError("userinfo.encryption 中缺少工号或密码，请使用 purpose=guide 重新引导")
    return u, p, data


@router.get("/api/dev/iwhalecloud/local-userinfo-exists")
def local_userinfo_exists():
    """
    检测当前进程 `settings.project_root` 下是否存在非空的 `data/userinfo.encryption`。

    供 Setup Center 引导等判断「可跳过研发云表单验证」；路径与登录写入逻辑一致，避免桌面端猜测 cwd。
    """
    path = _userinfo_encryption_path()
    try:
        st = path.stat()
        exists = path.is_file() and st.st_size > 0
    except OSError:
        exists = False
    return success_response(
        {
            "exists": exists,
            "path": str(path.resolve()),
            "project_root": str(settings.project_root.resolve()),
        }
    )


class DevserviceIpBody(BaseModel):
    ip: str = Field(..., min_length=1)


@router.get("/api/dev/devservice-ip")
def devservice_ip_get():
    """读取 `synapse_home/devservice.ip`（供 Web 引导与桌面一致）；若无则回退旧路径。"""
    primary = _devservice_ip_path()
    legacy = _devservice_ip_path_legacy()
    ip_val: str | None = None
    chosen = primary
    for path in (primary, legacy):
        if path.is_file():
            try:
                raw = path.read_text(encoding="utf-8").strip()
                if raw:
                    ip_val = raw
                    chosen = path
                    break
            except OSError:
                pass
    return success_response({"ip": ip_val, "path": str(chosen.resolve())})


@router.post("/api/dev/devservice-ip")
def devservice_ip_post(body: DevserviceIpBody):
    """写入产品公共服务主机地址（固定为 synapse_home/devservice.ip）。"""
    t = body.ip.strip()
    if not t:
        return error_response(400, "IP 不能为空")
    path = _devservice_ip_path()
    try:
        settings.synapse_home.mkdir(parents=True, exist_ok=True)
        path.write_text(t + "\n", encoding="utf-8")
    except OSError as e:
        return error_response(500, f"写入失败: {e}")
    return success_response({"ok": True, "path": str(path.resolve())})


class DevserviceProbeBody(BaseModel):
    ip: str = Field(..., min_length=1)


@router.post("/api/dev/devservice-probe")
def devservice_probe(body: DevserviceProbeBody):
    """对七个固定端口做 TCP 连通性探测（与桌面引导一致）。"""
    host = body.ip.strip()
    if not host:
        return error_response(400, "IP 不能为空")
    results = []
    for port in DEVSERVICE_PROBE_PORTS:
        ok, err = _tcp_probe(host, port)
        results.append({"port": port, "ok": ok, "error": err})
    return success_response({"results": results})


@router.get("/api/dev/userinfo-for-unified-service")
def userinfo_for_unified_service():
    """
    供前端调用研发统一服务（:10001）前准备数据：
    - owner_info：userinfo.encryption 文件原文（密文），按接口要求原样传递；
    - owner_name：解密后的姓名，用于 insert_prod_info 的 owner 字段。
    """
    path = _userinfo_encryption_path()
    if not path.is_file():
        return error_response(404, "未找到 userinfo.encryption，请先完成研发云引导登录")
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        return error_response(500, f"读取 userinfo 失败: {e}")
    if not raw:
        return error_response(400, "userinfo.encryption 为空")
    try:
        data = _load_userinfo_plain()
    except ValueError as e:
        return error_response(400, str(e))
    owner_name = (data or {}).get("name") or ""
    return success_response({"owner_info": raw, "owner_name": owner_name})


@router.post("/api/dev/iwhalecloud/login")
def login(body: LoginRequest):
    """
    登录研发云（浩鲸研发云验证流程）。

    验证通过后，将姓名、工号、密码、token 写入 data/userinfo.encryption（foundation.CryptHelper 加密）。
    """
    try:
        username, password, file_user = _resolve_iwhalecloud_login_creds(body)
    except ValueError as e:
        return error_response(400, str(e))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(DEV_IWHALECLOUD_LOGIN_PLAYWRIGHT_TIMEOUT_MS)
        page.set_default_navigation_timeout(DEV_IWHALECLOUD_LOGIN_PLAYWRIGHT_TIMEOUT_MS)

        csrf_token: dict[str, str | None] = {"value": None}
        logged_user_id: dict[str, int | None] = {"value": None}

        def on_request(req) -> None:
            if csrf_token["value"]:
                return
            h = req.headers
            t = h.get("x-csrf-token") or h.get("X-CSRF-Token")
            if t:
                csrf_token["value"] = t

        def on_response(resp) -> None:
            # 登录后浏览器会自动触发 /portal/logged 请求，响应 JSON 中包含 userId
            if logged_user_id["value"] is not None:
                return
            try:
                url = resp.url
            except Exception:
                return
            if "/portal/logged" not in (url or ""):
                return
            try:
                data = resp.json()
            except Exception:
                return
            if isinstance(data, dict):
                uid = data.get("userId")
                if isinstance(uid, int):
                    logged_user_id["value"] = uid

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            page.goto(DEV_IWHALECLOUD_BASE_URL)
            page.fill("#edt_username", username)
            page.fill("#edt_pwd", password)
            page.click(".loginBtn")
            page.wait_for_load_state("networkidle")
            page.reload(wait_until="networkidle")

            logger.debug("login employee_id=%s page_url=%s", username, page.url)

            if "main.html" not in page.url:
                return error_response(401, "账号或密码错误")

            # 等一小会儿让 /portal/logged 响应落地（通常会自动触发）
            for _ in range(30):
                if logged_user_id["value"] is not None:
                    break
                page.wait_for_timeout(100)

            captured = csrf_token["value"]
            token_out = body.token or captured or (file_user or {}).get("token") or ""
            if body.purpose == "guide":
                name_out = body.name if body.name is not None else ""
            elif body.purpose == "password_change":
                name_out = body.name if body.name is not None else (file_user or {}).get("name") or ""
            else:
                name_out = (file_user or {}).get("name") or ""

            ok, err = _save_userinfo_encrypted(
                name=name_out,
                employee_id=username,
                password=password,
                token=token_out,
                user_id=logged_user_id["value"]
            )
            if not ok:
                return error_response(500, err or "保存用户信息失败")

            return success_response({"token": token_out}, "验证通过")
        except FileNotFoundError as e:
            return error_response(500, str(e))
        except ValueError as e:
            return error_response(500, str(e))
        except Exception as exc:
            logger.exception("登录验证出错: %s", exc)
            return error_response(500, f"用户密码验证出错: {exc}")
        finally:
            browser.close()


def _cookies_to_header(cookies: list[dict]) -> str:
    """
    把 Playwright context.cookies() 的结果拼成 Cookie header 字符串。
    获取成功后，将x-csrf-token和cookies保存到本地。
    后续调用研发云接口时，将x-csrf-token和cookies作为请求头传递给研发云接口。

    使用前需要安装playwright和chromium浏览器内核。
    pip install playwright
    playwright install chromium
    """
    parts: list[str] = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if not name:
            continue
        if value is None:
            value = ""
        parts.append(f"{name}={value}")
    return "; ".join(parts)


_iwhalecloud_session_lock = asyncio.Lock()


def _fetch_token_and_cookies_sync(username: str, password: str) -> tuple[str, str]:
    """
    同步：用 Playwright 登录研发云，抓取 **x-csrf-token**（请求头）与 Cookie 串。
    与 userinfo.encryption 里的 API Authorization token 无关，勿混用。
    仅由 _ensure_valid_creds_async 在持有 asyncio.Lock 时经 asyncio.to_thread 调用，故全局已串行；
    进入后若会话文件已写入则直接返回（双检）。
    """
    sess = _load_iwhalecloud_session()
    if sess and (sess.get("token") or "").strip() and (sess.get("cookies") or "").strip():
        return str(sess["token"]), str(sess["cookies"])
    with sync_playwright() as p:
        # 启动 Chromium 浏览器实例。
        # headless=False: 有界面模式，便于本地观察登录过程；如改为 True 则后台无界面运行。
        browser = p.chromium.launch(headless=True)
        # 创建独立浏览器上下文，相当于一个全新的临时浏览器会话（隔离 cookie/localStorage）。
        context = browser.new_context()
        # 在当前上下文中打开一个新页面（Tab）。
        page = context.new_page()
        # 设置默认超时时间为 5 分钟，覆盖 Playwright 默认的 30s
        page.set_default_timeout(DEV_IWHALECLOUD_LOGIN_PLAYWRIGHT_TIMEOUT_MS)
        page.set_default_navigation_timeout(DEV_IWHALECLOUD_LOGIN_PLAYWRIGHT_TIMEOUT_MS)

        try:
            # 用可变容器保存 x-csrf-token，便于在内部回调 on_request 中写入。
            csrf_token = {"value": None}

            def on_request(req):
                # 已获取到 token 就不再重复处理后续请求头。
                if csrf_token["value"]:
                    return
                # req.headers: 当前网络请求头（字典）。
                h = req.headers
                # 兼容大小写两种 header 名，提取 x-csrf-token。
                t = h.get("x-csrf-token") or h.get("X-CSRF-Token")
                # 命中后立即缓存 token，供后续接口调用。
                if t:
                    csrf_token["value"] = t

            # 监听页面发出的每个请求，request 事件触发时执行 on_request 回调。
            page.on("request", on_request)

            # 打开研发云首页。
            # wait_until="domcontentloaded": DOM 解析完成即返回，不必等待全部静态资源。
            page.goto(DEV_IWHALECLOUD_BASE_URL, wait_until="domcontentloaded")
            # 等待网络空闲（networkidle），确保页面初始异步请求基本完成。
            # timeout=60000: 最长等待 60 秒，超时会抛异常。
            page.wait_for_load_state("networkidle", timeout=60000)

            # 向用户名输入框写入账号。
            # "#edt_username": CSS 选择器，定位 id 为 edt_username 的输入框。
            page.fill("#edt_username", username)
            # 向密码输入框写入密码。
            # "#edt_pwd": CSS 选择器，定位 id 为 edt_pwd 的输入框。
            page.fill("#edt_pwd", password)
            # 点击登录按钮发起登录。
            # ".loginBtn": CSS 选择器，定位 class 为 loginBtn 的元素。
            page.click(".loginBtn")
            # 等待登录后网络请求稳定，避免过早读取 token/cookie。
            page.wait_for_load_state("networkidle", timeout=60000)

            # 关闭“研发平台”标签页上的关闭按钮，避免遮挡或影响后续页面状态。
            # li:has-text("研发平台"): 文本匹配到对应标签项。
            # button.ui-tabs-close.close: 该标签项内的关闭按钮。
            try:
                page.locator('li:has-text("研发平台")').locator("button.ui-tabs-close.close").click()
            except PlaywrightTimeoutError:
                # 未出现该标签时跳过（部分环境可能无此 Tab）
                pass

            # 读取在 request 回调中捕获到的 x-csrf-token（非 API Bearer）。
            token = csrf_token["value"]
            if not token:
                raise ValueError("未获取到 x-csrf-token")

            # 读取当前上下文下全部 cookie（列表结构，每项含 name/value/domain/path 等）。
            all_cookies = context.cookies()
            # 将 cookie 列表拼成标准 Cookie 请求头字符串（name=value; name2=value2）。
            cookies = _cookies_to_header(all_cookies)
            logger.debug("获取研发云x-csrf-token和cookies成功: token=[%s], cookies=[%s]", token, cookies)
            _save_iwhalecloud_session(token, cookies)
            return token, cookies
        finally:
            context.close()
            browser.close()


async def _ensure_valid_creds_async(force_refresh: bool = False) -> tuple[str, str]:
    """
    确保拥有有效的 x-csrf-token 和 cookies（存于 data/iwhalecloud_session.json）。
    缺失或 force_refresh 时走 _fetch_token_and_cookies_sync（asyncio 锁串行 + to_thread 写文件）。
    """
    async with _iwhalecloud_session_lock:
        if force_refresh:
            _clear_iwhalecloud_session()
        else:
            sess = _load_iwhalecloud_session()
            if sess and (sess.get("token") or "").strip() and (sess.get("cookies") or "").strip():
                return str(sess["token"]), str(sess["cookies"])

        data = _load_userinfo_plain()
        if not data:
            raise ValueError("未找到本地凭据（userinfo.encryption），请先完成引导验证")
        username = (data.get("employee_id") or data.get("username") or "").strip()
        password = data.get("password") or ""
        if not username or not password:
            raise ValueError("userinfo.encryption 中缺少工号或密码，请重新引导")

        logger.info("正在使用 Playwright 自动获取研发云 x-csrf-token 与 cookies...")
        token, cookies = await asyncio.to_thread(_fetch_token_and_cookies_sync, username, password)
        return token, cookies


class ProductInitializeRequest(BaseModel):
    product_id: int = Field(..., description="产品ID")


def _register_product_knowledge_routes() -> None:
    from synapse.api.routes import dev_iwhalecloud_knowledge
    dev_iwhalecloud_knowledge.register_product_knowledge_routes(router)

_register_product_knowledge_routes()
