"""Phase 3 / §8.2：节点产物轻量校验（可选，不通过则不记完成）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from synapse.rd_sop.manifest import get_node_manifest_entry, node_output_artifacts


@dataclass
class NodeOutputValidation:
    ok: bool
    errors: list[str]


_MIN_BODY_LEN = 80
_REQUIRED_HEADING = re.compile(r"^#\s+\S+", re.MULTILINE)


def validate_node_output(node_id: str, content: str) -> NodeOutputValidation:
    """校验 archive result 类 Markdown：非空、有标题、最低长度。"""
    text = (content or "").strip()
    errors: list[str] = []

    if len(text) < _MIN_BODY_LEN:
        errors.append(f"产物过短（至少 {_MIN_BODY_LEN} 字符）")

    if not _REQUIRED_HEADING.search(text):
        errors.append("产物须包含 Markdown 一级标题（# ）")

    entry = get_node_manifest_entry(node_id)
    if entry and entry.get("type") == "ai":
        if "交付" not in text and "完成" not in text and "结论" not in text:
            errors.append("AI 节点产物建议包含「结论/完成/交付」等验收表述")

    return NodeOutputValidation(ok=len(errors) == 0, errors=errors)


def validate_node_archive_files(
    scope_id: str,
    stage_id: int,
    node_id: str,
) -> NodeOutputValidation:
    """P3：校验 NODE_OUTPUTS 约定的 Markdown 文件是否已写入归档目录。"""
    from synapse.rd_meeting.paths import scope_dir

    errors: list[str] = []
    dest = scope_dir(scope_id) / "archive" / str(stage_id) / node_id
    if not dest.is_dir():
        return NodeOutputValidation(ok=False, errors=["归档目录不存在"])
    for name in node_output_artifacts(node_id):
        if not name or name.startswith("（"):
            continue
        if not name.lower().endswith(".md"):
            continue
        if not (dest / name).is_file():
            errors.append(f"缺少约定产物：{name}")
    return NodeOutputValidation(ok=len(errors) == 0, errors=errors)
