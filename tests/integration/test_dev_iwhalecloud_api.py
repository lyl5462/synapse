"""Integration tests: 浩鲸研发云代理 API（dev_iwhalecloud 路由）。

- 校验路由注册与 OpenAPI 暴露
- 校验请求体缺失时的 422 / 业务 errorcode
- 对依赖 httpx 的上游调用使用 mock，避免访问真实 dev.iwhalecloud.com

不默认执行 Playwright 登录类接口（避免拉起浏览器）；仅做入参校验类测试。
"""

from __future__ import annotations

import json

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from synapse.api.routes import dev_iwhalecloud
from synapse.api.server import create_app


@pytest.fixture
async def client():
    app = create_app()
    app.state.agent = None
    app.state.session_manager = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


class TestIwhalecloudOpenAPI:
    async def test_openapi_lists_dev_iwhalecloud_post_routes(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        paths = spec.get("paths") or {}
        iwhale = [p for p in paths if p.startswith("/api/dev/iwhalecloud")]
        assert len(iwhale) >= 32, f"expected >=32 iwhalecloud paths, got {len(iwhale)}: {sorted(iwhale)}"
        for path in iwhale:
            methods = paths[path] or {}
            # 多数为 POST；local-userinfo-exists 为 GET
            if path.rstrip("/").endswith("/local-userinfo-exists"):
                assert methods.get("get") is not None, f"missing GET for {path}"
            else:
                assert methods.get("post") is not None, f"missing POST for {path}"

    # 注意：不要对全部路由无脑 POST {} —— 例如 get_product_list 的 body 有默认值，
    # 空对象会触发对 dev.iwhalecloud.com 的真实 HTTP 调用（长超时）。路由存在性以 OpenAPI 为准即可。


class TestGetProjectList:
    async def test_without_userinfo_returns_business_error(self, client):
        """门户凭据从服务端会话文件拉取；无 userinfo 时无法获取 x-csrf-token。"""
        with patch.object(
            dev_iwhalecloud,
            "_ensure_valid_creds_async",
            new_callable=AsyncMock,
            side_effect=ValueError("未找到本地凭据（userinfo.encryption），请先完成引导验证"),
        ):
            resp = await client.post("/api/dev/iwhalecloud/get_project_list", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("errorcode") == 400
        assert "userinfo" in (data.get("message") or "") or "凭据" in (data.get("message") or "")

    async def test_upstream_json_array_success_simplified(self, client):
        """mock 上游返回 JSON 数组时，路由精简为 projectId/projectName/projectCode。"""

        class _MockClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None, params=None):
                class _Resp:
                    status_code = 200
                    url = "https://dev.iwhalecloud.com/portal/zcm-cmdb/v1/projects/all"
                    text = json.dumps(
                        [
                            {"projectId": 1, "projectName": "P1", "projectCode": "C1", "extra": "x"},
                        ],
                        ensure_ascii=False,
                    )

                    def json(self):
                        return json.loads(self.text)

                return _Resp()

        with (
            patch.object(dev_iwhalecloud, "_ensure_valid_creds_async", new_callable=AsyncMock) as _ensure,
            patch.object(dev_iwhalecloud.httpx, "AsyncClient", _MockClient),
        ):
            _ensure.return_value = ("t", "c=1")
            resp = await client.post("/api/dev/iwhalecloud/get_project_list", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("errorcode") == 0
        lst = data.get("data") or []
        assert len(lst) == 1
        assert lst[0].get("projectId") == 1
        assert lst[0].get("projectName") == "P1"
        assert lst[0].get("projectCode") == "C1"
        assert "extra" not in lst[0]


class TestLoginAndTokenHelpers:
    async def test_login_guide_missing_password_422(self, client):
        resp = await client.post(
            "/api/dev/iwhalecloud/login",
            json={"purpose": "guide", "username": "u001"},
        )
        assert resp.status_code == 422


class TestCreateTaskValidation:
    async def test_empty_body_422(self, client):
        resp = await client.post("/api/dev/iwhalecloud/create_task", json={})
        assert resp.status_code == 422

    async def test_minimal_invalid_body_returns_business_error(self, client):
        """字段齐全但业务校验失败时返回 errorcode 非 0（不发起外呼）。"""
        body = {
            "taskNo": "",
            "taskTitle": "t",
            "comments": "c",
            "ownerUserCode": "o",
            "projectId": 1,
            "productModuleName": None,
            "branchVersionName": "br",
            "mainBranchVersionTaskNo": "",
            "taskClassification": "FUNCTION",
            "taskPri": 5,
            "patchName": "p",
            "userId": 1,
            "taskImpactList": [{"taskImpactId": 1, "taskImpactDesc": "d"}],
            "performanceImpact": "a",
            "functionalImpact": "b",
            "cfgChangeDescription": "c",
            "upgradeRisk": "d",
            "securityImpact": "e",
            "compatibilityImpact": "f",
        }
        resp = await client.post("/api/dev/iwhalecloud/create_task", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("errorcode") != 0
        assert data.get("message")


class TestGetModuleNameList:
    async def test_upstream_params_include_project_and_product_version_id(self, client):
        """研发云 getModuleList 传入 projectId 与 productVersionId。"""
        captured: dict[str, object] = {}

        class _MockClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None, params=None):
                captured["params"] = dict(params or {})
                captured["url"] = url
                req_url = url

                class _Resp:
                    status_code = 200
                    url = req_url
                    text = json.dumps({"code": "9999", "data": {"list": [], "total": 0}})

                    def json(self):
                        return json.loads(self.text)

                return _Resp()

        with (
            patch.object(dev_iwhalecloud, "_ensure_valid_creds_async", new_callable=AsyncMock) as _ensure,
            patch.object(dev_iwhalecloud.httpx, "AsyncClient", _MockClient),
        ):
            _ensure.return_value = ("t", "c=1")
            resp = await client.post(
                "/api/dev/iwhalecloud/get_module_name_list",
                json={"projectId": 42, "productVersionId": 7},
            )
        assert resp.status_code == 200
        assert resp.json().get("errorcode") == 0
        params = captured.get("params") or {}
        assert params.get("projectId") == 42
        assert params.get("productVersionId") == 7


class TestGetProductBranchList:
    async def test_missing_product_version_id_422(self, client):
        resp = await client.post("/api/dev/iwhalecloud/get_product_branch_list", json={})
        assert resp.status_code == 422

    async def test_qry_by_condition_params_and_list_mapping(self, client):
        captured: dict[str, object] = {}

        class _MockClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None, params=None):
                captured["params"] = dict(params or {})
                captured["url"] = url
                req_url = url

                class _Resp:
                    status_code = 200
                    url = req_url
                    text = json.dumps(
                        {
                            "code": "9999",
                            "data": {
                                "list": [
                                    {
                                        "branchVersionId": 101,
                                        "branchName": "main",
                                        "noise": "x",
                                    },
                                ],
                                "total": 1,
                            },
                        },
                        ensure_ascii=False,
                    )

                    def json(self):
                        return json.loads(self.text)

                return _Resp()

        with (
            patch.object(dev_iwhalecloud, "_ensure_valid_creds_async", new_callable=AsyncMock) as _ensure,
            patch.object(dev_iwhalecloud.httpx, "AsyncClient", _MockClient),
        ):
            _ensure.return_value = ("t", "c=1")
            resp = await client.post(
                "/api/dev/iwhalecloud/get_product_branch_list",
                json={"productVersionId": 18325},
            )
        assert resp.status_code == 200
        assert resp.json().get("errorcode") == 0
        data = resp.json().get("data") or {}
        assert data.get("total") == 1
        lst = data.get("list") or []
        assert len(lst) == 1
        assert lst[0].get("branchVersionId") == 101
        assert lst[0].get("branchName") == "main"
        assert "noise" not in lst[0]
        params = captured.get("params") or {}
        assert params.get("productVersionId") == 18325
        assert params.get("size") == 2000
        assert params.get("page") == 1
        assert str(params.get("isValid")).lower() == "true"
        assert params.get("projectId") == ""
        assert "qryByConditionWithMain" in str(captured.get("url") or "")


class TestGetRepoDetailByProdBranch:
    async def test_missing_fields_422(self, client):
        resp = await client.post("/api/dev/iwhalecloud/get_repo_detail_by_prod_branch", json={})
        assert resp.status_code == 422

    async def test_two_gets_merge_dest_branch(self, client):
        urls: list[str] = []

        class _MockClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None, params=None):
                req_url = str(url)
                urls.append(req_url)
                if "/module/branch-version/4531" in req_url:
                    p = dict(params or {})
                    assert p.get("projectId") == 562722
                    assert p.get("catalogIdList") == ""
                    assert p.get("typeIdList") == ""
                    assert p.get("_")

                    class _R1:
                        status_code = 200
                        url = req_url
                        text = json.dumps(
                            {
                                "code": "9999",
                                "data": [
                                    {
                                        "repositoryId": 7506,
                                        "repoUrl": "https://git-nj.iwhalecloud.com/xmjfbss/ZMDB.git",
                                        "branchName": "master",
                                        "extra": 1,
                                    },
                                ],
                            },
                            ensure_ascii=False,
                        )

                        def json(self):
                            return json.loads(self.text)

                    return _R1()

                if "/rpc/task/branch-versions/4531" in req_url:
                    p2 = dict(params or {})
                    assert "_" in p2

                    class _R2:
                        status_code = 200
                        url = req_url
                        text = json.dumps(
                            {
                                "code": "9999",
                                "data": [
                                    {
                                        "productModuleDto": {"repoId": 7506},
                                        "adBranchVersionGitList": [
                                            {
                                                "repoProductModuleId": 1001,
                                                "sourceBranchName": "master",
                                                "destBranchName": "UNI_online",
                                                "destBranchType": "RELEASE",
                                            },
                                        ],
                                    },
                                ],
                            },
                            ensure_ascii=False,
                        )

                        def json(self):
                            return json.loads(self.text)

                    return _R2()

                raise AssertionError(f"unexpected url {url}")

        with (
            patch.object(dev_iwhalecloud, "_ensure_valid_creds_async", new_callable=AsyncMock) as _ensure,
            patch.object(dev_iwhalecloud.httpx, "AsyncClient", _MockClient),
        ):
            _ensure.return_value = ("t", "c=1")
            resp = await client.post(
                "/api/dev/iwhalecloud/get_repo_detail_by_prod_branch",
                json={"prod_branch": 4531, "projectId": 562722, "productModuleId": 1001},
            )
        assert resp.status_code == 200
        assert resp.json().get("errorcode") == 0
        data = resp.json().get("data") or []
        assert len(data) == 1
        assert data[0].get("repositoryId") == 7506
        assert data[0].get("repoUrl") == "https://git-nj.iwhalecloud.com/xmjfbss/ZMDB.git"
        assert data[0].get("branchName") == "master"
        assert data[0].get("destBranchName") == "UNI_online"
        assert "extra" not in data[0]
        assert len(urls) == 2

    async def test_no_git_match_uses_branch_name(self, client):
        class _MockClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None, params=None):
                req_url = str(url)
                if "/module/branch-version/" in req_url:

                    class _R1:
                        status_code = 200
                        url = req_url
                        text = json.dumps(
                            {
                                "code": "9999",
                                "data": [
                                    {
                                        "repositoryId": 1,
                                        "repoUrl": "https://e.git",
                                        "branchName": "master",
                                    },
                                ],
                            },
                            ensure_ascii=False,
                        )

                        def json(self):
                            return json.loads(self.text)

                    return _R1()

                class _R2:
                    status_code = 200
                    url = req_url
                    text = json.dumps(
                        {
                            "code": "9999",
                            "data": [
                                {
                                    "productModuleDto": {"repoId": 999},
                                    "adBranchVersionGitList": [],
                                },
                            ],
                        },
                        ensure_ascii=False,
                    )

                    def json(self):
                        return json.loads(self.text)

                return _R2()

        with (
            patch.object(dev_iwhalecloud, "_ensure_valid_creds_async", new_callable=AsyncMock) as _e,
            patch.object(dev_iwhalecloud.httpx, "AsyncClient", _MockClient),
        ):
            _e.return_value = ("t", "c=1")
            resp = await client.post(
                "/api/dev/iwhalecloud/get_repo_detail_by_prod_branch",
                json={"prod_branch": 1, "projectId": 1, "productModuleId": 1},
            )
        assert resp.status_code == 200
        row = (resp.json().get("data") or [{}])[0]
        assert row.get("destBranchName") == "master"


class TestGetZcmProductList:
    async def test_upstream_only_cache_param_returns_full_content(self, client):
        """getZcmProductList 上游仅带 _ 时间戳；服务端按条精简字段但不按 projectId 过滤。"""
        captured: dict[str, object] = {}

        class _MockClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None, params=None):
                captured["params"] = dict(params or {})
                captured["url"] = url
                req_url = url

                class _Resp:
                    status_code = 200
                    url = req_url
                    text = json.dumps(
                        {
                            "code": "9999",
                            "data": {
                                "content": [
                                    {
                                        "productVersionId": 1,
                                        "productVersionCode": "A",
                                        "projectId": 10,
                                        "extra": "x",
                                    },
                                    {
                                        "productVersionId": 2,
                                        "productVersionCode": "B",
                                        "projectId": 99,
                                    },
                                ],
                                "size": 2,
                            },
                        },
                        ensure_ascii=False,
                    )

                    def json(self):
                        return json.loads(self.text)

                return _Resp()

        with (
            patch.object(dev_iwhalecloud, "_ensure_valid_creds_async", new_callable=AsyncMock) as _ensure,
            patch.object(dev_iwhalecloud.httpx, "AsyncClient", _MockClient),
        ):
            _ensure.return_value = ("t", "c=1")
            resp = await client.post(
                "/api/dev/iwhalecloud/get_zcm_product_list",
                json={},
            )
        assert resp.status_code == 200
        assert resp.json().get("errorcode") == 0
        data = resp.json().get("data") or {}
        assert data.get("size") == 2
        content = data.get("content") or []
        assert len(content) == 2
        assert content[0].get("productVersionId") == 1
        assert content[0].get("productVersionCode") == "A"
        assert "projectId" not in content[0]
        assert "extra" not in content[0]
        assert content[1].get("productVersionId") == 2
        assert "projectId" not in content[1]
        params = captured.get("params") or {}
        assert params.get("_") is not None
        assert "projectId" not in params
        assert "getZcmProductList" in str(captured.get("url") or "")
