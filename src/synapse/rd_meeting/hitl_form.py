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
    del reason  # 异常说明写入 gate reason，不用于生成题目
    if dynamic_schema:
        return dynamic_schema
    preset = binding.get("hitl_form_schema")
    if isinstance(preset, dict) and preset.get("questions"):
        return normalize_hitl_schema(preset)
    node_id = str(binding.get("node_id") or "")
    kind = (intervention_kind or "interactive").strip().lower()
    if kind in ("interactive", "exception"):
        return None
    if kind == "result_confirm" and node_id and binding.get("human_confirm"):
        return default_hitl_form_schema(node_id)
    if node_id and binding.get("human_confirm") and kind not in ("interactive", "exception"):
        return default_hitl_form_schema(node_id)
    return None


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


def attach_question_progress(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为题目列表写入统一的 progress.current / progress.total。"""
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
            "accent": "blue",
            "animate": True,
        },
        "questions": questions,
    }


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
    out["questions"] = attach_question_progress(list(questions))
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
