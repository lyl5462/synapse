"""人工确认（HITL）统一问答表单 schema：配置 → 绑定 → 小鲸 prompt。

Schema 采用 questionnaire v1.0（与需求澄清 question-transform 对齐）：
- ``type``: ``questionnaire``
- ``questions[]``: 单选 / 多选 / 判断 / 文本，含 context、render.progress、inputEnabled 等
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from synapse.rd_sop.manifest import get_node_manifest_entry
from synapse.rd_sop.nodes import node_display_name

QuestionType = Literal["single", "multiple", "boolean", "text", "textarea"]
OptionStyle = Literal["radio", "checkbox", "boolean"]

QUESTIONNAIRE_TYPE = "questionnaire"
QUESTIONNAIRE_VERSION = "1.0"

# 所有人机问卷末尾追加的自由补充题（不覆盖上方选项/填空答案）
HUMAN_SUPPLEMENT_QUESTION_ID = "human_supplement"
HUMAN_SUPPLEMENT_TITLE = "请问您还有什么需要补充的吗？"

# 智能体输出中的 HITL 问卷标记（与技能 whalecloud-dev-tool-ask-user 对齐）
HITL_MARKER_BEGIN = "<!-- hitl-questionnaire"
HITL_MARKER_END = "<!-- /hitl-questionnaire -->"

_HITL_HTML_BLOCK_RE = re.compile(
    r"<!--\s*hitl-questionnaire(?P<attrs>[^>]*)-->\s*"
    r"(?:```(?:json)?\s*\n)?(?P<body>.*?)(?:```\s*)?"
    r"<!--\s*/hitl-questionnaire\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_HITL_ATTR_KIND_RE = re.compile(r"\bkind\s*=\s*([^\s/>]+)", re.IGNORECASE)
_HITL_ATTR_CONFIRM_RE = re.compile(r"\bawait_confirm\s*=\s*(true|false)", re.IGNORECASE)


@dataclass(frozen=True)
class HitlGateFromReport:
    """从主控智能体回复中解析出的人机门控信息。"""

    clean_body: str
    schema: dict[str, Any] | None
    explicit: bool
    intervention_kind: str
    await_confirm: bool | None


def _parse_hitl_marker_attrs(attrs: str) -> tuple[str | None, bool | None]:
    kind: str | None = None
    await_confirm: bool | None = None
    m_kind = _HITL_ATTR_KIND_RE.search(attrs or "")
    if m_kind:
        kind = m_kind.group(1).strip().lower()
    m_confirm = _HITL_ATTR_CONFIRM_RE.search(attrs or "")
    if m_confirm:
        await_confirm = m_confirm.group(1).lower() == "true"
    return kind, await_confirm


def _loads_hitl_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _is_valid_hitl_schema(data: dict[str, Any]) -> bool:
    qs = data.get("questions")
    return isinstance(qs, list) and len(qs) > 0


def extract_hitl_from_agent_output(text: str) -> HitlGateFromReport:
    """从智能体 Markdown 回复中提取 HITL 问卷块。

    仅支持 HTML 注释包裹：
    ``<!-- hitl-questionnaire kind=interactive -->`` … ``<!-- /hitl-questionnaire -->``
    """
    body = str(text or "")
    schema: dict[str, Any] | None = None
    explicit = False
    kind: str | None = None
    await_confirm: bool | None = None
    span: tuple[int, int] | None = None

    for m in _HITL_HTML_BLOCK_RE.finditer(body):
        parsed = _loads_hitl_json(m.group("body"))
        if parsed and _is_valid_hitl_schema(parsed):
            schema = parsed
            explicit = True
            span = m.span()
            k, ac = _parse_hitl_marker_attrs(m.group("attrs") or "")
            kind = k or kind
            await_confirm = ac if ac is not None else await_confirm
            break

    clean = body
    if span is not None:
        clean = (body[: span[0]] + body[span[1] :]).strip()

    intervention_kind = kind or "interactive"
    if intervention_kind not in ("interactive", "result_confirm", "exception"):
        intervention_kind = "interactive"

    if await_confirm is None and explicit:
        if intervention_kind == "result_confirm":
            await_confirm = True
        elif "# 交付结论" in clean or "交付结论" in clean:
            await_confirm = True
            intervention_kind = "result_confirm"
        else:
            await_confirm = False

    normalized = normalize_hitl_schema(schema) if schema else None
    return HitlGateFromReport(
        clean_body=clean,
        schema=normalized,
        explicit=explicit,
        intervention_kind=intervention_kind,
        await_confirm=await_confirm,
    )


_LOOSE_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_loose_questionnaire_json(text: str) -> dict[str, Any] | None:
    """从回复中解析裸 questionnaire JSON（协作智能体 / question-transform 常见输出）。"""
    body = str(text or "").strip()
    if not body:
        return None
    if body.startswith("{"):
        parsed = _loads_hitl_json(body)
        if parsed and _is_valid_hitl_schema(parsed):
            return parsed
    for m in _LOOSE_JSON_FENCE_RE.finditer(body):
        parsed = _loads_hitl_json(m.group(1))
        if parsed and _is_valid_hitl_schema(parsed):
            return parsed
    return None


def load_scope_questions_json(scope_id: str) -> dict[str, Any] | None:
    """读取工单目录下需求澄清技能写入的 ``.questions.json``。"""
    sid = (scope_id or "").strip()
    if not sid:
        return None
    from synapse.rd_meeting.paths import scope_dir

    root = scope_dir(sid)
    for rel in (".questions.json", ".tmp/.questions.json"):
        path = root.joinpath(*rel.split("/"))
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and _is_valid_hitl_schema(data):
            return data
    return None


def infer_clarify_hitl_schema(
    report_body: str,
    *,
    scope_id: str = "",
    node_id: str = "req_clarify",
) -> dict[str, Any] | None:
    """会中澄清门控：从主控/协作产出或工单 ``.questions.json`` 解析问卷 schema。"""
    gate = extract_hitl_from_agent_output(report_body)
    if gate.schema:
        return gate.schema
    loose = _extract_loose_questionnaire_json(report_body)
    if loose:
        return normalize_hitl_schema(loose)
    if node_id == "req_clarify" and scope_id.strip():
        file_schema = load_scope_questions_json(scope_id)
        if file_schema:
            out = normalize_hitl_schema(file_schema)
            if out and not out.get("title"):
                name = node_display_name(node_id)
                out["title"] = f"{name} — 待澄清问题"
            return out
    return None


def resolve_hitl_schema_for_gate(
    binding: dict[str, Any],
    *,
    dynamic_schema: dict[str, Any] | None,
    reason: str = "",
    intervention_kind: str = "interactive",
) -> dict[str, Any] | None:
    """门控展示用 schema：仅使用智能体/协作产出或节点显式配置的 questionnaire。

    ``interactive`` / ``exception`` 不提供系统内置题目；``result_confirm`` 在无动态问卷时
    可使用节点默认结果确认模板（归档验收结构化字段）。
    """
    if dynamic_schema:
        return dynamic_schema
    preset = binding.get("hitl_form_schema")
    if isinstance(preset, dict) and preset.get("questions"):
        return normalize_hitl_schema(preset)
    node_id = str(binding.get("node_id") or "")
    kind = (intervention_kind or "interactive").strip().lower()
    if kind == "interactive":
        # 会中澄清的题面必须由 ask-user / submit_hitl_questionnaire 提供；
        # 此处不兜底，避免给用户看到无意义的占位题目。
        return None
    if kind == "exception":
        return normalize_hitl_schema(
            default_exception_hitl_schema(node_id, reason=reason)
        )
    if kind == "result_confirm" and node_id and binding.get("human_confirm"):
        return normalize_hitl_schema(default_hitl_form_schema(node_id))
    if node_id and binding.get("human_confirm"):
        return normalize_hitl_schema(default_hitl_form_schema(node_id))
    return None


_VALID_HITL_KINDS = ("interactive", "result_confirm", "exception")

# 颗粒度启发式：从 summary 推断「待确认决策点数量」
_DECISION_COUNT_PATTERNS = [
    # "14 个 P0 问题"、"10 个待确认项"、"6 个决策点"
    re.compile(r"(\d{1,3})\s*个\s*(?:P[0-9]\s*)?(?:问题|决策点|待澄清|待确认项?|要点)", re.IGNORECASE),
    # "14 questions" / "14 decisions"
    re.compile(r"(\d{1,3})\s*(?:questions?|decisions?|items?)\b", re.IGNORECASE),
]
# 编号列表项："1." / "1、" / "1) " / "1）" / "问题1：" / "Q1." 等
_LIST_ITEM_PATTERNS = [
    re.compile(r"(?m)^\s*\d{1,3}\s*[\.\、\)\）]\s+\S"),
    re.compile(r"(?m)^\s*问题\s*\d{1,3}\s*[：:.]\s*\S"),
    re.compile(r"(?m)^\s*Q\d{1,3}\s*[\.\、\):：]\s*\S", re.IGNORECASE),
]

# 题目标题中的「N 项/条」计数（如「验收标准（7项）」）
_COUNT_IN_TITLE_RE = re.compile(
    r"（(\d{1,3})\s*[项条个]）|\((\d{1,3})\s*(?:items?|项|条)\)|共\s*(\d{1,3})\s*[项条个]",
    re.IGNORECASE,
)
# 章节/清单「签收式」meta 题（须附带可审阅正文，不能只给维度关键词）
_META_REVIEW_TITLE_RE = re.compile(
    r"是否(?:满足|完整|准确|覆盖|可接受|充分|达标)|(?:完整|准确|充分)(?:覆盖|记录)",
    re.IGNORECASE,
)
# 仅维度关键词、无实质正文的 context（如「含配置/触发/手动/日志」）
_KEYWORD_ONLY_CONTEXT_RE = re.compile(
    r"^[\s含包括涵盖涉及]*(?:[\u4e00-\u9fffA-Za-z0-9_/、,，\s]+(?:关系|维度|方面)?)[\s。．.]*$",
    re.IGNORECASE,
)
_CONTEXT_LIST_LINE_RE = re.compile(
    r"(?m)^\s*(?:[-*•]|\d{1,3}\s*[\.\、\)\）]|Q\d+\.|AC\d+[\.:：]|\|\s*\d+\s*\|)\s*\S",
    re.IGNORECASE,
)


# summary 禁止混入 SOP 预告 / Worker Phase 路线图（见 meeting-room SKILL §4.5.2）
_SUMMARY_ROADMAP_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?m)^\s*#{1,3}\s*下一步\s*$", re.IGNORECASE), "「### 下一步」章节"),
    (re.compile(r"确认后\s*[→\-—>]", re.IGNORECASE), "「确认后 → …」式流程预告"),
    (re.compile(r"Phase\s*[1-9]\d*", re.IGNORECASE), "Phase 1~N 实施路线图表述"),
    (
        re.compile(r"进入\s*.{0,16}?(方案设计|下一阶段|下一节点|下一\s*SOP)", re.IGNORECASE),
        "「进入某某阶段/节点」式预告",
    ),
]


def _validate_summary_no_roadmap(summary: str, *, kind: str) -> None:
    """``summary`` 仅列本节点待确认要点，不得写路线图或 SOP 流程预告。"""
    text = (summary or "").strip()
    if not text or kind == "exception":
        return
    hits = [label for pat, label in _SUMMARY_ROADMAP_CHECKS if pat.search(text)]
    if not hits:
        return
    raise ValueError(
        "summary 待确认总结不得包含流程/路线图预告："
        + "、".join(hits)
        + "。请只保留与 questions 题号对齐的待确认简表，"
        "勿写 ### 下一步、确认后进入某阶段、Phase 1~N 或 SOP 下一节点预告"
        "（见 whalecloud-dev-tool-meeting-room SKILL §4.5.2）。"
    )


def _extract_count_from_title(title: str) -> int:
    """从题目标题解析「N 项/条」计数；无法解析则 0。"""
    text = (title or "").strip()
    if not text:
        return 0
    best = 0
    for m in _COUNT_IN_TITLE_RE.finditer(text):
        for g in m.groups():
            if g is None:
                continue
            try:
                n = int(g)
            except (TypeError, ValueError):
                continue
            if 2 <= n <= 200:
                best = max(best, n)
    return best


def _count_context_list_items(context: str) -> int:
    """统计 context 中列表/表格行数量（用于校验「N 项」题是否列全）。"""
    text = (context or "").strip()
    if not text:
        return 0
    return len(_CONTEXT_LIST_LINE_RE.findall(text))


def _is_keyword_only_context(context: str) -> bool:
    """context 是否仅为维度关键词枚举（无逐条正文）。"""
    text = (context or "").strip()
    if not text or len(text) > 160:
        return False
    if _count_context_list_items(text) >= 2:
        return False
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 80:
        return False
    return bool(_KEYWORD_ONLY_CONTEXT_RE.match(text))


def _validate_question_context_substance(
    question: dict[str, Any],
    *,
    idx: int,
    kind: str,
) -> None:
    """interactive / result_confirm：禁止「有题无内容」的签收式空壳题。"""
    kind_norm = (kind or "").strip().lower()
    if kind_norm not in ("interactive", "result_confirm"):
        return

    qid = str(question.get("id") or "").strip() or f"q{idx + 1}"
    title = str(question.get("title") or "").strip()
    context = str(question.get("context") or "").strip()
    qtype = str(question.get("type") or "").strip().lower()

    if qid == HUMAN_SUPPLEMENT_QUESTION_ID or qtype in ("text", "textarea"):
        return

    expected_n = _extract_count_from_title(title)
    is_meta_review = bool(_META_REVIEW_TITLE_RE.search(title))

    if expected_n >= 2:
        listed = _count_context_list_items(context)
        min_required = min(expected_n, max(3, expected_n // 2 + 1))
        if listed < min_required and len(context) < expected_n * 40:
            raise ValueError(
                f"questions[{idx}]（id={qid}）title 声明 {expected_n} 项/条，"
                f"但 context 仅列出 {listed} 条或正文过短。"
                "请在 context 中用 Markdown 列表或表格**逐条写出**待用户审阅的完整内容"
                "（不可只用「含 A/B/C 维度」类关键词替代）。"
            )

    if is_meta_review:
        if not context:
            raise ValueError(
                f"questions[{idx}]（id={qid}）为章节/清单签收题（{title[:40]}…），"
                "必须填写 context，嵌入待审阅的**完整章节正文或逐条清单**，"
                "让用户无需离开表单即可核对内容。"
            )
        if _is_keyword_only_context(context):
            raise ValueError(
                f"questions[{idx}]（id={qid}）context 仅为维度关键词"
                f"（{context[:60]}…），不可作为签收依据。"
                "请把被询问的章节/清单**全文或逐条列表**写入 context。"
            )
        if len(context) < 80 and _count_context_list_items(context) < 2:
            raise ValueError(
                f"questions[{idx}]（id={qid}）签收题 context 过短（{len(context)} 字），"
                "请补充完整待审阅内容后再提交问卷。"
            )


def _validate_questions_context_substance(
    questions: list[dict[str, Any]],
    *,
    kind: str,
) -> None:
    for idx, q in enumerate(questions):
        if isinstance(q, dict):
            _validate_question_context_substance(q, idx=idx, kind=kind)


def _infer_expected_question_count(summary: str) -> int:
    """从 summary 推断「至少应有多少道题」。0 表示无法判定。"""
    text = (summary or "").strip()
    if not text:
        return 0
    best = 0
    for pat in _DECISION_COUNT_PATTERNS:
        for m in pat.finditer(text):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 2 <= n <= 200:
                best = max(best, n)
    list_total = 0
    for pat in _LIST_ITEM_PATTERNS:
        list_total = max(list_total, len(pat.findall(text)))
    if list_total >= 3:
        best = max(best, list_total)
    return best


def coerce_questionnaire_schema(
    *,
    kind: str,
    questions: Any,
    title: str = "",
    description: str = "",
    summary: str = "",
    render: dict[str, Any] | None = None,
    enforce_granularity: bool = True,
) -> dict[str, Any]:
    """工具入参 → 标准 questionnaire schema；用于 submit_hitl_questionnaire。

    若 ``enforce_granularity=True`` 且 ``summary`` 推断出的待确认决策点数显著
    多于 ``questions`` 数量（默认阈值：questions < expected/2），抛 ValueError，
    强迫 LLM 按「一个决策点一道题」重组问卷。
    """
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions 必须为非空数组")

    kind_norm = (kind or "").strip().lower()
    if kind_norm not in _VALID_HITL_KINDS:
        raise ValueError(
            f"kind 必须是 {'/'.join(_VALID_HITL_KINDS)}，收到 {kind!r}"
        )

    summary_expected = _infer_expected_question_count(summary.strip()) if summary.strip() else 0
    valid_questions: list[dict[str, Any]] = []
    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f"questions[{idx}] 必须为对象")
        qid = str(q.get("id") or "").strip() or f"q{idx + 1}"
        qtype = str(q.get("type") or "single").strip().lower()
        if qtype not in ("single", "multiple", "boolean", "text", "textarea"):
            raise ValueError(
                f"questions[{idx}].type 必须是 single/multiple/boolean/text/textarea"
            )
        qtitle = str(q.get("title") or "").strip()
        if not qtitle:
            raise ValueError(f"questions[{idx}].title 不能为空")
        entry = dict(q)
        entry["id"] = qid
        entry["type"] = qtype
        entry["title"] = qtitle
        # 兼容 LLM 输出 ``{"id": "...", "label": "..."}``（无 value）的题型选项；
        # 统一为 ``{"value": "...", "label": "..."}``，避免前端用 undefined 主键。
        raw_opts = entry.get("options")
        if isinstance(raw_opts, list):
            normalized_opts: list[dict[str, Any]] = []
            for opt_idx, opt in enumerate(raw_opts):
                if not isinstance(opt, dict):
                    continue
                raw_val = opt.get("value")
                if raw_val is not None and raw_val is not False and str(raw_val).strip() != "":
                    value = _normalize_option_value(raw_val)
                else:
                    value = (
                        str(opt.get("id") or "").strip()
                        or str(opt.get("label") or "").strip()
                        or f"opt_{opt_idx}"
                    )
                    value = _normalize_option_value(value) or value
                normalized_opts.append(
                    {
                        "value": value,
                        "label": str(opt.get("label") or value),
                        **{
                            k: v
                            for k, v in opt.items()
                            if k not in ("value", "label", "id")
                        },
                    }
                )
            entry["options"] = normalized_opts
        _maybe_normalize_boolean_question(entry)
        if kind_norm == "interactive":
            from synapse.rd_meeting.questionnaire_repair import repair_embedded_options

            entry = repair_embedded_options(entry, idx=idx)
            qtype = str(entry.get("type") or qtype).strip().lower()
        # 选项题由前端/归一化自动附加人工输入框，不再要求 LLM 显式 inputEnabled
        if qtype in ("single", "multiple") and qid != HUMAN_SUPPLEMENT_QUESTION_ID:
            entry["inputEnabled"] = True
            if not entry.get("inputPlaceholder"):
                entry["inputPlaceholder"] = "或者你的答案："
        valid_questions.append(entry)

    if kind_norm == "interactive":
        from synapse.rd_meeting.questionnaire_repair import validate_no_stacked_decisions

        validate_no_stacked_decisions(valid_questions, summary_expected=summary_expected)

    schema: dict[str, Any] = {
        "type": QUESTIONNAIRE_TYPE,
        "version": QUESTIONNAIRE_VERSION,
        "title": (title or "").strip() or "人工确认",
        "description": (description or "").strip(),
        "questions": valid_questions,
    }
    if render and isinstance(render, dict):
        schema["render"] = render
    else:
        accent_map = {"exception": "violet", "result_confirm": "blue", "interactive": "emerald"}
        schema["render"] = {
            "layout": "stepped",
            "showOverallProgress": True,
            "progressBasis": "step",
            "accent": accent_map[kind_norm],
            "animate": True,
        }
    summary_text = summary.strip()
    if summary_text:
        _validate_summary_no_roadmap(summary_text, kind=kind_norm)
        schema["summary_markdown"] = summary_text
    schema["intervention_kind"] = kind_norm

    if enforce_granularity and kind_norm in ("result_confirm", "interactive"):
        expected = _infer_expected_question_count(summary)
        actual = len(valid_questions)
        if expected >= 3 and actual * 2 < expected:
            raise ValueError(
                "问卷题目颗粒度不达标："
                f"summary 中推断到至少 {expected} 个待确认决策点，"
                f"当前只提供 {actual} 道题。请按「一个决策点 = 一道独立题」拆分："
                "每个待澄清问题（如「问题1～问题14」）都要单独成题，把可默认结论作为"
                "推荐选项（可标 ✅），即使你已经给出建议值也不要合并题目。"
            )

    _validate_questions_context_substance(valid_questions, kind=kind_norm)

    return normalize_hitl_schema(schema) or schema


def _option_style_for(qtype: QuestionType) -> OptionStyle:
    if qtype == "multiple":
        return "checkbox"
    if qtype == "boolean":
        return "boolean"
    return "radio"


def _letter_options(labels: list[str]) -> list[dict[str, Any]]:
    return [
        {"value": chr(65 + i), "label": label, "selected": False}
        for i, label in enumerate(labels)
    ]


def _value_options(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """(value, label) 对，用于 decision 等需固定 value 的字段。"""
    return [{"value": v, "label": label, "selected": False} for v, label in pairs]


def _boolean_options() -> list[dict[str, Any]]:
    return [
        {"value": "true", "label": "是", "selected": False},
        {"value": "false", "label": "否", "selected": False},
    ]


def _normalize_option_value(raw: Any) -> str:
    """选项 value 归一化：bool / True / 是 → ``true``，避免前端选中态失配。"""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    text = str(raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low in ("true", "yes", "y", "1", "是"):
        return "true"
    if low in ("false", "no", "n", "0", "否"):
        return "false"
    return text


def _looks_like_boolean_options(opts: list[Any]) -> bool:
    if len(opts) != 2:
        return False
    labels: set[str] = set()
    values: set[str] = set()
    for o in opts:
        if not isinstance(o, dict):
            return False
        labels.add(str(o.get("label") or "").strip())
        values.add(_normalize_option_value(o.get("value")) or str(o.get("label") or "").strip())
    if labels <= {"是", "否"}:
        return True
    return values <= {"true", "false"}


def _apply_boolean_question_shape(item: dict[str, Any]) -> None:
    """是/否 判断题：统一 value=true/false + optionStyle=boolean。"""
    item["type"] = "single"
    item["options"] = _boolean_options()
    render = dict(item.get("render") or {})
    render["optionStyle"] = "boolean"
    item["render"] = render


def _maybe_normalize_boolean_question(entry: dict[str, Any]) -> None:
    qtype = str(entry.get("type") or "single").strip().lower()
    opts = entry.get("options")
    opt_list = list(opts) if isinstance(opts, list) else []
    style = str((entry.get("render") or {}).get("optionStyle") or "").strip().lower()
    if qtype == "boolean" or style == "boolean" or _looks_like_boolean_options(opt_list):
        _apply_boolean_question_shape(entry)


def build_question(
    *,
    qid: str,
    qtype: QuestionType,
    title: str,
    context: str = "",
    options: list[dict[str, Any]] | None = None,
    input_enabled: bool = False,
    input_placeholder: str = "或者你的答案：",
    required: bool = False,
    option_style: OptionStyle | None = None,
    layout: str = "vertical",
    show_progress: bool = True,
    current: int = 1,
    total: int = 1,
) -> dict[str, Any]:
    """构造单题 JSON（questionnaire v1.0 子项）。"""
    style = option_style or _option_style_for(qtype)
    opts = list(options or [])
    if qtype == "boolean" and not opts:
        opts = _boolean_options()
    return {
        "id": qid,
        "type": qtype if qtype != "boolean" else "single",
        "title": title,
        "context": context,
        "options": opts,
        "inputEnabled": input_enabled,
        "inputPlaceholder": input_placeholder if input_enabled else "",
        "required": required,
        "render": {
            "layout": layout,
            "optionStyle": style,
            "showProgress": show_progress,
            "progress": {"current": current, "total": total},
        },
    }


def build_human_supplement_question() -> dict[str, Any]:
    """所有人机场景末尾的选填补充题（长文本输入，独立于上方各题答案）。"""
    return build_question(
        qid=HUMAN_SUPPLEMENT_QUESTION_ID,
        qtype="textarea",
        title=HUMAN_SUPPLEMENT_TITLE,
        context="选填。此处为自由补充说明，不会覆盖您在上方各题中的选择；无补充可留空直接提交。",
        required=False,
        show_progress=False,
    )


def append_human_supplement_question(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """在题目列表末尾追加统一补充题（已存在同 id/标题则跳过）。"""
    out = [dict(q) for q in questions if isinstance(q, dict)]
    if any(str(q.get("id") or "").strip() == HUMAN_SUPPLEMENT_QUESTION_ID for q in out):
        return out
    if any(HUMAN_SUPPLEMENT_TITLE in str(q.get("title") or "") for q in out):
        return out
    out.append(build_human_supplement_question())
    return out


def attach_question_progress(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为题目列表写入题序 progress（current=第几题，total=总题数；非已填题数）。"""
    total = len(questions)
    out: list[dict[str, Any]] = []
    for idx, q in enumerate(questions, start=1):
        item = dict(q)
        render = dict(item.get("render") or {})
        render["showProgress"] = render.get("showProgress", True)
        render["progress"] = {"current": idx, "total": total}
        item["render"] = render
        out.append(item)
    return out


def _default_questions_for_node(node_id: str, *, node_name: str, intent: str) -> list[dict[str, Any]]:
    """按节点生成默认人机确认问卷（多题型 + 进度条 + 自定义输入）。"""
    intent_hint = intent.strip() or f"完成节点「{node_name}」的会议目标"
    raw = [
        build_question(
            qid="quality_check",
            qtype="boolean",
            title="产出质量",
            context=(
                f"请审阅待确认总结：节点「{node_name}」的交付内容是否完整、准确，"
                f"且符合会议目标「{intent_hint}」？"
            ),
            input_enabled=True,
            input_placeholder="如有具体质量问题，请在此说明：",
            required=False,
        ),
        build_question(
            qid="risk_ack",
            qtype="single",
            title="风险与遗留项",
            context="总结中是否已明确标注未决风险、依赖阻塞或需后续跟进的遗留项？",
            options=_letter_options(
                [
                    "已充分标注，可接受",
                    "部分标注，需补充说明（可在下方填写）",
                    "未标注或存在重大遗漏",
                ]
            ),
            input_enabled=True,
            required=False,
        ),
        build_question(
            qid="decision",
            qtype="single",
            title="确认结论",
            context="基于上述审阅，请选择下一步操作。确认通过后系统将写入归档产物并推进至下一节点。",
            options=_value_options(
                [
                    ("approve", "通过 — 归档产出并进入下一节点"),
                    ("reject", "不通过 — 按补充说明返工本节点"),
                ]
            ),
            input_enabled=False,
            required=True,
            option_style="radio",
        ),
        build_question(
            qid="comment",
            qtype="textarea",
            title="补充说明",
            context="可选：记录评审意见、返工原因、验收备注或给智能体的后续指引。",
            options=[],
            input_enabled=True,
            input_placeholder="输入补充说明…",
            required=False,
        ),
    ]
    return attach_question_progress(raw)


def default_hitl_form_schema(node_id: str) -> dict[str, Any]:
    """节点结束后的「结果确认」问卷（归档验收）；会中澄清须由智能体技能产出 questionnaire。"""
    entry = get_node_manifest_entry(node_id)
    name = str(entry.get("name") if entry else node_display_name(node_id))
    intent = str(entry.get("intent") if entry else "")
    questions = _default_questions_for_node(node_id, node_name=name, intent=intent)
    return {
        "type": QUESTIONNAIRE_TYPE,
        "version": QUESTIONNAIRE_VERSION,
        "title": f"{name} — 人工确认",
        "description": (
            (intent or f"请审阅节点「{name}」的待确认总结，逐项回答下方问题后提交。")
            + " 系统将依据「确认结论」决定归档推进或返工重跑。"
        ),
        "render": {
            "layout": "stepped",
            "showOverallProgress": True,
            "progressBasis": "step",
            "accent": "blue",
            "animate": True,
        },
        "questions": questions,
    }


def _exception_questions(node_name: str, reason: str) -> list[dict[str, Any]]:
    short_reason = (reason or "").strip().splitlines()[0] if reason else ""
    short_reason = short_reason[:160] if short_reason else "（系统未捕获到具体原因）"
    raw = [
        build_question(
            qid="exception_ack",
            qtype="boolean",
            title="我已知悉本次异常",
            context=(
                f"节点「{node_name}」执行过程中出现异常：{short_reason}\n"
                "请确认你已阅读上方异常摘要后再决定下一步操作。"
            ),
            input_enabled=False,
            required=True,
        ),
        build_question(
            qid="decision",
            qtype="single",
            title="下一步操作",
            context="选择系统应执行的恢复动作。",
            options=_value_options(
                [
                    ("retry", "重跑本节点 — 智能体会带上你的备注重新执行"),
                    ("abort", "终止节点 — 标记会议异常结束，等待人工兜底"),
                    ("escalate", "升级人工接管 — 暂停流水线，转交研发组长"),
                ]
            ),
            input_enabled=False,
            required=True,
            option_style="radio",
        ),
        build_question(
            qid="risk_level",
            qtype="single",
            title="风险级别评估",
            context="本次异常对整体研发流水线的潜在影响。",
            options=_value_options(
                [
                    ("low", "可控 — 仅本节点受影响"),
                    ("medium", "需关注 — 可能波及后续节点"),
                    ("high", "重大 — 需阻塞流水线立即处理"),
                ]
            ),
            input_enabled=False,
            required=False,
            option_style="radio",
        ),
        build_question(
            qid="comment",
            qtype="textarea",
            title="备注 / 重跑指引",
            context="可选：补充异常上下文、指明重跑时智能体应注意的事项。",
            options=[],
            input_enabled=True,
            input_placeholder="例如：忽略 X 字段格式异常 / 重新校验 Y 接口…",
            required=False,
        ),
    ]
    return attach_question_progress(raw)


def default_exception_hitl_schema(
    node_id: str, *, reason: str = ""
) -> dict[str, Any]:
    """异常门控默认问卷（避免 ``human_intervention`` 时前端白屏）。"""
    entry = get_node_manifest_entry(node_id)
    name = str(entry.get("name") if entry else node_display_name(node_id))
    short_reason = (reason or "").strip()
    desc = (
        f"节点「{name}」未通过系统校验或主控未提交结构化问卷，已进入异常门控。"
        "请审阅下方异常摘要后选择处置动作；提交后系统会按你的选择继续执行。"
    )
    return {
        "type": QUESTIONNAIRE_TYPE,
        "version": QUESTIONNAIRE_VERSION,
        "title": f"{name} — 异常人工裁决",
        "description": desc,
        "render": {
            "layout": "stepped",
            "showOverallProgress": True,
            "progressBasis": "step",
            "accent": "violet",
            "animate": True,
        },
        "summary_kind": "exception",
        "summary_reason": short_reason,
        "questions": _exception_questions(name, short_reason),
    }


def ensure_question_input_guardrails(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """组件级护栏（后端归一化）：每题可输入；无选项的选择题降级为 textarea。"""
    out: list[dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        item = dict(q)
        qid = str(item.get("id") or "").strip()
        qtype = str(item.get("type") or "single").strip().lower()
        if qid == HUMAN_SUPPLEMENT_QUESTION_ID or qtype in ("text", "textarea"):
            out.append(item)
            continue
        opts = item.get("options")
        has_opts = isinstance(opts, list) and len(opts) > 0
        if qtype in ("single", "multiple") and not has_opts:
            item["type"] = "textarea"
            item["options"] = []
            if not item.get("inputPlaceholder"):
                item["inputPlaceholder"] = "请输入您的回答…"
            out.append(item)
            continue
        if qtype == "boolean" and not has_opts:
            item["type"] = "single"
            item["options"] = _boolean_options()
            item.setdefault("render", {})["optionStyle"] = "boolean"
        elif qtype == "boolean" or _looks_like_boolean_options(list(opts) if isinstance(opts, list) else []):
            _apply_boolean_question_shape(item)
        item["inputEnabled"] = True
        if not item.get("inputPlaceholder"):
            item["inputPlaceholder"] = "或者你的答案："
        out.append(item)
    return out


def normalize_hitl_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """归一化 schema：补全 questionnaire v1.0 元数据与题目进度。"""
    if not schema or not isinstance(schema, dict):
        return schema
    out = dict(schema)
    questions = out.get("questions")
    if not isinstance(questions, list) or not questions:
        return out
    if not out.get("type"):
        out["type"] = QUESTIONNAIRE_TYPE
    if not out.get("version"):
        out["version"] = QUESTIONNAIRE_VERSION
    kind_norm = str(out.get("intervention_kind") or "").strip().lower()
    question_list = list(questions)
    if kind_norm == "interactive":
        from synapse.rd_meeting.questionnaire_repair import apply_interactive_question_repairs

        summary_text = str(out.get("summary_markdown") or "")
        question_list = apply_interactive_question_repairs(question_list, summary=summary_text)
    guarded = ensure_question_input_guardrails(question_list)
    merged = append_human_supplement_question(guarded)
    out["questions"] = attach_question_progress(merged)
    return out


def resolve_hitl_form_schema(
    node_id: str,
    *,
    node_override: dict[str, Any],
) -> dict[str, Any] | None:
    """节点 binding 预置 schema：仅显式配置或结果确认默认模板；会中澄清不在此生成。"""
    custom = node_override.get("hitl_form_schema")
    if isinstance(custom, dict) and custom.get("questions"):
        return normalize_hitl_schema(custom)
    if node_id == "req_clarify":
        return None
    return default_hitl_form_schema(node_id)


def _type_label(q: dict[str, Any]) -> str:
    qtype = str(q.get("type") or "single")
    style = str((q.get("render") or {}).get("optionStyle") or "")
    if style == "boolean" or (
        qtype == "single"
        and len(q.get("options") or []) == 2
        and {str(o.get("value")) for o in (q.get("options") or []) if isinstance(o, dict)}
        == {"true", "false"}
    ):
        return "判断"
    mapping = {
        "single": "单选",
        "multiple": "多选",
        "boolean": "判断",
        "text": "填空",
        "textarea": "长文本",
    }
    return mapping.get(qtype, qtype)


def format_hitl_schema_for_prompt(schema: dict[str, Any] | None) -> str:
    """将表单 schema 压缩为可注入小鲸 system/user 的说明。"""
    if not schema:
        return ""
    normalized = normalize_hitl_schema(schema) or schema
    lines = [
        f"标题：{normalized.get('title') or '人工确认'}",
    ]
    desc = str(normalized.get("description") or "").strip()
    if desc:
        lines.append(f"说明：{desc}")

    questions = normalized.get("questions")
    if isinstance(questions, list) and questions:
        lines.append(f"需收集的问题（共 {len(questions)} 题，请引导用户逐项确认）：")
        for idx, q in enumerate(questions, start=1):
            if not isinstance(q, dict):
                continue
            title = str(q.get("title") or q.get("id") or "")
            ctx = str(q.get("context") or "").strip()
            req = "必填" if q.get("required") else "选填"
            typ = _type_label(q)
            lines.append(f"{idx}. [{typ}, {req}] {title}")
            if ctx:
                lines.append(f"   场景：{ctx}")
            opts = q.get("options")
            if isinstance(opts, list) and opts:
                parts = [
                    f"{o.get('value', '')}: {o.get('label', '')}"
                    for o in opts
                    if isinstance(o, dict)
                ]
                lines.append(f"   选项：{' | '.join(p for p in parts if p.strip(': '))}")
            if q.get("inputEnabled"):
                ph = str(q.get("inputPlaceholder") or "或者你的答案")
                lines.append(f"   支持自定义输入（{ph}）")
        lines.append(
            "提交后系统解析 ``decision`` 字段：``approve`` 归档推进，``reject`` 触发返工；"
            "``comment`` 为补充说明。"
        )
        return "\n".join(lines)

    return "\n".join(lines)
