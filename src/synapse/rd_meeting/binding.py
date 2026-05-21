"""解析节点 binding：Manifest default_binding + meeting_room_config 覆盖。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.config_store import (
    DEFAULT_LLM_ENDPOINT_KEY,
    DEFAULT_MEETING_SKILL_ID,
    load_meeting_room_config,
)
from synapse.rd_meeting.hitl_form import resolve_hitl_form_schema
from synapse.rd_meeting.intents import resolve_node_intent
from synapse.rd_sop.manifest import (
    DEFAULT_HOST_PROFILE_ID,
    default_human_confirm,
    get_node_manifest_entry,
    node_output_artifacts,
)
from synapse.rd_sop.nodes import node_display_name


def _coerce_enabled(value: Any) -> bool:
    """未配置或显式 true → 启用；仅 false / 0 / 'false' 视为关闭。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "disabled")
    return bool(value)


def _coerce_human_confirm(value: Any, *, node_id: str) -> bool:
    if value is None:
        return default_human_confirm(node_id)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
    return bool(value)


def _merge_binding(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    if "enabled" in override:
        out["enabled"] = _coerce_enabled(override.get("enabled"))
    if "human_confirm" in override:
        out["human_confirm"] = override.get("human_confirm")
    if override.get("host_profile_id"):
        out["host_profile_id"] = str(override["host_profile_id"]).strip()
    if override.get("worker_profile_ids"):
        w = override["worker_profile_ids"]
        if isinstance(w, list):
            out["worker_profile_ids"] = [str(x).strip() for x in w if str(x).strip()]
    if override.get("skill_ids"):
        s = override["skill_ids"]
        if isinstance(s, list):
            out["skill_ids"] = [str(x).strip() for x in s if str(x).strip()]
    if override.get("llm_endpoint_key"):
        out["llm_endpoint_key"] = str(override["llm_endpoint_key"]).strip()
    if override.get("prompt_supplement") is not None:
        out["prompt_supplement"] = str(override.get("prompt_supplement") or "")
    if override.get("node_intent") is not None:
        out["node_intent"] = str(override.get("node_intent") or "")
    if override.get("hitl_form_schema") is not None:
        out["hitl_form_schema"] = override.get("hitl_form_schema")
    return out


def resolve_node_binding(
    node_id: str,
    *,
    scope_type: str = "demand",
    scope_id: str = "",
    ticket_title: str = "",
) -> dict[str, Any]:
    del scope_type, scope_id, ticket_title  # 会议目标不再依赖工单上下文生成
    cfg = load_meeting_room_config()
    host_llm_endpoint = str(
        cfg.get("host_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY
    ).strip() or DEFAULT_LLM_ENDPOINT_KEY
    worker_llm_endpoint = str(
        cfg.get("worker_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY
    ).strip() or DEFAULT_LLM_ENDPOINT_KEY
    meeting_skill_id = str(
        cfg.get("meeting_skill_id") or DEFAULT_MEETING_SKILL_ID
    ).strip() or DEFAULT_MEETING_SKILL_ID

    overrides = cfg.get("node_overrides")
    override = overrides.get(node_id) if isinstance(overrides, dict) else {}
    if not isinstance(override, dict):
        override = {}

    enabled = _coerce_enabled(override.get("enabled") if "enabled" in override else None)

    entry = get_node_manifest_entry(node_id)
    if entry is None:
        node_intent, default_node_intent = resolve_node_intent(node_id, node_override=override)
        human_confirm = _coerce_human_confirm(
            override.get("human_confirm") if "human_confirm" in override else None,
            node_id=node_id,
        )
        hitl_schema = resolve_hitl_form_schema(node_id, node_override=override) if human_confirm else None
        return {
            "node_id": node_id,
            "node_name": node_display_name(node_id),
            "stage_id": 0,
            "stage_name": "",
            "type": "ai",
            "enabled": enabled,
            "human_confirm": human_confirm,
            "default_human_confirm": default_human_confirm(node_id),
            "hitl_form_schema": hitl_schema,
            "node_outputs": node_output_artifacts(node_id),
            "intent": node_intent,
            "node_intent": node_intent,
            "default_node_intent": default_node_intent,
            "host_profile_id": DEFAULT_HOST_PROFILE_ID,
            "worker_profile_ids": [DEFAULT_HOST_PROFILE_ID],
            "skill_ids": [],
            "llm_endpoint_key": worker_llm_endpoint,
            "host_llm_endpoint_key": host_llm_endpoint,
            "worker_llm_endpoint_key": worker_llm_endpoint,
            "meeting_skill_id": meeting_skill_id,
            "prompt_supplement": "",
        }

    base = dict(entry.get("default_binding") or {})
    base["llm_endpoint_key"] = worker_llm_endpoint
    base["enabled"] = enabled
    merged = _merge_binding(base, override)

    node_worker_endpoint = str(
        merged.get("llm_endpoint_key") or worker_llm_endpoint
    ).strip() or worker_llm_endpoint
    merged["llm_endpoint_key"] = node_worker_endpoint

    human_confirm = _coerce_human_confirm(
        merged.get("human_confirm") if "human_confirm" in merged else None,
        node_id=node_id,
    )
    hitl_schema = resolve_hitl_form_schema(node_id, node_override=override) if human_confirm else None
    node_intent, default_node_intent = resolve_node_intent(node_id, node_override=override)

    return {
        "node_id": node_id,
        "node_name": str(entry.get("name") or node_id),
        "stage_id": int(entry.get("stage_id") or 0),
        "stage_name": str(entry.get("stage_name") or ""),
        "type": entry.get("type"),
        "enabled": _coerce_enabled(merged.get("enabled")),
        "human_confirm": human_confirm,
        "default_human_confirm": default_human_confirm(node_id),
        "hitl_form_schema": hitl_schema,
        "node_outputs": node_output_artifacts(node_id),
        "intent": node_intent,
        "node_intent": node_intent,
        "default_node_intent": default_node_intent,
        "host_llm_endpoint_key": host_llm_endpoint,
        "worker_llm_endpoint_key": node_worker_endpoint,
        "meeting_skill_id": meeting_skill_id,
        **merged,
    }


def list_resolved_bindings() -> list[dict[str, Any]]:
    from synapse.rd_sop.manifest import list_manifest_nodes

    return [resolve_node_binding(str(n["id"])) for n in list_manifest_nodes() if n]
