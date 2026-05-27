"""人机问卷反馈：结构化解析、自由输入判定、Host 续跑提示。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from synapse.rd_meeting.hitl_form import HUMAN_SUPPLEMENT_QUESTION_ID

HitlFeedbackMode = Literal["options_only", "with_free_text"]

_HITL_FORM_PREFIX = "[人工确认表单]"

_PROMPT_OPTIONS_ONLY = """
## 系统提示：用户已完成问卷（仅选项反馈，无额外自由输入）

用户已通过会中问卷做出选择，**未**在题目自定义输入框或末尾补充栏填写额外说明。

**本次要求**：
1. **逐条阅读**上方「本轮人工确认反馈（结构化）」JSON：以用户选项为约束，结合工单、产品、代码仓库等**真实上下文**，更新或落盘本节点约定产出物（NODE_OUTPUTS 中的 Markdown）。
2. 不得无视或弱化用户选项；选项即用户决策，写入产出物时必须体现。
3. 若选项与现有产物/分析冲突，以用户选项为准并简要说明调整点。
4. 无需再次提交 interactive 问卷，除非出现新的未决决策点。
5. 完成产出物更新后停止；系统将进入节点完成确认（NodeReview）。
""".strip()

_PROMPT_WITH_FREE_TEXT = """
## 系统提示：用户已完成问卷（含自由输入，需认真总结并多轮推进）

用户在题目自定义输入框和/或末尾「还有什么需要补充的吗」中提供了**自由文本**。

**本次要求**：
1. **先总结**：逐条整理「本轮人工确认反馈（结构化）」JSON——每题的用户选项与用户输入，形成「用户意图与约束摘要」（不得省略任何输入细节）。
2. **再推进**：基于该摘要，结合工单、产品、代码真实信息，继续分析、委派协作智能体、更新产出物；凡用户输入中的新要求、例外、约束必须显式响应。
3. **多轮问卷（允许且常见）**：收敛后**应**再次 ``submit_hitl_questionnaire(kind="interactive")`` 让用户对更新后的章节/清单签收；若无新未决点则推进产出物直至可验收。
4. 禁止用泛泛复述代替对用户输入的针对性回应。
""".strip()

_PROMPT_FOLLOWUP_INTERACTIVE_ROUND = """
## 系统提示：第 {round_n} 轮会中问卷（内容签收 / 续澄清）

用户已在前面轮次完成澄清；本轮问卷用于**呈现已收敛内容供人工签收**，或继续未决决策点。

**硬约束（工具会校验，不达标将拒绝提交）**：
1. **summary**：表单顶部会渲染给用户——写本节点核心变化、产出文件、与 ``questions`` 对齐的待确认简表（可含表格）；**禁止** SOP 下一节点 / Phase 路线图预告。
2. **每题 context 必须可独立审阅**：
   - 题目标题含「（N项）」「共 N 条」→ context **逐条列出 N 条完整内容**（Markdown 列表或表格），禁止只用「含 A/B/C 维度」。
   - 题为「XX 是否满足/完整/覆盖」类签收 → context 必须嵌入**该章节/清单的全文或逐条列表**（从已写归档 Markdown ``read_file`` 摘录），让用户不离开表单即可核对。
3. **禁止空壳 meta 题**：不得只问「7 项验收标准是否 OK」却在 context 里只写「含配置/触发/日志…」关键词。
4. 调用 ``submit_hitl_questionnaire`` 后立即停止；正文摘要由 ``summary`` + 各题 ``context`` 承担，勿依赖 tool 返回后的聊天输出。
""".strip()


def prompt_for_followup_interactive_round(round_n: int) -> str:
    """第 2 轮及以后会中问卷：注入内容签收约束。"""
    n = max(2, int(round_n or 2))
    return _PROMPT_FOLLOWUP_INTERACTIVE_ROUND.format(round_n=n)


def prompt_after_hitl_feedback(mode: HitlFeedbackMode, *, followup_round: int = 0) -> str:
    base = _PROMPT_WITH_FREE_TEXT if mode == "with_free_text" else _PROMPT_OPTIONS_ONLY
    if followup_round >= 2:
        return f"{base}\n\n{prompt_for_followup_interactive_round(followup_round)}"
    if followup_round == 1 and mode == "with_free_text":
        return (
            f"{base}\n\n"
            "## 续跑提示\n"
            "用户已提供自由文本纠偏；更新产出物后，**建议**再交一轮 ``interactive`` 问卷"
            "让用户对收敛后的章节/清单签收（每题 context 须含完整待审阅正文）。"
        )
    return base


def _normalize_option_key(raw: Any, idx: int = 0) -> str:
    if isinstance(raw, bool):
        return "true" if raw else "false"
    text = str(raw or "").strip()
    if not text:
        return f"opt_{idx}"
    low = text.lower()
    if low in ("true", "yes", "y", "1") or text == "是":
        return "true"
    if low in ("false", "no", "n", "0") or text == "否":
        return "false"
    return text


def _question_option_index(question: dict[str, Any]) -> dict[str, str]:
    """option key → display label."""
    mapping: dict[str, str] = {}
    for idx, opt in enumerate(question.get("options") or []):
        if not isinstance(opt, dict):
            continue
        label = str(opt.get("label") or opt.get("value") or opt.get("id") or "").strip()
        for candidate in (opt.get("value"), opt.get("id"), opt.get("label")):
            if candidate is None:
                continue
            key = _normalize_option_key(candidate, idx)
            mapping[key] = label or key
    return mapping


def _question_by_id(schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(schema, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for q in schema.get("questions") or []:
        if isinstance(q, dict):
            qid = str(q.get("id") or "").strip()
            if qid:
                out[qid] = q
    return out


def split_question_answer(
    question: dict[str, Any] | None,
    raw: Any,
) -> tuple[list[str], str]:
    """拆分解答题答案 → (选项 keys, 用户自由输入)。"""
    q = question or {}
    qid = str(q.get("id") or "").strip()
    qtype = str(q.get("type") or "").strip().lower()

    if qtype in ("text", "textarea") or qid == HUMAN_SUPPLEMENT_QUESTION_ID:
        text = str(raw or "").strip() if raw is not None else ""
        return [], text

    opt_index = _question_option_index(q)
    known = set(opt_index)
    selected: list[str] = []
    custom = ""

    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif raw is None or str(raw).strip() == "":
        items = []
    else:
        items = [raw]

    for item in items:
        s = str(item).strip()
        if not s:
            continue
        if s.startswith("OTHER:"):
            custom = s[6:].strip() or custom
            continue
        key = _normalize_option_key(s)
        if key in known:
            selected.append(key)
        elif s in known:
            selected.append(s)
        else:
            # parse_hitl_form_text 可能已剥掉 OTHER: 前缀
            custom = custom if custom else s

    return selected, custom


def _format_option_labels(question: dict[str, Any], option_keys: list[str]) -> str:
    if not option_keys:
        return "（无）"
    opt_index = _question_option_index(question)
    labels = [opt_index.get(k, k) for k in option_keys]
    return "；".join(labels)


def classify_hitl_feedback_mode(
    values: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    comment: str = "",
) -> HitlFeedbackMode:
    """区分「仅选项」与「含自由输入（题目输入框 / 末尾补充 / 文本题）」。"""
    if user_has_free_text_input(values, schema, comment=comment):
        return "with_free_text"
    return "options_only"


def user_has_free_text_input(
    values: dict[str, Any],
    schema: dict[str, Any] | None = None,
    *,
    comment: str = "",
) -> bool:
    """是否含用户自由输入（非纯选项反馈）。

    覆盖：
    - 各题选项旁的自定义输入（``OTHER:…`` 或解析后无法匹配选项的文本）
    - 末尾 ``human_supplement`` 补充题
    - ``text`` / ``textarea`` 题型答案
    - 表单 ``补充说明`` / comment 行
    """
    if (comment or "").strip():
        return True

    qmap = _question_by_id(schema)
    seen: set[str] = set()

    for qid, q in qmap.items():
        if qid in values:
            seen.add(qid)
        raw = values.get(qid)
        _, custom = split_question_answer(q, raw)
        if custom:
            return True

    for qid, raw in values.items():
        if qid in seen:
            continue
        q = qmap.get(qid, {})
        _, custom = split_question_answer(q, raw)
        if custom:
            return True

    return False


def format_hitl_feedback_structured(
    values: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    comment: str = "",
) -> str:
    """格式化问卷反馈：题目标题、用户选项、用户输入。"""
    mode = classify_hitl_feedback_mode(values, schema, comment=comment)
    mode_label = "含自由输入" if mode == "with_free_text" else "仅选项"
    lines = [
        _HITL_FORM_PREFIX,
        "",
        "## 用户问卷反馈（结构化）",
        "",
        f"**反馈模式**：{mode_label}",
        "",
    ]

    qmap = _question_by_id(schema)
    ordered_ids: list[str] = []
    for q in (schema or {}).get("questions") or []:
        if isinstance(q, dict):
            qid = str(q.get("id") or "").strip()
            if qid and qid != HUMAN_SUPPLEMENT_QUESTION_ID:
                ordered_ids.append(qid)
    for qid in values:
        if qid not in ordered_ids and qid != HUMAN_SUPPLEMENT_QUESTION_ID:
            ordered_ids.append(qid)

    for qid in ordered_ids:
        raw = values.get(qid)
        if raw is None or str(raw).strip() == "":
            continue
        q = qmap.get(qid, {"id": qid, "title": qid})
        title = str(q.get("title") or qid).strip()
        opts, custom = split_question_answer(q, raw)
        lines.append(f"### {title}")
        lines.append(f"- **用户选项**：{_format_option_labels(q, opts)}")
        lines.append(f"- **用户输入**：{custom if custom else '（无）'}")
        lines.append("")

    supplement_q = qmap.get(HUMAN_SUPPLEMENT_QUESTION_ID, {})
    supplement_title = str(supplement_q.get("title") or "请问您还有什么需要补充的吗？").strip()
    supplement_raw = values.get(HUMAN_SUPPLEMENT_QUESTION_ID)
    supplement_text = ""
    if supplement_raw is not None:
        _, supplement_text = split_question_answer(supplement_q or {"id": HUMAN_SUPPLEMENT_QUESTION_ID, "type": "textarea"}, supplement_raw)
    if supplement_text:
        lines.append(f"### {supplement_title}")
        lines.append("- **用户选项**：（无）")
        lines.append(f"- **用户输入**：{supplement_text}")
        lines.append("")

    if (comment or "").strip():
        lines.append("### 表单补充说明")
        lines.append("- **用户选项**：（无）")
        lines.append(f"- **用户输入**：{comment.strip()}")
        lines.append("")

    return "\n".join(lines).strip()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_hitl_round_record(
    values: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    comment: str = "",
    intervention_kind: str = "interactive",
    feedback_mode: HitlFeedbackMode | str = "options_only",
) -> dict[str, Any]:
    """构建单轮问卷结构化记录（与 ``hitl_context.json`` rounds[] 项同构）。"""
    mode = feedback_mode if isinstance(feedback_mode, str) else feedback_mode
    qmap = _question_by_id(schema)
    ordered_ids: list[str] = []
    for q in (schema or {}).get("questions") or []:
        if isinstance(q, dict):
            qid = str(q.get("id") or "").strip()
            if qid and qid != HUMAN_SUPPLEMENT_QUESTION_ID:
                ordered_ids.append(qid)
    for qid in values:
        if qid not in ordered_ids and qid != HUMAN_SUPPLEMENT_QUESTION_ID:
            ordered_ids.append(qid)

    questions: list[dict[str, Any]] = []
    for qid in ordered_ids:
        raw = values.get(qid)
        if raw is None or str(raw).strip() == "":
            continue
        q = qmap.get(qid, {"id": qid, "title": qid})
        title = str(q.get("title") or qid).strip()
        opts, custom = split_question_answer(q, raw)
        opt_index = _question_option_index(q)
        questions.append(
            {
                "id": qid,
                "title": title,
                "selected_options": opts,
                "option_labels": [opt_index.get(k, k) for k in opts],
                "user_input": custom,
            }
        )

    supplement_q = qmap.get(HUMAN_SUPPLEMENT_QUESTION_ID, {})
    supplement_raw = values.get(HUMAN_SUPPLEMENT_QUESTION_ID)
    supplement_text = ""
    if supplement_raw is not None:
        _, supplement_text = split_question_answer(
            supplement_q or {"id": HUMAN_SUPPLEMENT_QUESTION_ID, "type": "textarea"},
            supplement_raw,
        )
    if supplement_text:
        supplement_title = str(supplement_q.get("title") or "请问您还有什么需要补充的吗？").strip()
        questions.append(
            {
                "id": HUMAN_SUPPLEMENT_QUESTION_ID,
                "title": supplement_title,
                "selected_options": [],
                "option_labels": [],
                "user_input": supplement_text,
            }
        )

    kind = (intervention_kind or "interactive").strip().lower() or "interactive"
    return {
        "intervention_kind": kind,
        "submitted_at": _now_iso(),
        "feedback_mode": str(mode),
        "comment": (comment or "").strip(),
        "questions": questions,
    }


def format_hitl_current_round_prompt(round_record: dict[str, Any]) -> str:
    """格式化为注入 host prompt 的「仅本轮」结构化反馈块。"""
    payload = {"current_round": round_record}
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "## 本轮人工确认反馈（结构化）\n\n"
        "以下为**本轮**问卷提交结果；全节点历史见节点归档 ``hitl_context.json``（生成会议产出前须 read_file）。\n\n"
        f"```json\n{body}\n```\n"
    )
