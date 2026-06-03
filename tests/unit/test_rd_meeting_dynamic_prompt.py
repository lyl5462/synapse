"""四段式动态提示词模板。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.dynamic_prompt import (
    _format_section_product,
    _format_section_system,
    build_dynamic_meeting_context,
)


@pytest.fixture
def host_binding() -> dict:
    return {
        "node_id": "req_clarify",
        "node_name": "需求澄清",
        "stage_id": 1,
        "stage_name": "需求分析",
        "human_confirm": True,
        "node_intent": "澄清需求边界。",
        "host_profile_id": "default",
        "worker_profile_ids": ["whalecloud-requirement-expert"],
        "worker_llm_endpoint_key": "worker-default",
        "prompt_supplement": "账务中心优先复用限流方案",
    }


def test_four_section_structure(host_binding, monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_code": "ok", "prod": "p1", "repos": [], "docs": []},
            {"synapse_url": "http://127.0.0.1:10001"},
        ),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync._scope_row",
        lambda *_a, **_k: {"demand_no": "D1", "demand_title": "T", "prod": "p1"},
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync.load_scope_work_order_context",
        lambda *_a, **_k: {"demand_no": "D1", "demand_title": "T", "prod": "p1"},
    )

    md = build_dynamic_meeting_context(
        binding=host_binding,
        scope_type="demand",
        scope_id="D1",
        sop_node_display="需求澄清",
    )
    assert "## 一、本 SOP 环节工作信息" in md
    assert "(1) **会议节点**" in md
    assert "`需求澄清`" in md
    assert "(2) **会议目标**" in md
    assert "(3) **人工确认" in md
    assert "(4) **协作智能体**" in md
    assert "账务中心优先复用限流方案" in md
    assert "## 二、工单信息" in md
    assert "## 三、产品信息" in md
    assert "## 四、系统信息" in md
    assert "synapse_url" in md.lower() or "127.0.0.1:10001" in md


def test_dynamic_context_workers_summary_avoids_capability_card_duplication(host_binding, monkeypatch):
    """§0 一、(4) 协作智能体段仅给清单 + 指向能力卡片，不再重复 label/技能详情，避免与
    system prompt 顶部「参会能力卡片」冲突。"""
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_code": "ok", "prod": "p1", "repos": [], "docs": []},
            {"synapse_url": "http://127.0.0.1:10001"},
        ),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context._scope_row",
        lambda *_a, **_k: {"demand_no": "D1", "demand_title": "T", "prod": "p1"},
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync.load_scope_work_order_context",
        lambda *_a, **_k: {"demand_no": "D1", "demand_title": "T", "prod": "p1"},
    )

    md = build_dynamic_meeting_context(
        binding=host_binding,
        scope_type="demand",
        scope_id="D1",
        sop_node_display="需求澄清",
    )
    assert "(4) **协作智能体**" in md
    assert "whalecloud-requirement-expert" in md, "应列出参与本节点的 worker id"
    assert "参会能力卡片" in md, "应指向能力卡片以避免重复"
    # 不应再渲染单个 worker 的技能详表（这些已收敛到能力卡片）
    assert "- 技能：" not in md
    assert "- 主张：" not in md
    # 也不应再展示单 worker 的端点行（端点信息只在能力卡片上）
    assert md.count("worker-default") == 0


def test_format_section_system_includes_current_os(monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.dynamic_prompt._detect_current_os_type",
        lambda: "WINDOWS",
    )
    md = _format_section_system({})
    assert "- CURRENT_OS：`WINDOWS`" in md


def test_format_section_system_current_os_override():
    md = _format_section_system({"current_os": "linux"})
    assert "- CURRENT_OS：`LINUX`" in md


def test_format_section_product_repos_with_prod_branch():
    md = _format_section_product(
        {
            "prod": "p1",
            "repos": [
                {
                    "repo_module": "1001|客户管理",
                    "prod_branch": "4531|release-1.0",
                    "repo_url": "https://git.example.com/foo.git",
                    "local_path": "/work/code/foo",
                    "materialize_status": "ok",
                },
            ],
        }
    )
    assert "应用模块：客户管理" in md
    assert "产品分支ID: 4531" in md
    assert "产品分支: release-1.0" in md
    assert "仓库地址:https://git.example.com/foo.git" in md
    assert "→ `/work/code/foo`" in md


def test_product_section_includes_prod_feature(host_binding):
    md = build_dynamic_meeting_context(
        binding=host_binding,
        init_data={
            "order": {"id": "D1", "title": "T", "prod": "p1"},
            "product": {
                "locator_code": "ok",
                "prod": "p1",
                "prod_feature": "客户管理:CRM|订单中心:订单",
                "repos": [],
                "docs": [],
            },
            "system": {"synapse_url": "http://127.0.0.1:10001"},
        },
        scope_type="demand",
        scope_id="D1",
        sop_node_display="需求澄清",
    )
    assert "PROD_FEATURE" in md
    assert "客户管理:CRM|订单中心:订单" in md


def test_capability_cards_render_skill_label():
    """技能 label（来自 SKILL frontmatter）应出现在能力卡片，不再在动态上下文里。"""
    from synapse.rd_meeting.room_skill import _resolve_profile, build_capability_cards

    # 若 profile 不存在则跳过（依赖 SYSTEM_PRESETS）
    if _resolve_profile("whalecloud-requirement-expert") is None:
        pytest.skip("whalecloud-requirement-expert preset missing")

    cards = build_capability_cards(
        host_profile_id="default",
        worker_profile_ids=["whalecloud-requirement-expert"],
        host_llm_endpoint="reasoning-heavy",
        worker_llm_endpoint="worker-default",
        include_host=False,
    )
    assert "whalecloud-requirement-expert" in cards
    # 至少有一个技能 label（带括号的中文描述）出现在能力卡片中
    assert "（" in cards and "）" in cards
