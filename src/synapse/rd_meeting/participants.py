"""会议室参会智能体列表（Host + Worker），供详情 API 与前端右侧栏展示。"""

from __future__ import annotations

import re
from typing import Any

from synapse.rd_sop.manifest import DEFAULT_HOST_PROFILE_ID

# 并行委派分身：ephemeral_{base_profile_id}_{timestamp_ms}_{clone_index}
_EPHEMERAL_PROFILE_RE = re.compile(r"^ephemeral_(.+)_(\d{10,})_(\d+)$")


def parse_ephemeral_profile_id(profile_id: str) -> tuple[str, int] | None:
    """解析 ephemeral 分身 profile_id，返回 (base_profile_id, clone_index)。"""
    pid = (profile_id or "").strip()
    m = _EPHEMERAL_PROFILE_RE.match(pid)
    if not m:
        return None
    return m.group(1), int(m.group(3))


def _lookup_profile_name(profile_id: str) -> str | None:
    """从 ProfileStore / SYSTEM_PRESETS 解析展示名；找不到返回 None。"""
    pid = (profile_id or "").strip()
    if not pid:
        return None
    try:
        from synapse.agents.presets import SYSTEM_PRESETS
        from synapse.agents.profile import get_profile_store

        store = get_profile_store()
        loaded = store.get(pid)
        if loaded is not None:
            name = getattr(loaded, "name", None) or loaded.get_display_name()
            if name and str(name).strip():
                return str(name).strip()
        for sp in SYSTEM_PRESETS:
            if sp.id == pid:
                return str(getattr(sp, "name", None) or sp.get_display_name() or pid)
    except Exception:
        pass
    return None


def resolve_profile_display_name(profile_id: str) -> str:
    """解析智能体展示名（与 orchestrator._resolve_profile 同源，避免 UI 显示 profile id）。"""
    pid = (profile_id or "").strip() or DEFAULT_HOST_PROFILE_ID
    direct = _lookup_profile_name(pid)
    if direct:
        return direct

    parsed = parse_ephemeral_profile_id(pid)
    if parsed is not None:
        base_id, clone_idx = parsed
        base_name = _lookup_profile_name(base_id)
        label = base_name or base_id
        return f"{label} (分身{clone_idx})"

    if pid == DEFAULT_HOST_PROFILE_ID:
        return "小鲸"
    return pid


def _profile_display_name(profile_id: str) -> str:
    return resolve_profile_display_name(profile_id)


def build_system_participants() -> list[dict[str, str]]:
    """系统节点参会方（无 LLM Agent）。"""
    return [
        {
            "profile_id": "system",
            "role": "system",
            "display_name": "系统",
        }
    ]


def build_meeting_participants(binding: dict[str, Any]) -> list[dict[str, str]]:
    """从节点 binding 解析参会阵容（主控 + 协作智能体，去重）。"""
    if str(binding.get("type") or "").strip() == "system":
        return build_system_participants()
    host_id = str(binding.get("host_profile_id") or DEFAULT_HOST_PROFILE_ID).strip()
    workers = [
        str(w).strip()
        for w in (binding.get("worker_profile_ids") or [])
        if str(w).strip() and str(w).strip() != host_id
    ]
    seen: set[str] = set()
    rows: list[dict[str, str]] = []

    def _add(profile_id: str, role: str) -> None:
        if not profile_id or profile_id in seen:
            return
        seen.add(profile_id)
        rows.append(
            {
                "profile_id": profile_id,
                "role": role,
                "display_name": _profile_display_name(profile_id),
            }
        )

    _add(host_id, "host")
    for wid in workers:
        _add(wid, "worker")
    return rows
