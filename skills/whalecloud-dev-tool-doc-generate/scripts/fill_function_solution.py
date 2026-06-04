# -*- coding: utf-8 -*-
"""函数级方案.md 模板填充脚本（结构化 CONTEXT_JSON → Markdown）。

doc-generate 在 OUTPUT=函数级方案.md 时**必须**调用本脚本；禁止手填模板。
脚本仅输出到 .tmp 草稿路径，交付物由 doc-generate 经 read_file + write_file 写入。
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any


def _g(ctx: dict[str, Any], key: str, default: str = "[待补充]") -> str:
    val = ctx.get(key, default)
    if val is None or val == "":
        return default
    return str(val)


def _fill_row(template: str, item: dict[str, Any] | Any) -> str:
    row = template
    if isinstance(item, dict):
        for k, v in item.items():
            row = row.replace("{{" + k + "}}", "" if v is None else str(v))
    else:
        row = row.replace("{{.}}", str(item))
    return row


def _repl_each(
    result: str,
    list_name: str,
    items: list[Any],
    *,
    empty: str = "（无）",
) -> str:
    pattern = rf"\{{\{{#each {list_name}\}}\}}(.*?)\{{\{{/each\}}\}}"

    def _handler(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not items:
            return empty
        rows = []
        for idx, item in enumerate(items, 1):
            line = inner.replace("{{@index}}", str(idx))
            rows.append(_fill_row(line, item))
        return "\n".join(rows)

    return re.sub(pattern, _handler, result, flags=re.DOTALL)


def _repl_modules(result: str, modules: list[dict[str, Any]]) -> str:
    pattern = r"\{\{#each modules\}\}(.*?)\{\{/each\}\}"

    def _handler(match: re.Match[str]) -> str:
        block = match.group(1)
        if not modules:
            return "（无）"
        fn_pattern = r"\{\{#each functions\}\}(.*?)\{\{/each\}\}"
        sections = []
        for idx, mod in enumerate(modules, 1):
            section = block.replace("{{@index}}", str(idx))
            if not isinstance(mod, dict):
                mod = {"module_name": str(mod)}
            functions = mod.get("functions") or []

            def _repl_fn(fn_match: re.Match[str]) -> str:
                inner = fn_match.group(1)
                if not functions:
                    return "（无）"
                parts = []
                for fn in functions:
                    parts.append(_fill_row(inner, fn if isinstance(fn, dict) else {"signature": str(fn)}))
                return "\n".join(parts)

            section = re.sub(fn_pattern, _repl_fn, section, flags=re.DOTALL)
            for k, v in mod.items():
                if k == "functions":
                    continue
                section = section.replace("{{" + k + "}}", "" if v is None else str(v))
            sections.append(section.rstrip())
        return "\n\n".join(sections)

    return re.sub(pattern, _handler, result, flags=re.DOTALL)


SCALAR_KEYS = (
    "TIMESTAMP",
    "REQUIREMENT_NAME",
    "STATUS",
    "PROD",
    "DEMAND_DESC",
    "scope_overview",
    "tech_stack_constraints",
    "data_flow_diagram",
    "function_stats",
    "code_confirm_rate",
)

LIST_KEYS = (
    "repos",
    "terms",
    "data_structures",
    "db_changes",
    "message_contracts",
    "enums",
    "cross_module_calls",
    "interface_summary",
    "tech_constraints",
    "risk_mitigations",
    "boundary_constraints",
    "performance_impacts",
    "functional_impacts",
    "config_changes",
    "upgrade_risks",
    "security_impacts",
    "compatibility_impacts",
    "ui_ue",
    "acceptance_mapping",
    "code_confirmations",
    "pending_items",
)

REQUIRED_SCALAR_KEYS = (
    "REQUIREMENT_NAME",
    "DEMAND_DESC",
    "scope_overview",
    "tech_stack_constraints",
    "data_flow_diagram",
    "function_stats",
    "code_confirm_rate",
    "PROD",
    "STATUS",
)

REQUIRED_LIST_KEYS = LIST_KEYS + ("modules",)

ALLOWED_TOP_LEVEL_KEYS = frozenset(REQUIRED_SCALAR_KEYS) | frozenset(REQUIRED_LIST_KEYS) | frozenset({"TIMESTAMP"})

FORBIDDEN_TOP_LEVEL_KEYS: dict[str, str] = {
    "DOCUMENT_BODY": "已废弃，须使用结构化字段",
    "requirement_name": "应使用 REQUIREMENT_NAME",
    "demand_id": "契约中无此字段，请删除",
    "status": "应使用 STATUS",
    "timestamp": "TIMESTAMP 由 doc-generate/脚本自动生成，勿写入",
    "prod": "应使用 PROD",
    "config_xml": "契约中无此字段，配置内容写入 config_changes[] 或标量/模块字段",
    "verification": "契约中无此字段",
}

LIST_ROW_KEYS: dict[str, tuple[str, ...]] = {
    "repos": ("branch_id", "repo_url", "change_desc"),
    "terms": ("term", "meaning"),
    "data_structures": ("name", "change_type", "module", "description"),
    "db_changes": ("table_name", "change_type", "field_changes", "description"),
    "message_contracts": (
        "interface_name",
        "caller",
        "callee",
        "request_fields",
        "response_fields",
    ),
    "enums": ("name", "change_type", "values", "description"),
    "cross_module_calls": ("caller_module", "callee_module", "function_name", "call_mode"),
    "interface_summary": (
        "interface_name",
        "request_format",
        "response_format",
        "provider",
        "consumer",
    ),
    "tech_constraints": ("constraint", "implementation"),
    "risk_mitigations": ("risk", "measure", "implementation"),
    "boundary_constraints": ("constraint", "implementation"),
    "performance_impacts": (
        "change_point",
        "impact_type",
        "severity",
        "unavoidable_reason",
        "mitigation",
    ),
    "functional_impacts": ("impact_type", "module", "description", "scope", "remark"),
    "config_changes": ("config_item", "change_type", "location", "scope", "description"),
    "upgrade_risks": ("risk_type", "description", "level", "mitigation", "rollback"),
    "security_impacts": ("dimension", "description", "severity", "measures", "remark"),
    "compatibility_impacts": (
        "compat_type",
        "item",
        "current_version",
        "target_version",
        "assessment",
        "description",
    ),
    "ui_ue": ("element", "change_type", "description", "design_notes", "acceptance_points"),
    "acceptance_mapping": ("criterion", "mapped_function", "verification"),
    "code_confirmations": ("function", "confirm_type", "evidence", "status"),
    "pending_items": ("item", "description", "priority"),
}

LIST_ROW_FORBIDDEN_KEYS: dict[str, frozenset[str]] = {
    "repos": frozenset({"repo_name", "repo_path", "files"}),
    "data_structures": frozenset({"file", "definition"}),
}

MODULE_FORBIDDEN_KEYS = frozenset({"module_path", "module_repo"})
FUNCTION_FORBIDDEN_KEYS = frozenset(
    {"func_name", "func_signature", "func_type", "func_location", "changes", "pseudo_code"}
)
FUNCTION_REQUIRED_KEYS = ("signature",)

# 与 templates/函数级方案.md 固定章节一致（填充后必须全部存在）
REQUIRED_HEADINGS = (
    "# 函数级方案",
    "## 1. 方案内容",
    "### 1.1 需求背景",
    "### 1.2 改造范围概述",
    "### 1.3 涉及仓库",
    "### 1.4 技术栈约束",
    "### 1.5 术语约定",
    "### 1.6 数据设计",
    "### 1.7 模块改造方案",
    "### 1.8 跨模块交互设计",
    "### 1.9 约束与风险应对",
    "### 1.10 影响评估",
    "### 1.11 验收映射",
    "## 2. 附录",
    "### 2.1 代码确认记录",
    "### 2.2 待确认项清单",
    "### 2.3 元数据",
)


def _wrong_keys(item: dict[str, Any], forbidden: frozenset[str]) -> list[str]:
    return sorted(k for k in item if k in forbidden)


def _validate_list_rows(
    issues: list[str],
    list_name: str,
    items: list[Any],
) -> None:
    if not items:
        return
    expected = LIST_ROW_KEYS.get(list_name)
    if not expected:
        return
    forbidden = LIST_ROW_FORBIDDEN_KEYS.get(list_name, frozenset())
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"{list_name}[{i}] 须为对象")
            continue
        wrong = _wrong_keys(item, forbidden)
        if wrong:
            issues.append(
                f"{list_name}[{i}] 含非法键 {wrong}，应使用 {list(expected)}"
            )
        if forbidden and any(k in item for k in forbidden):
            continue
        missing = [k for k in expected if k not in item]
        if missing and list_name == "repos":
            issues.append(f"{list_name}[{i}] 缺少键 {missing}（勿用 repo_name/repo_path/files）")


def _validate_modules(issues: list[str], modules: list[Any]) -> None:
    for i, mod in enumerate(modules):
        if not isinstance(mod, dict):
            issues.append(f"modules[{i}] 须为对象")
            continue
        wrong = _wrong_keys(mod, MODULE_FORBIDDEN_KEYS)
        if wrong:
            issues.append(f"modules[{i}] 含非法键 {wrong}")
        if "module_name" not in mod:
            issues.append(f"modules[{i}] 缺少 module_name")
        functions = mod.get("functions")
        if functions is None:
            issues.append(f"modules[{i}] 缺少 functions 数组")
            continue
        if not isinstance(functions, list):
            issues.append(f"modules[{i}].functions 须为数组")
            continue
        for j, fn in enumerate(functions):
            if not isinstance(fn, dict):
                issues.append(f"modules[{i}].functions[{j}] 须为对象")
                continue
            wrong_fn = _wrong_keys(fn, FUNCTION_FORBIDDEN_KEYS)
            if wrong_fn:
                issues.append(
                    f"modules[{i}].functions[{j}] 含非法键 {wrong_fn}，"
                    "应使用 signature/inputs/outputs/class_file/responsibility/"
                    "change_type/pseudocode/call_relations"
                )
            if any(k not in fn for k in FUNCTION_REQUIRED_KEYS):
                issues.append(f"modules[{i}].functions[{j}] 缺少 signature")


def validate_context(ctx: dict[str, Any]) -> list[str]:
    """校验 CONTEXT_JSON 与函数级方案模板契约；返回问题列表（空=通过）。"""
    issues: list[str] = []
    if not isinstance(ctx, dict):
        return ["CONTEXT_JSON 根节点须为 JSON 对象"]

    for key, hint in FORBIDDEN_TOP_LEVEL_KEYS.items():
        if key in ctx:
            issues.append(f"禁止使用顶层键 '{key}'：{hint}")

    for key in ctx:
        if key in FORBIDDEN_TOP_LEVEL_KEYS:
            continue
        if key not in ALLOWED_TOP_LEVEL_KEYS:
            issues.append(
                f"未知顶层键 '{key}'，须与契约一致"
                "（见 function-solution/references/function_solution_context.skeleton.json）"
            )

    for key in REQUIRED_SCALAR_KEYS:
        if key not in ctx:
            issues.append(f"缺少顶层标量键 '{key}'")

    for key in REQUIRED_LIST_KEYS:
        if key not in ctx:
            issues.append(f"缺少顶层列表键 '{key}'")
        elif not isinstance(ctx[key], list):
            issues.append(f"顶层键 '{key}' 须为数组")

    for list_name in LIST_KEYS:
        items = ctx.get(list_name)
        if isinstance(items, list):
            _validate_list_rows(issues, list_name, items)

    modules = ctx.get("modules")
    if isinstance(modules, list):
        _validate_modules(issues, modules)

    return issues


def validate_context_or_raise(ctx: dict[str, Any]) -> None:
    issues = validate_context(ctx)
    if issues:
        raise ValueError("CONTEXT_JSON 契约校验失败:\n" + "\n".join(f"  - {x}" for x in issues))


def merge_context(
    ctx: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """合并 CONTEXT_JSON 与 Parameters 标量（后者覆盖同名字段）。"""
    merged = dict(ctx)
    if overrides:
        for k, v in overrides.items():
            if v is not None and v != "":
                merged[k] = v
    ts = timestamp or merged.get("TIMESTAMP")
    if not ts:
        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    merged["TIMESTAMP"] = ts
    return merged


def render(template: str, ctx: dict[str, Any]) -> str:
    """将模板字符串填充为 Markdown（不读写文件）。"""
    ts = ctx.get("TIMESTAMP") or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    result = template
    for key in SCALAR_KEYS:
        if key == "TIMESTAMP":
            result = result.replace("{{TIMESTAMP}}", str(ts))
        else:
            result = result.replace("{{" + key + "}}", _g(ctx, key))

    for name in LIST_KEYS:
        result = _repl_each(result, name, ctx.get(name) or [])

    result = _repl_modules(result, ctx.get("modules") or [])

    result = re.sub(r"\{\{[^}]+\}\}", "[待补充]", result)
    result = re.sub(r"\{\{/if\}\}", "", result)
    result = re.sub(r"\{\{/each\}\}", "", result)
    return result


def validate_filled(markdown: str) -> list[str]:
    """返回模板一致性/占位符残留问题列表；空列表表示通过。"""
    issues: list[str] = []
    if "{{" in markdown:
        issues.append("正文仍含未解析占位符 {{...}}")
    if "{{#each" in markdown or "{{/each" in markdown:
        issues.append("正文仍含未展开的 {{#each}} 块")
    if "DOCUMENT_BODY" in markdown:
        issues.append("正文含已废弃的 DOCUMENT_BODY")
    for heading in REQUIRED_HEADINGS:
        if heading not in markdown:
            issues.append(f"缺少模板固定标题: {heading}")
    return issues


def _load_context(ctx_source: str | Path) -> dict[str, Any]:
    """从 .json 文件路径或内联 JSON 字符串加载上下文。"""
    src = str(ctx_source).strip()
    path = Path(src)
    if path.is_file():
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    return json.loads(src)


def fill(
    template_path: str | Path,
    ctx_source: str | Path | dict[str, Any],
    out_path: str | Path,
    *,
    overrides: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> None:
    with open(template_path, encoding="utf-8") as f:
        tmpl = f.read()
    if isinstance(ctx_source, dict):
        ctx = ctx_source
    else:
        ctx = _load_context(ctx_source)
    ctx = merge_context(ctx, overrides, timestamp=timestamp)
    validate_context_or_raise(ctx)
    result = render(tmpl, ctx)
    issues = validate_filled(result)
    if issues:
        raise ValueError("模板填充校验失败: " + "; ".join(issues))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(result)
    print(f"[OK] Written: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--validate-only":
        try:
            ctx = _load_context(sys.argv[2])
            validate_context_or_raise(ctx)
            print("[OK] CONTEXT_JSON 契约校验通过")
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if len(sys.argv) != 4:
        print(
            "Usage:\n"
            "  python scripts/fill_function_solution.py <template.md> "
            "<context.json|inline-json> <output.md>\n"
            "  python scripts/fill_function_solution.py --validate-only <context.json|inline-json>"
        )
        sys.exit(1)
    try:
        fill(sys.argv[1], sys.argv[2], sys.argv[3])
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
