"""会议室参会智能体列表（Host + Worker），供详情 API 与前端右侧栏展示。"""

from __future__ import annotations

from typing import Any

from synapse.rd_sop.manifest import DEFAULT_HOST_PROFILE_ID


def resolve_profile_display_name(profile_id: str) -> str:
    """解析智能体展示名（与 orchestrator._resolve_profile 同源，避免 UI 显示 profile id）。"""
    pid = (profile_id or "").strip() or DEFAULT_HOST_PROFILE_ID
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
    if pid == DEFAULT_HOST_PROFILE_ID:
        return "小鲸"
    return pid


def _profile_display_name(profile_id: str) -> str:
    return resolve_profile_display_name(profile_id)


def build_meeting_participants(binding: dict[str, Any]) -> list[dict[str, str]]:
    """从节点 binding 解析参会阵容（主控 + 协作智能体，去重）。"""
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
