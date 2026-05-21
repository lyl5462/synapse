"""四段式动态提示词模板。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.dynamic_prompt import build_dynamic_meeting_context


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
            {"synapse_url": "http://127.0.0.1:10001", "gitnexus_url": "http://127.0.0.1:11011"},
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
