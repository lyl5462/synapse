"""interactive 问卷结构修复：嵌入 options 提取、堆叠题拒绝。"""

from __future__ import annotations

import pytest

from synapse.rd_meeting.hitl_form import coerce_questionnaire_schema, normalize_hitl_schema
from synapse.rd_meeting.questionnaire_repair import (
    apply_interactive_question_repairs,
    extract_embedded_options,
    repair_embedded_options,
    validate_no_stacked_decisions,
)


def test_extract_letter_options_from_context():
    result = extract_embedded_options(
        "备份方式确认",
        "假设运维需调整备份策略，请选择：A. 全量备份 B. 增量备份 C. 按节点备份（✅ 推荐）",
    )
    assert result is not None
    options, new_context, title = result
    assert len(options) == 3
    assert options[0]["label"] == "全量备份"
    assert "✅" in options[2]["label"]
    assert "A." not in new_context
    assert title == "备份方式确认"


def test_repair_embedded_options_populates_options():
    q = repair_embedded_options(
        {
            "id": "q1",
            "type": "single",
            "title": "备份方式",
            "context": "请选择：A. 全量 B. 增量 C. 按节点",
            "options": [],
        },
        idx=0,
    )
    assert len(q["options"]) == 3
    assert q["type"] == "single"


def test_repair_rejects_unparseable_embedded_options():
    with pytest.raises(ValueError) as excinfo:
        repair_embedded_options(
            {
                "id": "q2",
                "type": "single",
                "title": "确认",
                "context": "可选：详见上文表格，无法拆分为独立选项",
                "options": [],
            },
            idx=2,
        )
    assert "options[]" in str(excinfo.value)


def test_open_question_without_patterns_stays_empty():
    q = repair_embedded_options(
        {
            "id": "q3",
            "type": "single",
            "title": "请补充联系人",
            "context": "若与默认不同请说明原因。",
            "options": [],
        },
        idx=0,
    )
    assert q["options"] == []


def test_reject_stacked_decision_options():
    stacked = {
        "id": "confirm_all",
        "type": "single",
        "title": "整体确认以下默认结论",
        "options": [
            {"value": "1", "label": "Q1 备份方式：全量 ✅"},
            {"value": "2", "label": "Q2 备份粒度：按节点 ✅"},
            {"value": "3", "label": "Q3 触发机制：定时 ✅"},
            {"value": "4", "label": "Q4 存储格式：二进制 ✅"},
            {"value": "5", "label": "Q5 保留策略：最近3份 ✅"},
        ],
    }
    with pytest.raises(ValueError) as excinfo:
        validate_no_stacked_decisions([stacked])
    assert "合并成一道题" in str(excinfo.value)


def test_allow_legitimate_multi_option_question():
    modules = {
        "id": "modules",
        "type": "multiple",
        "title": "该变更涉及哪些模块？",
        "options": [
            {"value": "a", "label": "网关模块"},
            {"value": "b", "label": "调度模块"},
            {"value": "c", "label": "存储模块"},
            {"value": "d", "label": "监控模块"},
            {"value": "e", "label": "配置中心"},
        ],
    }
    validate_no_stacked_decisions([modules])


def test_coerce_interactive_repairs_embedded_options():
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "q1",
                "type": "single",
                "title": "限流档位",
                "context": "场景说明。A. 固定三级 B. 数字自定义 C. 五档",
            }
        ],
        summary="## 待确认\n- Q1 限流档位",
    )
    q = schema["questions"][0]
    assert len(q["options"]) == 3
    assert q["type"] == "single"


def test_coerce_interactive_rejects_stacked():
    with pytest.raises(ValueError) as excinfo:
        coerce_questionnaire_schema(
            kind="interactive",
            questions=[
                {
                    "id": "all",
                    "type": "single",
                    "title": "批量确认",
                    "options": [
                        {"value": str(i), "label": f"Q{i} 维度{i}：默认 ✅"}
                        for i in range(1, 6)
                    ],
                }
            ],
        )
    assert "合并成一道题" in str(excinfo.value)


def test_coerce_result_confirm_skips_repair():
    schema = coerce_questionnaire_schema(
        kind="result_confirm",
        questions=[
            {
                "id": "q1",
                "type": "single",
                "title": "确认",
                "context": "A. 是 B. 否",
                "options": [],
            }
        ],
        summary="待确认",
        enforce_granularity=False,
    )
    q = schema["questions"][0]
    assert q["type"] == "textarea"


def test_normalize_interactive_repairs_from_file_schema():
    schema = normalize_hitl_schema(
        {
            "type": "questionnaire",
            "intervention_kind": "interactive",
            "questions": [
                {
                    "id": "q1",
                    "type": "single",
                    "title": "触发周期",
                    "context": "请选择：1. 4小时 2. 8小时 3. 24小时",
                    "options": [],
                }
            ],
        }
    )
    assert schema is not None
    assert len(schema["questions"][0]["options"]) == 3


def test_apply_repairs_end_to_end():
    out = apply_interactive_question_repairs(
        [
            {"id": "q1", "type": "single", "title": "Q1", "context": "A. 同意 B. 拒绝", "options": []},
            {
                "id": "q2",
                "type": "single",
                "title": "模块范围",
                "options": [
                    {"value": "a", "label": "模块A"},
                    {"value": "b", "label": "模块B"},
                    {"value": "c", "label": "模块C"},
                ],
            },
        ],
        summary="## 待确认\n1. Q1\n2. Q2",
    )
    assert len(out[0]["options"]) == 2
    assert len(out[1]["options"]) == 3
