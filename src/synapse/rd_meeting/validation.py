"""Phase 3 / §8.2：节点产物轻量校验（仅针对归档目录约定 Markdown 文件）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from synapse.rd_sop.manifest import get_node_manifest_entry, node_output_artifacts
from synapse.rd_sop.nodes import node_display_name


@dataclass
class NodeOutputValidation:
    ok: bool
    errors: list[str]
    artifacts: list[dict[str, Any]] = field(default_factory=list)


_MIN_BODY_LEN = 80
_REQUIRED_HEADING = re.compile(r"^#\s+\S+", re.MULTILINE)


def _artifact_md_names(node_id: str) -> list[str]:
    names: list[str] = []
    for name in node_output_artifacts(node_id):
        if not name or name.startswith("（"):
            continue
        if name.lower().endswith(".md"):
            names.append(name)
    return names


def normalize_node_output_body(node_id: str, content: str) -> str:
    """为缺少一级标题的正文补上 ``# {节点名}`` 前缀（写盘兜底）。"""
    text = (content or "").strip()
    if not text or _REQUIRED_HEADING.search(text):
        return text
    title = node_display_name(node_id or "pending")
    return f"# {title}\n\n{text}"


def resolve_delivery_body_for_archive(
    scope_id: str,
    node_id: str,
    report_body: str,
) -> str:
    """解析可用于写盘的正文：优先归档约定 md，其次 pending 终稿，最后补标题兜底。"""
    from synapse.rd_meeting.hitl_submission import load_archive_delivery_body

    archive = load_archive_delivery_body(scope_id, node_id).strip()
    if archive:
        return archive
    pending = (report_body or "").strip()
    if pending:
        return pending
    return normalize_node_output_body(node_id, pending)


def _validate_markdown_body(node_id: str, content: str, *, filename: str = "") -> list[str]:
    prefix = f"{filename}: " if filename else ""
    text = (content or "").strip()
    errors: list[str] = []

    if len(text) < _MIN_BODY_LEN:
        errors.append(f"{prefix}产物过短（至少 {_MIN_BODY_LEN} 字符）")

    if not _REQUIRED_HEADING.search(text):
        errors.append(f"{prefix}须包含 Markdown 一级标题（# ）")

    entry = get_node_manifest_entry(node_id)
    if entry and entry.get("type") == "ai":
        if "交付" not in text and "完成" not in text and "结论" not in text:
            errors.append(f"{prefix}AI 节点产物建议包含「结论/完成/交付」等验收表述")

    return errors


def validate_node_output(node_id: str, content: str) -> NodeOutputValidation:
    """（内部）校验 Markdown 正文格式；对外请使用 ``validate_node_archive_artifacts``。"""
    errors = _validate_markdown_body(node_id, content)
    return NodeOutputValidation(ok=len(errors) == 0, errors=errors)


def validate_node_archive_artifacts(
    scope_id: str,
    stage_name: str,
    node_id: str,
) -> NodeOutputValidation:
    """校验归档目录下 NODE_OUTPUTS 约定的 Markdown 产出物（仅存在性）。

    会议室节点验收以约定文件是否落盘为准；正文格式/关键词由人工或后续流程处理。
    内容级校验保留在 ``validate_node_output`` / ``_validate_markdown_body``（可选、非门禁）。
    """
    from synapse.rd_meeting.paths import archive_node_dir, archive_stage_segment

    names = _artifact_md_names(node_id)
    if not names:
        return NodeOutputValidation(ok=True, errors=[])

    stg = archive_stage_segment(stage_name)
    dest = archive_node_dir(scope_id, stage_name, node_id)
    if not dest.is_dir():
        return NodeOutputValidation(
            ok=False,
            errors=[f"归档目录不存在：archive/{stg}/{node_id}/"],
        )

    from synapse.rd_meeting.paths import scope_dir

    scope_root = scope_dir(scope_id)
    errors: list[str] = []
    artifacts: list[dict[str, Any]] = []
    for name in names:
        path = dest / name
        rel = f"archive/{stg}/{node_id}/{name}"
        if not path.is_file():
            errors.append(f"缺少约定产出物：{name}（{rel}）")
            continue
        try:
            relative_path = path.resolve().relative_to(scope_root.resolve()).as_posix()
        except ValueError:
            relative_path = rel
        artifacts.append({"name": name, "relative_path": relative_path})

    return NodeOutputValidation(ok=len(errors) == 0, errors=errors, artifacts=artifacts)


def validate_node_archive_files(
    scope_id: str,
    stage_name: str,
    node_id: str,
) -> NodeOutputValidation:
    """仅校验约定 Markdown 文件是否存在于归档目录（与 ``validate_node_archive_artifacts`` 同逻辑）。"""
    return validate_node_archive_artifacts(scope_id, stage_name, node_id)
