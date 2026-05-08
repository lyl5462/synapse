"""L2 Component Tests: Database CRUD operations."""

import pytest
from datetime import datetime, timedelta

from synapse.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


class TestConversationCRUD:
    @pytest.mark.asyncio
    async def test_create_conversation(self, db):
        conv_id = await db.create_conversation(title="Test Chat")
        assert isinstance(conv_id, int)

    @pytest.mark.asyncio
    async def test_get_conversation(self, db):
        conv_id = await db.create_conversation(title="Retrieval Test")
        conv = await db.get_conversation(conv_id)
        assert conv is not None
        assert conv.title == "Retrieval Test"


class TestMessageCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get_messages(self, db):
        conv_id = await db.create_conversation(title="Msg Test")
        await db.add_message(conv_id, "user", "你好")
        await db.add_message(conv_id, "assistant", "你好！有什么可以帮你？")
        messages = await db.get_messages(conv_id)
        assert len(messages) == 2
        assert messages[0].role == "user"


class TestMemoryCRUD:
    @pytest.mark.asyncio
    async def test_add_memory(self, db):
        mem_id = await db.add_memory("preference", "用户喜欢Python", importance=3)
        assert isinstance(mem_id, int)

    @pytest.mark.asyncio
    async def test_get_memories(self, db):
        await db.add_memory("skill", "用户会用React", importance=2)
        memories = await db.get_memories(category="skill")
        assert len(memories) >= 1

    @pytest.mark.asyncio
    async def test_search_memories(self, db):
        await db.add_memory("fact", "用户的狗叫旺财")
        results = await db.search_memories("旺财")
        assert isinstance(results, list)


class TestPreferenceCRUD:
    @pytest.mark.asyncio
    async def test_set_and_get_preference(self, db):
        await db.set_preference("theme", "dark")
        value = await db.get_preference("theme")
        assert value == "dark"

    @pytest.mark.asyncio
    async def test_get_default_preference(self, db):
        value = await db.get_preference("nonexistent", default="fallback")
        assert value == "fallback"

    @pytest.mark.asyncio
    async def test_get_all_preferences(self, db):
        await db.set_preference("lang", "zh")
        prefs = await db.get_all_preferences()
        assert isinstance(prefs, dict)


class TestSkillCRUD:
    @pytest.mark.asyncio
    async def test_record_skill(self, db):
        skill_id = await db.record_skill("web-search", "1.0", "builtin")
        assert isinstance(skill_id, int)

    @pytest.mark.asyncio
    async def test_get_skill(self, db):
        await db.record_skill("file-ops", "2.0", "github")
        skill = await db.get_skill("file-ops")
        assert skill is not None
        assert skill.version == "2.0"

    @pytest.mark.asyncio
    async def test_list_skills(self, db):
        await db.record_skill("test-skill", "1.0", "local")
        skills = await db.list_skills()
        assert len(skills) >= 1


class TestTaskCRUD:
    @pytest.mark.asyncio
    async def test_record_task(self, db):
        task_id_db = await db.record_task("t1", "Process file")
        assert isinstance(task_id_db, int)

    @pytest.mark.asyncio
    async def test_update_task(self, db):
        await db.record_task("t2", "Upload data")
        await db.update_task("t2", status="completed", result="Success")


class TestWorkOrderDbMetrics:
    @pytest.mark.asyncio
    async def test_sop_metrics_empty_orders(self, db):
        assert await db.get_sop_trajectory_metrics_by_order_ids([]) == {}
        assert await db.get_sop_trajectory_artifacts_for_order_ids([]) == []
        s = await db.get_sop_trajectory_summary_for_order_ids([])
        assert s["process_seconds"] == 0
        assert s["human_interventions"] == 0
        assert s["artifacts"] == []

    @pytest.mark.asyncio
    async def test_sop_metrics_insert_and_aggregate(self, db):
        await db._connection.execute(
            """
            INSERT INTO sop_trajectories (
                order_id, sop_step_id, sop_node_id, sop_node_status,
                sop_node_start_time, sop_node_end_time, sop_node_use_model,
                sop_node_use_tokens, sop_node_output_list, sop_node_human_in_the_loop
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "D-100",
                "s1",
                "n1",
                "done",
                "2026-01-01 10:00:00",
                "2026-01-01 10:00:30",
                "gpt",
                42,
                '["artifact-a.md"]',
                1,
            ),
        )
        await db._connection.commit()
        per = await db.get_sop_trajectory_metrics_by_order_ids(["D-100"])
        assert per["D-100"]["deal_seconds"] == 30
        assert per["D-100"]["deal_tokens"] == 42
        assert per["D-100"]["human_interventions"] == 1
        arts = await db.get_sop_trajectory_artifacts_for_order_ids(["D-100"])
        assert "artifact-a.md" in arts
        summary = await db.get_sop_trajectory_summary_for_order_ids(["D-100"])
        assert summary["process_seconds"] == 30
        assert summary["human_interventions"] == 1

    @pytest.mark.asyncio
    async def test_sop_human_in_loop_flags_by_order_ids(self, db):
        assert await db.get_sop_human_in_loop_flags_by_order_ids([]) == {}
        await db._connection.execute(
            """
            INSERT INTO sop_trajectories (
                order_id, sop_step_id, sop_node_id, sop_node_status,
                sop_node_start_time, sop_node_end_time, sop_node_use_model,
                sop_node_use_tokens, sop_node_output_list, sop_node_human_in_the_loop
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "HITL-1",
                "s1",
                "n1",
                "done",
                "2026-01-01 10:00:00",
                "2026-01-01 10:00:30",
                "gpt",
                10,
                "[]",
                1,
            ),
        )
        await db._connection.execute(
            """
            INSERT INTO sop_trajectories (
                order_id, sop_step_id, sop_node_id, sop_node_status,
                sop_node_start_time, sop_node_end_time, sop_node_use_model,
                sop_node_use_tokens, sop_node_output_list, sop_node_human_in_the_loop
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "NO-HITL",
                "s1",
                "n1",
                "done",
                "2026-01-01 10:00:00",
                "2026-01-01 10:00:30",
                "gpt",
                5,
                "[]",
                0,
            ),
        )
        await db._connection.commit()
        flags = await db.get_sop_human_in_loop_flags_by_order_ids(["HITL-1", "NO-HITL", "MISSING"])
        assert flags["HITL-1"] is True
        assert flags["NO-HITL"] is False
        assert flags["MISSING"] is False

    @pytest.mark.asyncio
    async def test_token_usage_total_for_scenes(self, db):
        await db._connection.execute(
            """
            INSERT INTO token_usage (
                session_id, endpoint_name, model, operation_type,
                input_tokens, output_tokens, usage_scene
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("s1", "e1", "m1", "chat", 10, 20, "dev_whalecloud_sop_D-200"),
        )
        await db._connection.commit()
        total = await db.get_token_usage_total_tokens_for_scenes(
            ["dev_whalecloud_sop_D-200", "dev_whalecloud_sop_missing"]
        )
        assert total == 30


class TestTokenUsage:
    @pytest.mark.asyncio
    async def test_get_total(self, db):
        now = datetime.now()
        result = await db.get_token_usage_total(
            start_time=now - timedelta(hours=1),
            end_time=now,
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_summary(self, db):
        now = datetime.now()
        result = await db.get_token_usage_summary(
            start_time=now - timedelta(hours=1),
            end_time=now,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_by_scene(self, db):
        now = datetime.now()
        result = await db.get_token_usage_by_scene(
            start_time=now - timedelta(hours=1),
            end_time=now,
        )
        assert isinstance(result, list)
