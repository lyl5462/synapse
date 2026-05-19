"""研发 SOP 只读定义（Phase 0：节点 id / 中文名解析）。"""

from synapse.rd_sop.nodes import (
    node_display_name,
    resolve_sop_raw_to_node_id,
    stage_id_for_node_id,
    stage_name_for_id,
)

__all__ = [
    "node_display_name",
    "resolve_sop_raw_to_node_id",
    "stage_id_for_node_id",
    "stage_name_for_id",
]
