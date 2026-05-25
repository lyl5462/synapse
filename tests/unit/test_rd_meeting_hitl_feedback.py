"""人机问卷反馈结构化与模式判定。"""

from __future__ import annotations

from synapse.rd_meeting.hitl_feedback import (
    classify_hitl_feedback_mode,
    format_hitl_feedback_structured,
    split_question_answer,
    user_has_free_text_input,
)
from synapse.rd_meeting.hitl_form import HUMAN_SUPPLEMENT_QUESTION_ID
from synapse.rd_meeting.hitl_lifecycle import user_has_supplement_input

_SCHEMA = {
    "type": "questionnaire",
    "questions": [
        {
            "id": "q1",
            "type": "single",
            "title": "触发周期",
            "options": [{"value": "daily", "label": "每日一次"}, {"value": "weekly", "label": "每周一次"}],
        },
        {
            "id": "q2",
            "type": "single",
            "title": "是否启用",
            "options": [{"value": "true", "label": "是"}, {"value": "false", "label": "否"}],
        },
        {"id": HUMAN_SUPPLEMENT_QUESTION_ID, "type": "textarea", "title": "请问您还有什么需要补充的吗？"},
    ],
}


def test_user_has_free_text_detects_human_supplement_only():
    vals = {"q1": "daily", "q2": "true", HUMAN_SUPPLEMENT_QUESTION_ID: "  需要补充风险  "}
    assert user_has_free_text_input(vals, _SCHEMA)
    assert user_has_supplement_input(vals, schema=_SCHEMA)


def test_user_has_free_text_detects_per_question_other():
    vals = {"q1": ["daily", "OTHER:每周一和周五"], "q2": "true", HUMAN_SUPPLEMENT_QUESTION_ID: ""}
    assert user_has_free_text_input(vals, _SCHEMA)
    _, custom = split_question_answer(_SCHEMA["questions"][0], vals["q1"])
    assert custom == "每周一和周五"


def test_user_has_free_text_detects_parsed_other_without_prefix():
    """parse_hitl_form_text 剥掉 OTHER: 后，无法匹配选项的值仍视为自由输入。"""
    vals = {"q1": "每周一和周五", "q2": "true"}
    assert user_has_free_text_input(vals, _SCHEMA)


def test_options_only_when_selections_without_custom():
    vals = {"q1": "daily", "q2": "true", HUMAN_SUPPLEMENT_QUESTION_ID: ""}
    assert not user_has_free_text_input(vals, _SCHEMA)
    assert classify_hitl_feedback_mode(vals, _SCHEMA) == "options_only"


def test_text_question_counts_as_free_text():
    schema = {
        "questions": [{"id": "note", "type": "textarea", "title": "补充说明"}],
    }
    vals = {"note": "用户写了长段说明"}
    assert user_has_free_text_input(vals, schema)


def test_format_hitl_feedback_structured_shows_title_option_input():
    vals = {"q1": ["daily", "OTHER:节假日除外"], "q2": "true", HUMAN_SUPPLEMENT_QUESTION_ID: "整体 OK"}
    text = format_hitl_feedback_structured(vals, _SCHEMA)
    assert "触发周期" in text
    assert "每日一次" in text
    assert "节假日除外" in text
    assert "用户选项" in text
    assert "用户输入" in text
    assert "含自由输入" in text
    assert "请问您还有什么需要补充的吗" in text
    assert "整体 OK" in text


def test_format_hitl_feedback_options_only_mode_label():
    vals = {"q1": "weekly", "q2": "false", HUMAN_SUPPLEMENT_QUESTION_ID: ""}
    text = format_hitl_feedback_structured(vals, _SCHEMA)
    assert "仅选项" in text
    assert "用户输入**：（无）" in text
