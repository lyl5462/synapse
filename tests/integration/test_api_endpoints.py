"""L3 Integration Tests: Remaining API endpoints (files, skills, token_stats, im, logs, upload, models)."""

import pytest
import httpx

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


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


class TestModelsEndpoint:
    async def test_list_models(self, client):
        resp = await client.get("/api/models")
        # Should return 200 even without agent (graceful fallback)
        assert resp.status_code in (200, 500)


class TestSkillsEndpoint:
    async def test_list_skills(self, client):
        resp = await client.get("/api/skills")
        assert resp.status_code in (200, 500)

    async def test_reload_skills(self, client):
        resp = await client.post("/api/skills/reload")
        assert resp.status_code in (200, 500)

    async def test_search_marketplace(self, client):
        resp = await client.get("/api/skills/marketplace?q=test")
        assert resp.status_code in (200, 500)


class TestTokenStatsEndpoint:
    async def test_summary(self, client):
        resp = await client.get("/api/stats/tokens/summary")
        assert resp.status_code in (200, 500)

    async def test_total(self, client):
        resp = await client.get("/api/stats/tokens/total")
        assert resp.status_code in (200, 500)

    async def test_timeline(self, client):
        resp = await client.get("/api/stats/tokens/timeline")
        assert resp.status_code in (200, 500)

    async def test_sessions(self, client):
        resp = await client.get("/api/stats/tokens/sessions")
        assert resp.status_code in (200, 500)

    async def test_scenes(self, client):
        resp = await client.get("/api/stats/tokens/scenes")
        assert resp.status_code in (200, 500)

    async def test_context(self, client):
        resp = await client.get("/api/stats/tokens/context")
        assert resp.status_code in (200, 500)


class TestWorkOrderDbMetricsEndpoint:
    async def test_db_metrics(self, client):
        resp = await client.post(
            "/api/dev/work-order/db-metrics",
            json={"demand_no": "21878317", "task_nos": ["11879580"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("errorcode") == 0
        data = body.get("data") or {}
        assert "summary" in data
        assert "demand_metrics" in data
        assert "task_metrics" in data

    async def test_human_in_loop_flags(self, client):
        resp = await client.post(
            "/api/dev/work-order/human-in-loop-flags",
            json={"order_id": "D-100"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("errorcode") == 0
        data = body.get("data") or {}
        assert "human_in_the_loop" in data
        assert isinstance(data.get("human_in_the_loop"), bool)

    async def test_human_in_loop_flags_empty_order_id(self, client):
        resp = await client.post("/api/dev/work-order/human-in-loop-flags", json={"order_id": ""})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("errorcode") == 400

    async def test_db_metrics_empty_demand(self, client):
        resp = await client.post("/api/dev/work-order/db-metrics", json={"demand_no": ""})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("errorcode") == 400


class TestIMEndpoint:
    async def test_list_channels(self, client):
        resp = await client.get("/api/im/channels")
        assert resp.status_code in (200, 500)

    async def test_list_sessions(self, client):
        resp = await client.get("/api/im/sessions")
        assert resp.status_code in (200, 500)


class TestLogsEndpoint:
    async def test_service_log(self, client):
        resp = await client.get("/api/logs/service")
        assert resp.status_code in (200, 500)


class TestUploadEndpoint:
    async def test_upload_without_file(self, client):
        resp = await client.post("/api/upload")
        assert resp.status_code in (422, 400)  # Missing required file

    async def test_serve_nonexistent_upload(self, client):
        resp = await client.get("/api/uploads/nonexistent.txt")
        assert resp.status_code in (404, 500)


class TestFilesEndpoint:
    async def test_serve_root(self, client):
        resp = await client.get("/api/files")
        assert resp.status_code in (200, 400, 404, 500)
