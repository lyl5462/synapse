"""节点归档产物：result.md + Manifest NODE_OUTPUTS 约定文件名（P1/P3）。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.paths import scope_dir
from synapse.rd_sop.manifest import node_output_artifacts


def write_node_deliverables(
    scope_id: str,
    stage_id: int,
    node_id: str,
    content: str,
    *,
    primary_filename: str = "result.md",
) -> list[dict[str, Any]]:
    """写入主产物并补齐 NODE_OUTPUTS 中可落地的 Markdown 文件名。"""
    from synapse.rd_meeting.orchestrator import write_archive_artifact

    body = (content or "").strip()
    artifacts: list[dict[str, Any]] = []
    written_names: set[str] = set()

    primary_path = write_archive_artifact(
        scope_id,
        stage_id,
        node_id,
        filename=primary_filename,
        content=body,
    )
    artifacts.append(
        {
            "name": primary_path.name,
            "relative_path": primary_path.relative_to(scope_dir(scope_id)).as_posix(),
        }
    )
    written_names.add(primary_filename)

    for name in node_output_artifacts(node_id):
        if not name or name.startswith("（"):
            continue
        if name in written_names:
            continue
        if not name.lower().endswith(".md"):
            continue
        path = write_archive_artifact(
            scope_id,
            stage_id,
            node_id,
            filename=name,
            content=body,
        )
        artifacts.append(
            {
                "name": path.name,
                "relative_path": path.relative_to(scope_dir(scope_id)).as_posix(),
            }
        )
        written_names.add(name)

    return artifacts


def validate_archive_outputs(
    scope_id: str,
    stage_id: int,
    node_id: str,
) -> tuple[bool, list[str]]:
    """P3：校验 NODE_OUTPUTS 中 Markdown 文件是否存在于归档目录。"""
    errors: list[str] = []
    dest = scope_dir(scope_id) / "archive" / str(stage_id) / node_id
    if not dest.is_dir():
        return False, ["归档目录不存在"]

    for name in node_output_artifacts(node_id):
        if not name or name.startswith("（"):
            continue
        if not name.lower().endswith(".md"):
            continue
        if not (dest / name).is_file():
            errors.append(f"缺少约定产物：{name}")

    return len(errors) == 0, errors
