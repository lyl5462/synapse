"""前序 SOP 环节产出：解析历史节点开关、归档产物与用法规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.paths import archive_node_dir
from synapse.rd_sop.manifest import (
    node_output_artifacts,
    prior_output_use_mode_for,
)
from synapse.rd_sop.nodes import ALL_NODES, node_display_name

PriorOutputUseMode = Literal["skill_required", "flow_required", "llm_judge"]

_USE_MODE_LABEL: dict[str, str] = {
    "skill_required": "技能强制要求",
    "flow_required": "流程强制转换",
    "llm_judge": "大模型自主判断",
}


@dataclass(frozen=True)
class PriorArtifactRow:
    source_node_id: str
    source_node_name: str
    stage_name: str
    artifact: str
    archive_path: str
    node_enabled: bool
    node_skipped: bool
    file_exists: bool
    use_mode: str | None
    use_note: str


def prior_node_ids(current_node_id: str) -> list[str]:
    """返回当前节点之前（不含自身）的 SOP 节点 id，顺序与 ALL_NODES 一致。"""
    ids = [str(n["id"]) for n in ALL_NODES]
    try:
        idx = ids.index((current_node_id or "").strip())
    except ValueError:
        return []
    return ids[:idx]


def _artifact_names(node_id: str) -> list[str]:
    return [
        name
        for name in node_output_artifacts(node_id)
        if (name or "").strip() and not str(name).strip().startswith("（")
    ]


def collect_prior_artifact_rows(
    scope_id: str,
    current_node_id: str,
    *,
    skipped_node_ids: set[str] | None = None,
) -> list[PriorArtifactRow]:
    """汇总当前节点可引用的前序 SOP 产出物行。"""
    sid = (scope_id or "").strip()
    nid = (current_node_id or "").strip()
    skipped = skipped_node_ids or set()
    rows: list[PriorArtifactRow] = []

    for source_id in prior_node_ids(nid):
        binding = resolve_node_binding(source_id)
        enabled = bool(binding.get("enabled", True))
        skipped_flag = source_id in skipped
        stage_name = str(binding.get("stage_name") or "").strip()
        source_name = str(binding.get("node_name") or node_display_name(source_id))

        for artifact in _artifact_names(source_id):
            archive_path = ""
            exists = False
            if sid and stage_name:
                abs_path = archive_node_dir(sid, stage_name, source_id) / artifact
                archive_path = str(abs_path.resolve())
                exists = abs_path.is_file()

            use_mode, use_note = prior_output_use_mode_for(
                nid,
                source_node_id=source_id,
                artifact=artifact,
            )
            if not enabled or skipped_flag:
                use_mode = None

            rows.append(
                PriorArtifactRow(
                    source_node_id=source_id,
                    source_node_name=source_name,
                    stage_name=stage_name,
                    artifact=artifact,
                    archive_path=archive_path,
                    node_enabled=enabled,
                    node_skipped=skipped_flag,
                    file_exists=exists,
                    use_mode=use_mode,
                    use_note=use_note,
                )
            )
    return rows


def _node_switch_label(row: PriorArtifactRow) -> str:
    if row.node_skipped:
        return "已跳过"
    if not row.node_enabled:
        return "已关闭"
    return "开启"


def _artifact_status_label(row: PriorArtifactRow) -> str:
    if row.node_skipped:
        return "环节已跳过"
    if not row.node_enabled:
        return "环节已关闭"
    if row.file_exists:
        return "已归档"
    return "尚未归档"


def format_prior_sop_outputs_section(
    scope_id: str,
    current_node_id: str,
    *,
    skipped_node_ids: set[str] | None = None,
) -> str:
    """渲染运行时头「前序 SOP 环节产出」段落；无前序或无产出配置时返回空串。"""
    rows = collect_prior_artifact_rows(
        scope_id,
        current_node_id,
        skipped_node_ids=skipped_node_ids,
    )
    display_rows = [r for r in rows if r.node_enabled and not r.node_skipped]
    if not display_rows:
        return ""

    lines: list[str] = [
        "## 前序 SOP 环节产出（本节点可用输入）",
        "",
        "- **用法说明**：",
        "  - **技能强制要求**：绑定 SKILL 规定必须先 `read_file` 该产出后再执行",
        "  - **流程强制转换**：调用 `whalecloud-dev-tool-doc-generate` 时须作为 "
        "`CONTEXT_FILES` / `CONTEXT_JSON` 载入",
        "  - **大模型自主判断**：可按任务相关性自行决定是否 `read_file` 引用",
        "",
    ]

    current_source = ""
    for row in display_rows:
        if row.source_node_id != current_source:
            current_source = row.source_node_id
            switch = _node_switch_label(row)
            lines.append(
                f"- **{row.source_node_name}**（`{row.source_node_id}` · {row.stage_name}）"
                f"：环节开关 **{switch}**"
            )

        status = _artifact_status_label(row)
        path_part = f"`{row.archive_path}`" if row.archive_path else "（路径未解析）"
        if row.use_mode:
            mode_label = _USE_MODE_LABEL.get(row.use_mode, row.use_mode)
            usage = f"**{mode_label}**"
            if row.use_note:
                usage += f"（{row.use_note}）"
        elif not row.file_exists:
            usage = "待前序环节归档后再引用"
        else:
            usage = "**大模型自主判断**"

        lines.append(
            f"  - `{row.artifact}` → {path_part} · 状态：{status} · 本节点用法：{usage}"
        )

    lines.append("")
    return "\n".join(lines)


def load_skipped_node_ids(scope_id: str) -> set[str]:
    """从 room_history 读取已跳过的 SOP 节点 id。"""
    sid = (scope_id or "").strip()
    if not sid:
        return set()
    try:
        from synapse.rd_meeting.room_runtime import extract_skipped_node_ids, read_history

        return set(extract_skipped_node_ids(read_history(sid, limit=500)))
    except Exception:
        return set()
