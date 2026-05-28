"""interactive 问卷结构修复与校验：选项泄漏提取、堆叠题拒绝。"""

from __future__ import annotations

import re
from typing import Any

from synapse.rd_meeting.hitl_form import HUMAN_SUPPLEMENT_QUESTION_ID

STACKED_OPTION_THRESHOLD = 5
_DECISION_POINT_MIN_MATCHES = 3

_CHOICE_TYPES = frozenset({"single", "multiple", "boolean"})

_PACKAGED_TITLE_RE = re.compile(
    r"整体确认|批量|汇总|打包|"
    r"以下.*(?:选择|确认)|"
    r"全部.*(?:同意|确认)|"
    r"(?:多项|各.*)(?:确认|选择)",
    re.IGNORECASE,
)
_DECISION_POINT_OPTION_RE = re.compile(
    r"^(?:Q|问题)?\s*\d+[\.、\):：]\s*|"
    r"✅|(?:推荐|默认)|"
    r"[\u4e00-\u9fffA-Za-z0-9_]{2,12}[：:]\s*\S",
    re.IGNORECASE,
)
_LIST_LINE_RE = re.compile(r"(?m)^\s*[-*•]\s+(.+)$")
_OPTION_PREFIX_RE = re.compile(r"(?:可选|选项|请选择)[：:]\s*(.+)")
_LETTER_OPTIONS_RE = re.compile(
    r"(?:^|[\s；;，,（(:：。.])([A-Z])[\.、\)]\s*([^A-Z\n]+?)"
    r"(?=(?:\s+[A-Z][\.、\)]|\s*$|；|;|\n))",
)
_NUMBERED_OPTIONS_RE = re.compile(
    r"(?:^|[\s；;，,（(:：。.]|(?<=[选择]))"
    r"(\d{1,2})[\.、\)]\s*(.+?)"
    r"(?=(?:\s+\d{1,2}[\.、\)]|\s*$|；|;|\n))",
)


def _extract_letter_options(text: str) -> list[tuple[str, str]] | None:
    matches = list(_LETTER_OPTIONS_RE.finditer(text))
    if len(matches) < 2:
        return None
    return [(m.group(1), m.group(2).strip()) for m in matches if m.group(2).strip()]


def _extract_numbered_options(text: str) -> list[tuple[str, str]] | None:
    matches = list(_NUMBERED_OPTIONS_RE.finditer(text))
    if len(matches) < 2:
        return None
    return [(m.group(1), m.group(2).strip()) for m in matches if m.group(2).strip()]


def _extract_list_options(text: str) -> list[tuple[str, str]] | None:
    lines = [line.strip() for line in _LIST_LINE_RE.findall(text) if line.strip()]
    if len(lines) < 2:
        return None
    return [(str(i + 1), line) for i, line in enumerate(lines)]


def _extract_colon_prefixed_options(text: str) -> list[tuple[str, str]] | None:
    match = _OPTION_PREFIX_RE.search(text)
    if not match:
        return None
    body = match.group(1).strip()
    parts = [part.strip() for part in re.split(r"[/／|、]", body) if part.strip()]
    if len(parts) < 2:
        return None
    return [(str(i + 1), part) for i, part in enumerate(parts)]


def _has_embedded_option_patterns(text: str) -> bool:
    body = text or ""
    if len(_extract_letter_options(body) or []) >= 2:
        return True
    if re.search(r"(?:可选|选项|请选择)[：: ]?\s*\S", body):
        if _extract_colon_prefixed_options(body):
            return True
        # 「可选：xxx」但无法拆成 ≥2 项 → 仍视为泄漏，交给 repair 拒绝
        return True
    for line in body.splitlines():
        if len(list(_NUMBERED_OPTIONS_RE.finditer(line))) >= 2:
            return True
    if re.search(r"(?:可选|选项|请选择)", body) and len(_LIST_LINE_RE.findall(body)) >= 2:
        return True
    return False


def _question_id(question: dict[str, Any], idx: int) -> str:
    return str(question.get("id") or "").strip() or f"q{idx + 1}"


def _option_labels(question: dict[str, Any]) -> list[str]:
    opts = question.get("options")
    if not isinstance(opts, list):
        return []
    labels: list[str] = []
    for opt in opts:
        if isinstance(opt, dict):
            labels.append(str(opt.get("label") or opt.get("value") or "").strip())
    return labels


def _count_decision_point_options(labels: list[str]) -> int:
    return sum(1 for label in labels if label and _DECISION_POINT_OPTION_RE.search(label))


def _option_value_from_label(label: str, idx: int) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff]+", "_", label[:48].strip()).strip("_").lower()
    return base or f"opt_{idx}"


def _pairs_to_options(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, (value, label) in enumerate(pairs):
        text = label.strip()
        if not text:
            continue
        key = str(value).strip() or _option_value_from_label(text, idx)
        out.append({"value": key, "label": text})
    return out


def _strip_option_block(text: str) -> str:
    cleaned = text
    patterns = (
        r"(?:请选择[：:])?\s*[A-Z][\.、\)].*$",
        r"(?:可选|选项)[：:].*$",
        r"(?m)^\s*[-*•]\s+.*$",
        r"(?:^|[\s；;，,（(:：。.])\d{1,2}[\.、\)].*$",
    )
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.MULTILINE | re.DOTALL).strip()
    return cleaned or "请从下列选项中选择。"


def extract_embedded_options(
    title: str,
    context: str,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """从 context（优先）或 title 提取嵌入选项。成功返回 (options, new_context, new_title)。"""
    extractors = (
        _extract_letter_options,
        _extract_numbered_options,
        _extract_list_options,
        _extract_colon_prefixed_options,
    )
    for field, text in (("context", context), ("title", title)):
        body = (text or "").strip()
        if not body:
            continue
        for extractor in extractors:
            pairs = extractor(body)
            if not pairs or len(pairs) < 2:
                continue
            options = _pairs_to_options(pairs)
            if len(options) < 2:
                continue
            cleaned = _strip_option_block(body)
            if field == "context":
                return options, cleaned, title
            return options, context, cleaned
    return None


def repair_embedded_options(question: dict[str, Any], *, idx: int) -> dict[str, Any]:
    """interactive：从题面提取 options；检测到会提取但失败则抛 ValueError。"""
    item = dict(question)
    qid = _question_id(item, idx)
    qtype = str(item.get("type") or "single").strip().lower()
    if qid == HUMAN_SUPPLEMENT_QUESTION_ID or qtype not in _CHOICE_TYPES:
        return item
    if qtype == "boolean":
        return item

    opts = item.get("options")
    existing = [o for o in opts if isinstance(o, dict)] if isinstance(opts, list) else []
    if len(existing) >= 2:
        return item

    title = str(item.get("title") or "").strip()
    context = str(item.get("context") or "").strip()
    combined = f"{title}\n{context}"
    if not _has_embedded_option_patterns(combined):
        return item

    extracted = extract_embedded_options(title, context)
    if not extracted:
        raise ValueError(
            f"questions[{idx}]（id={qid}）在 title/context 中检测到选项列表，"
            "但未写入 options[]。请把选项移到 options 字段，context 只保留场景说明。"
        )

    options, new_context, new_title = extracted
    item["options"] = options
    item["context"] = new_context
    item["title"] = new_title
    if qtype == "boolean" and len(options) > 2:
        item["type"] = "single"
    return item


def detect_stacked_decision_question(
    question: dict[str, Any],
    *,
    idx: int,
    question_count: int,
    summary_expected: int = 0,
) -> str | None:
    """检测「多决策点合并为一题」。命中则返回错误说明，否则 None。"""
    qtype = str(question.get("type") or "single").strip().lower()
    if qtype not in ("single", "multiple"):
        return None

    labels = _option_labels(question)
    if len(labels) < STACKED_OPTION_THRESHOLD:
        return None

    decision_hits = _count_decision_point_options(labels)
    title = str(question.get("title") or "").strip()
    packaged_title = bool(_PACKAGED_TITLE_RE.search(title))
    summary_stack = (
        summary_expected >= 3
        and question_count == 1
        and len(labels) >= max(STACKED_OPTION_THRESHOLD, int(summary_expected * 0.5))
    )

    if decision_hits >= _DECISION_POINT_MIN_MATCHES or packaged_title or summary_stack:
        qid = _question_id(question, idx)
        return (
            f"questions[{idx}]（id={qid}）疑似把 {len(labels)} 个决策点合并成一道题"
            f"（{len(labels)} 个 options 各描述不同维度/编号）。"
            "请按「一个决策点 = 一道独立题」拆分：每题 title 写决策点，"
            "options 写该点的互斥选项（可标 ✅ 推荐）。"
        )
    return None


def validate_no_stacked_decisions(
    questions: list[dict[str, Any]],
    *,
    summary_expected: int = 0,
) -> None:
    """interactive：拒绝堆叠题。"""
    count = len(questions)
    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        msg = detect_stacked_decision_question(
            q,
            idx=idx,
            question_count=count,
            summary_expected=summary_expected,
        )
        if msg:
            raise ValueError(msg)


def apply_interactive_question_repairs(
    questions: list[dict[str, Any]],
    *,
    summary: str = "",
) -> list[dict[str, Any]]:
    """interactive 问卷：逐题提取嵌入 options，并校验堆叠题。"""
    expected = 0
    if summary.strip():
        from synapse.rd_meeting.hitl_form import _infer_expected_question_count

        expected = _infer_expected_question_count(summary)

    repaired: list[dict[str, Any]] = []
    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            repaired.append(q)
            continue
        item = repair_embedded_options(q, idx=idx)
        repaired.append(item)

    validate_no_stacked_decisions(repaired, summary_expected=expected)
    return repaired
