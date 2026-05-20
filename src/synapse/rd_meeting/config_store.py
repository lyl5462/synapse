"""meeting_room_config.json 读写（Phase 2 / 双端点扩展）。

`meeting_room_config.json` 现在承载两类配置：

- **会议室全局**：host_llm_endpoint_key、worker_llm_endpoint_key、meeting_skill_id。
  小鲸独立配端点（能力优先），所有协作智能体共享另一端点。
- **节点级覆盖**：`node_overrides[<node_id>]` 仍可覆盖 prompt_supplement / host /
  worker / skill_ids / llm_endpoint_key（节点级 llm_endpoint_key 仅覆盖 worker）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from filelock import FileLock

from synapse.config import settings

logger = logging.getLogger(__name__)

CONFIG_VERSION = "2"
DEFAULT_LLM_ENDPOINT_KEY = "default"
DEFAULT_MEETING_SKILL_ID = "whalecloud-dev-tool-meeting-room"


def rd_meeting_config_dir() -> Path:
    return settings.synapse_home / "rd_meeting"


def meeting_room_config_path() -> Path:
    return rd_meeting_config_dir() / "meeting_room_config.json"


def meeting_room_config_lock_path() -> Path:
    return rd_meeting_config_dir() / "meeting_room_config.lock"


def default_meeting_room_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "host_llm_endpoint_key": DEFAULT_LLM_ENDPOINT_KEY,
        "worker_llm_endpoint_key": DEFAULT_LLM_ENDPOINT_KEY,
        "meeting_skill_id": DEFAULT_MEETING_SKILL_ID,
        "node_overrides": {},
    }


def _coerce_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        v = value.strip()
        if v:
            return v
    return default


def load_meeting_room_config() -> dict[str, Any]:
    """读取配置；缺失字段以默认值兜底，老版本（v1）自动升级到 v2 结构。"""
    path = meeting_room_config_path()
    base = default_meeting_room_config()
    if not path.is_file():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 meeting_room_config 失败: %s", exc)
        return base
    if not isinstance(data, dict):
        return base

    merged = dict(base)
    merged["version"] = _coerce_str(data.get("version"), CONFIG_VERSION)
    merged["host_llm_endpoint_key"] = _coerce_str(
        data.get("host_llm_endpoint_key"), DEFAULT_LLM_ENDPOINT_KEY
    )
    merged["worker_llm_endpoint_key"] = _coerce_str(
        data.get("worker_llm_endpoint_key"), DEFAULT_LLM_ENDPOINT_KEY
    )
    merged["meeting_skill_id"] = _coerce_str(
        data.get("meeting_skill_id"), DEFAULT_MEETING_SKILL_ID
    )
    overrides = data.get("node_overrides")
    merged["node_overrides"] = overrides if isinstance(overrides, dict) else {}
    return merged


_SAVABLE_OVERRIDE_KEYS = (
    "enabled",
    "human_confirm",
    "prompt_supplement",
    "host_profile_id",
    "worker_profile_ids",
    "skill_ids",
    "llm_endpoint_key",
    "node_intent",
    "hitl_form_schema",
)


def _normalize_overrides(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for node_id, ov in value.items():
        if not isinstance(ov, dict):
            continue
        entry: dict[str, Any] = {}
        for key in _SAVABLE_OVERRIDE_KEYS:
            if key in ov:
                entry[key] = ov[key]
        if entry:
            cleaned[str(node_id)] = entry
    return cleaned


def save_meeting_room_config(payload: dict[str, Any]) -> dict[str, Any]:
    """部分写入：仅承载白名单字段；未提供的字段保留磁盘上的旧值。"""
    rd_meeting_config_dir().mkdir(parents=True, exist_ok=True)
    path = meeting_room_config_path()
    lock = FileLock(str(meeting_room_config_lock_path()), timeout=30)

    with lock:
        existing = load_meeting_room_config()
        merged = dict(existing)
        merged["version"] = _coerce_str(payload.get("version"), existing.get("version") or CONFIG_VERSION)
        if "host_llm_endpoint_key" in payload:
            merged["host_llm_endpoint_key"] = _coerce_str(
                payload.get("host_llm_endpoint_key"),
                str(existing.get("host_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY),
            )
        if "worker_llm_endpoint_key" in payload:
            merged["worker_llm_endpoint_key"] = _coerce_str(
                payload.get("worker_llm_endpoint_key"),
                str(existing.get("worker_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY),
            )
        if "meeting_skill_id" in payload:
            merged["meeting_skill_id"] = _coerce_str(
                payload.get("meeting_skill_id"),
                str(existing.get("meeting_skill_id") or DEFAULT_MEETING_SKILL_ID),
            )
        if "node_overrides" in payload:
            merged["node_overrides"] = _normalize_overrides(payload.get("node_overrides"))

        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged
