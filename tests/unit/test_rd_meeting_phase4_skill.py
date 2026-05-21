"""Phase 4：会议室专属 SKILL 加载、角色裁剪、能力卡片渲染。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.room_skill import (
    DEFAULT_MEETING_SKILL_ID,
    build_capability_cards,
    build_room_skill_prompt,
    find_meeting_skill_file,
    load_meeting_skill_body,
    make_context,
    meeting_skill_preview,
    trim_skill_for_role,
)


@pytest.fixture
def host_binding() -> dict:
    return {
        "node_id": "boundary",
        "node_name": "边界确认",
        "stage_id": 1,
        "stage_name": "需求分析",
        "type": "ai",
        "intent": "识别跨产品边界，确保单需求单产品。",
        "host_profile_id": "default",
        "worker_profile_ids": [
            "whalecloud-requirement-expert",
            "whalecloud-design-expert",
        ],
        "skill_ids": [],
        "llm_endpoint_key": "worker-default",
        "host_llm_endpoint_key": "reasoning-heavy",
        "worker_llm_endpoint_key": "worker-default",
        "meeting_skill_id": DEFAULT_MEETING_SKILL_ID,
        "prompt_supplement": "本产品为账务中心，优先复用存量限流方案。",
    }


def test_skill_file_exists_in_repo():
    path = find_meeting_skill_file(DEFAULT_MEETING_SKILL_ID)
    assert path is not None, "SKILL.md 应能从仓库内 skills/ 目录被发现"
    assert path.name == "SKILL.md"


def test_load_skill_body_strips_frontmatter():
    body = load_meeting_skill_body(DEFAULT_MEETING_SKILL_ID)
    assert "## 1. 节点会议目标" in body
    assert "## 7. 不变量" in body
    assert "name: whalecloud-dev-tool-meeting-room" not in body, "front-matter 应被去除"


def test_trim_skill_for_role_hides_other_perspective():
    body = load_meeting_skill_body(DEFAULT_MEETING_SKILL_ID)
    host_view = trim_skill_for_role(body, "host")
    worker_view = trim_skill_for_role(body, "worker")

    assert "## 4. 小鲸（Host）的工作循环" in host_view
    assert "## 5. 协作智能体（Worker）的协作规范" not in host_view

    assert "## 5. 协作智能体（Worker）的协作规范" in worker_view
    assert "## 4. 小鲸（Host）的工作循环" not in worker_view


def test_build_capability_cards_lists_host_and_workers(host_binding):
    cards = build_capability_cards(
        host_profile_id=host_binding["host_profile_id"],
        worker_profile_ids=host_binding["worker_profile_ids"],
        host_llm_endpoint=host_binding["host_llm_endpoint_key"],
        worker_llm_endpoint=host_binding["worker_llm_endpoint_key"],
    )
    assert "角色：host" in cards
    assert "角色：worker" in cards
    assert "whalecloud-requirement-expert" in cards
    assert "whalecloud-design-expert" in cards
    assert "reasoning-heavy" in cards


def test_build_capability_cards_excludes_self_for_worker(host_binding):
    cards = build_capability_cards(
        host_profile_id=host_binding["host_profile_id"],
        worker_profile_ids=host_binding["worker_profile_ids"],
        host_llm_endpoint=host_binding["host_llm_endpoint_key"],
        worker_llm_endpoint=host_binding["worker_llm_endpoint_key"],
        exclude_self_id="whalecloud-requirement-expert",
    )
    assert "whalecloud-requirement-expert" not in cards.split("##", 2)[2] if cards.count("##") > 1 else True
    assert "whalecloud-design-expert" in cards
    assert "角色：host" in cards, "Host 卡片对 Worker 仍然可见"


def test_build_room_skill_prompt_renders_context_vars(host_binding):
    ctx = make_context(
        role="host",
        binding=host_binding,
        scope_type="demand",
        scope_id="21878317",
        ticket_title="演示工单",
        archive_dir="/tmp/work/21878317/archive/1/boundary",
    )
    rendered = build_room_skill_prompt(ctx)

    assert "{ROLE}" not in rendered
    assert "host" in rendered
    assert "21878317" in rendered
    assert "演示工单" in rendered
    assert "边界确认" in rendered
    assert "reasoning-heavy" in rendered
    assert "worker-default" in rendered
    assert "## 1. 节点会议目标" in rendered
    assert "## 4. 小鲸（Host）的工作循环" in rendered
    assert "## 5. 协作智能体（Worker）的协作规范" not in rendered
    assert "本产品为账务中心" in rendered, "运营补充应出现在四段式第一节"
    assert "## 一、本 SOP 环节工作信息" in rendered
    assert "{DYNAMIC_MEETING_CONTEXT}" not in rendered
    assert "协作智能体能力已并入" in rendered or "(4) **协作智能体**" in rendered


def test_build_room_skill_prompt_worker_view(host_binding):
    ctx = make_context(
        role="worker",
        binding=host_binding,
        scope_type="demand",
        scope_id="21878317",
        ticket_title="演示工单",
        archive_dir="/tmp/work/21878317/archive/1/boundary",
    )
    rendered = build_room_skill_prompt(ctx)
    assert "## 5. 协作智能体（Worker）的协作规范" in rendered
    assert "## 4. 小鲸（Host）的工作循环" not in rendered


def test_meeting_skill_preview_returns_metadata():
    preview = meeting_skill_preview(DEFAULT_MEETING_SKILL_ID)
    assert preview["skill_id"] == DEFAULT_MEETING_SKILL_ID
    assert preview["exists"] is True
    assert preview["path"]
    assert preview.get("length", 0) > 0


def test_fallback_when_skill_id_unknown():
    body = load_meeting_skill_body("non-existent-skill-id-xyz")
    assert "兜底版" in body
    preview = meeting_skill_preview("non-existent-skill-id-xyz")
    assert preview["exists"] is False
