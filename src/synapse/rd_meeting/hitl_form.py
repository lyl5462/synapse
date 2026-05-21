"""人工确认（HITL）统一问答表单 schema：配置 → 绑定 → 小鲸 prompt。"""

from __future__ import annotations

from typing import Any

from synapse.rd_sop.manifest import get_node_manifest_entry
from synapse.rd_sop.nodes import node_display_name

# 字段 type: text | textarea | select | radio | checkbox
_DEFAULT_APPROVAL_FIELDS: list[dict[str, Any]] = [
    {
        "id": "decision",
        "label": "确认结论",
        "type": "radio",
        "required": True,
        "options": [
            {"label": "通过，进入下一节点", "value": "approve"},
            {"label": "不通过，需返工", "value": "reject"},
        ],
    },
    {
        "id": "comment",
        "label": "补充说明",
        "type": "textarea",
        "required": False,
        "placeholder": "可选：记录评审意见或返工原因",
    },
]


def default_hitl_form_schema(node_id: str) -> dict[str, Any]:
    """按节点生成默认人机确认表单（可写入配置或由 binding 返回）。"""
    entry = get_node_manifest_entry(node_id)
    name = str(entry.get("name") if entry else node_display_name(node_id))
    intent = str(entry.get("intent") if entry else "")
    return {
        "title": f"{name} — 人工确认",
        "description": (
            (intent or f"请审阅节点「{name}」的待确认总结，确认无误后提交表单。")
            + " 确认通过后系统将写入归档产物并推进至下一节点；选择返工将根据您的说明重新执行本节点。"
        ),
        "fields": list(_DEFAULT_APPROVAL_FIELDS),
    }


def resolve_hitl_form_schema(
    node_id: str,
    *,
    node_override: dict[str, Any],
) -> dict[str, Any] | None:
    """人工确认关闭时返回 None；开启时返回有效 schema。"""
    custom = node_override.get("hitl_form_schema")
    if isinstance(custom, dict) and custom.get("fields"):
        return custom
    return default_hitl_form_schema(node_id)


def format_hitl_schema_for_prompt(schema: dict[str, Any] | None) -> str:
    """将表单 schema 压缩为可注入小鲸 system/user 的说明。"""
    if not schema:
        return ""
    lines = [
        f"标题：{schema.get('title') or '人工确认'}",
    ]
    desc = str(schema.get("description") or "").strip()
    if desc:
        lines.append(f"说明：{desc}")
    lines.append("需收集的字段：")
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return "\n".join(lines)
    for f in fields:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "")
        label = str(f.get("label") or fid)
        ftype = str(f.get("type") or "text")
        req = "必填" if f.get("required") else "选填"
        opts = f.get("options")
        opt_txt = ""
        if isinstance(opts, list) and opts:
            parts = [
                str(o.get("label") or o.get("value") or "")
                for o in opts
                if isinstance(o, dict)
            ]
            opt_txt = f"（选项：{', '.join(p for p in parts if p)}）"
        lines.append(f"- {label} [{ftype}, {req}]{opt_txt}")
    return "\n".join(lines)
