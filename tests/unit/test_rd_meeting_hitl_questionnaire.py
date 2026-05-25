"""submit_hitl_questionnaire 工具与异常兜底单测。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.hitl_form import (
    HUMAN_SUPPLEMENT_QUESTION_ID,
    coerce_questionnaire_schema,
    default_exception_hitl_schema,
    normalize_hitl_schema,
    resolve_hitl_schema_for_gate,
)
from synapse.rd_meeting.hitl_submit import (
    PENDING_QUESTIONNAIRE_KEY,
    clear_pending_questionnaire,
    consume_pending_questionnaire,
    submit_questionnaire,
)


@pytest.fixture
def meeting_scope(tmp_path, monkeypatch):
    scope_id = "hitl-scope"
    work = tmp_path / scope_id
    work.mkdir(parents=True)
    (work / "dev.status").write_text(
        json.dumps(
            {
                "meeting_room": {"room_id": "room-hitl", "active": True},
                "current_node_id": "req_clarify",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (work / "room_state.json").write_text("{}", encoding="utf-8")
    (work / "room_history.jsonl").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "synapse.rd_meeting.live.scope_id_for_room_id",
        lambda rid: scope_id if rid == "room-hitl" else None,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.hitl_submit.scope_id_for_room_id",
        lambda rid: scope_id if rid == "room-hitl" else None,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_state_path",
        lambda s: work / "room_state.json",
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda s: work / "room_history.jsonl",
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_state_lock_path",
        lambda s: work / "room_state.lock",
    )
    return scope_id, work


def _sample_questions():
    return [
        {
            "id": "decision",
            "type": "single",
            "title": "请选择",
            "options": [
                {"value": "ok", "label": "同意"},
                {"value": "no", "label": "拒绝"},
            ],
            "inputEnabled": True,
            "inputPlaceholder": "或者你的答案：",
        }
    ]


def test_coerce_schema_validates_questions():
    with pytest.raises(ValueError):
        coerce_questionnaire_schema(kind="interactive", questions=[])
    with pytest.raises(ValueError):
        coerce_questionnaire_schema(kind="bogus", questions=_sample_questions())
    with pytest.raises(ValueError):
        coerce_questionnaire_schema(
            kind="interactive",
            questions=[{"id": "x", "type": "single", "title": ""}],
        )

    schema = coerce_questionnaire_schema(
        kind="result_confirm",
        questions=_sample_questions(),
        title="结果确认",
        summary="待确认要点",
    )
    assert schema["intervention_kind"] == "result_confirm"
    assert schema["summary_markdown"] == "待确认要点"
    assert schema["render"]["accent"] == "blue"
    assert schema["questions"][-1]["id"] == HUMAN_SUPPLEMENT_QUESTION_ID
    assert schema["questions"][-1]["type"] == "textarea"
    assert schema["questions"][0]["render"]["progress"]["total"] == 2


def test_normalize_appends_human_supplement_question():
    schema = normalize_hitl_schema(
        {
            "type": "questionnaire",
            "questions": [
                {
                    "id": "q1",
                    "type": "single",
                    "title": "是否通过",
                    "options": [{"value": "y", "label": "是"}],
                    "inputEnabled": True,
                },
            ],
        }
    )
    assert schema is not None
    assert schema["questions"][-1]["id"] == HUMAN_SUPPLEMENT_QUESTION_ID
    assert schema["questions"][-1]["required"] is False
    assert schema["questions"][-1]["type"] == "textarea"


def test_submit_questionnaire_writes_room_state(meeting_scope):
    scope_id, work = meeting_scope
    result = submit_questionnaire(
        session_id="rd_meeting:room-hitl:host",
        kind="exception",
        questions=_sample_questions(),
        title="异常",
        summary="质量未达标",
    )
    assert result["scope_id"] == scope_id
    assert result["await_confirm"] is False  # exception 默认 false

    state = json.loads((work / "room_state.json").read_text(encoding="utf-8"))
    pending = state.get(PENDING_QUESTIONNAIRE_KEY)
    assert isinstance(pending, dict)
    assert pending["kind"] == "exception"
    assert pending["consumed"] is False
    assert pending["schema"]["intervention_kind"] == "exception"

    history = (work / "room_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert any("hitl_questionnaire_submitted" in line for line in history)


def test_submit_questionnaire_rejects_non_host_session(meeting_scope):
    with pytest.raises(ValueError):
        submit_questionnaire(
            session_id="rd_meeting:room-hitl:worker",
            kind="interactive",
            questions=_sample_questions(),
        )
    with pytest.raises(ValueError):
        submit_questionnaire(
            session_id="desktop:abc",
            kind="interactive",
            questions=_sample_questions(),
        )


def test_consume_marks_consumed(meeting_scope):
    scope_id, _ = meeting_scope
    submit_questionnaire(
        session_id="rd_meeting:room-hitl:host",
        kind="interactive",
        questions=_sample_questions(),
    )
    first = consume_pending_questionnaire(scope_id)
    assert first is not None
    again = consume_pending_questionnaire(scope_id)
    assert again is None  # 第二次为 None（已消费）


def test_clear_pending(meeting_scope):
    scope_id, work = meeting_scope
    submit_questionnaire(
        session_id="rd_meeting:room-hitl:host",
        kind="interactive",
        questions=_sample_questions(),
    )
    clear_pending_questionnaire(scope_id)
    state = json.loads((work / "room_state.json").read_text(encoding="utf-8"))
    assert PENDING_QUESTIONNAIRE_KEY not in state


def test_resolve_hitl_schema_exception_has_default():
    binding = {"node_id": "req_clarify", "human_confirm": True}
    schema = resolve_hitl_schema_for_gate(
        binding,
        dynamic_schema=None,
        reason="产物过短",
        intervention_kind="exception",
    )
    assert schema is not None
    assert schema["summary_kind"] == "exception"
    assert any(
        q["id"] == "decision" for q in schema["questions"]
    ), "异常默认表单需包含 decision 题"


def test_resolve_hitl_schema_interactive_stays_none():
    binding = {"node_id": "req_clarify", "human_confirm": True}
    assert (
        resolve_hitl_schema_for_gate(
            binding,
            dynamic_schema=None,
            intervention_kind="interactive",
        )
        is None
    )


def test_coerce_rejects_under_granular_questionnaire():
    """summary 列了 14 个 P0 问题，questions 只给 2 道 → 必须拒绝。"""
    summary = (
        "## 需求澄清\n"
        "14个P0问题均附有可默认结论（含2个待确认项），请确认：\n"
        "1. 备份方式：全量\n2. 备份粒度：按节点\n3. 触发机制：定时\n"
        "4. 备份范围：全量内存\n5. 存储格式：二进制\n6. 保留策略：最近3份\n"
        "7. 回退触发：人工\n8. 交付范围：完整闭环\n9. 触发周期：4h\n"
        "10. 交付时间：待业务方确认\n11. 性能影响：可接受\n"
        "12. 多节点协调：独立\n13. 监控告警：复用\n14. 失败恢复：自动重试\n"
    )
    questions = [
        {"id": "q1", "type": "single", "title": "整体确认", "inputEnabled": True},
        {"id": "q2", "type": "single", "title": "触发周期", "inputEnabled": True},
    ]
    with pytest.raises(ValueError) as excinfo:
        coerce_questionnaire_schema(
            kind="result_confirm",
            questions=questions,
            summary=summary,
        )
    assert "颗粒度" in str(excinfo.value)


def test_coerce_allows_sufficient_granularity():
    summary = "## 待澄清问题\n1. A\n2. B\n3. C\n"
    questions = [
        {"id": f"q{i}", "type": "single", "title": f"题目 {i}", "inputEnabled": True}
        for i in range(1, 4)
    ]
    schema = coerce_questionnaire_schema(
        kind="result_confirm",
        questions=questions,
        summary=summary,
    )
    assert len(schema["questions"]) == 4
    assert schema["questions"][-1]["id"] == HUMAN_SUPPLEMENT_QUESTION_ID


def test_coerce_granularity_skipped_for_exception():
    """异常场景不强制颗粒度（异常摘要里常出现数字但没有题目对应）。"""
    summary = "节点产物未通过 14 项校验"
    schema = coerce_questionnaire_schema(
        kind="exception",
        questions=[
            {"id": "q1", "type": "single", "title": "处置", "inputEnabled": True}
        ],
        summary=summary,
    )
    assert schema["intervention_kind"] == "exception"


def test_coerce_normalizes_option_value_from_id():
    """LLM 输出 ``{"id": "...", "label": "..."}`` 时必须归一化为 value。"""
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "q1",
                "type": "single",
                "title": "请选择",
                "options": [
                    {"id": "confirm_all", "label": "全部确认"},
                    {"id": "reject", "label": "拒绝"},
                    {"label": "仅有 label 也要拿到稳定 value"},
                ],
                "inputEnabled": True,
            }
        ],
    )
    opts = schema["questions"][0]["options"]
    values = [o["value"] for o in opts]
    assert values[0] == "confirm_all"
    assert values[1] == "reject"
    # 第三项无 id 也无 value：从 label 推断稳定主键
    assert values[2] and values[2] != values[0] and values[2] != values[1]
    assert all(isinstance(v, str) and v.strip() for v in values)


def test_coerce_rejects_roadmap_in_summary():
    summary = (
        "## 待确认\n| Q1 | 备份 |\n\n### 下一步\n"
        "确认后 → 方案设计（Phase 1：备份文件格式）"
    )
    with pytest.raises(ValueError) as excinfo:
        coerce_questionnaire_schema(
            kind="result_confirm",
            questions=[
                {"id": "q1", "type": "single", "title": "Q1", "inputEnabled": True}
            ],
            summary=summary,
        )
    assert "summary" in str(excinfo.value).lower() or "路线图" in str(excinfo.value)


def test_coerce_allows_clean_summary():
    coerce_questionnaire_schema(
        kind="result_confirm",
        questions=[
            {
                "id": "q1",
                "type": "single",
                "title": "Q1 备份方式",
                "inputEnabled": True,
            }
        ],
        summary="## 本节点待确认\n- Q1 备份方式：推荐全量（✅）\n",
    )


def test_coerce_granularity_can_be_disabled():
    """允许测试 / 系统场景跳过校验。"""
    summary = "10 个待确认项："
    coerce_questionnaire_schema(
        kind="result_confirm",
        questions=[
            {"id": "q1", "type": "single", "title": "整体", "inputEnabled": True}
        ],
        summary=summary,
        enforce_granularity=False,
    )


def test_coerce_auto_enables_input_for_single_without_flag():
    """选项题无需 LLM 显式 inputEnabled；coerce 会自动打开。"""
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "decision",
                "type": "single",
                "title": "请选择",
                "options": [
                    {"value": "ok", "label": "同意"},
                    {"value": "no", "label": "拒绝"},
                ],
            }
        ],
    )
    assert schema["questions"][0]["inputEnabled"] is True


def test_coerce_auto_enables_input_for_multiple_without_flag():
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "tags",
                "type": "multiple",
                "title": "影响范围（可多选）",
                "options": [
                    {"value": "a", "label": "A 模块"},
                    {"value": "b", "label": "B 模块"},
                ],
            }
        ],
    )
    assert schema["questions"][0]["inputEnabled"] is True


def test_normalize_guardrail_empty_options_becomes_textarea():
    from synapse.rd_meeting.hitl_form import ensure_question_input_guardrails

    out = ensure_question_input_guardrails(
        [{"id": "q1", "type": "single", "title": "无选项题", "options": []}]
    )
    assert out[0]["type"] == "textarea"


def test_coerce_allows_multiple_choice_with_input():
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "tags",
                "type": "multiple",
                "title": "影响范围（可多选）",
                "options": [
                    {"value": "a", "label": "A 模块"},
                    {"value": "b", "label": "B 模块"},
                ],
                "inputEnabled": True,
                "inputPlaceholder": "其他模块：",
            }
        ],
    )
    assert schema["questions"][0]["type"] == "multiple"
    assert schema["questions"][0]["inputEnabled"] is True


def test_coerce_boolean_and_text_do_not_require_input_enabled():
    """``boolean`` / ``text`` / ``textarea`` 不强制 inputEnabled。"""
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {"id": "ack", "type": "boolean", "title": "是否知悉"},
            {"id": "note", "type": "textarea", "title": "备注"},
            {"id": "name", "type": "text", "title": "联系人"},
        ],
    )
    assert len(schema["questions"]) == 4  # 含系统追加补充题


def test_coerce_normalizes_yes_no_options_to_true_false():
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "q1",
                "type": "single",
                "title": "是否同意",
                "options": [
                    {"label": "是"},
                    {"label": "否"},
                ],
            },
        ],
    )
    q = schema["questions"][0]
    assert q["render"]["optionStyle"] == "boolean"
    values = {o["value"] for o in q["options"]}
    assert values == {"true", "false"}


def test_coerce_normalizes_python_bool_option_values():
    schema = coerce_questionnaire_schema(
        kind="interactive",
        questions=[
            {
                "id": "q1",
                "type": "single",
                "title": "判断",
                "options": [
                    {"value": True, "label": "是"},
                    {"value": False, "label": "否"},
                ],
            },
        ],
    )
    q = schema["questions"][0]
    assert q["render"]["optionStyle"] == "boolean"
    assert [o["value"] for o in q["options"]] == ["true", "false"]


def test_default_exception_schema_shape():
    schema = default_exception_hitl_schema("req_clarify", reason="解析失败")
    assert schema["type"] == "questionnaire"
    assert schema["render"]["accent"] == "violet"
    ids = {q["id"] for q in schema["questions"]}
    assert {"exception_ack", "decision", "comment"} <= ids
