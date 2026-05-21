"""节点会议目标（NODE_INTENT）。"""

from __future__ import annotations

from typing import Any

from synapse.rd_sop.manifest import NODE_INTENTS, get_node_manifest_entry


def default_node_intent(node_id: str) -> str:
    """节点会议目标默认值（SOP Manifest）。"""
    entry = get_node_manifest_entry(node_id)
    if entry:
        return str(entry.get("intent") or "").strip()
    return str(NODE_INTENTS.get(node_id, "") or "").strip()


def resolve_node_intent(
    node_id: str,
    *,
    node_override: dict[str, Any],
) -> tuple[str, str]:
    """解析节点会议目标（不可为空；配置留空则用默认）。

    Returns:
        (node_intent, default_node_intent)
    """
    def_node = default_node_intent(node_id)
    custom = str(node_override.get("node_intent") or "").strip()
    intent = custom or def_node
    return intent, def_node
