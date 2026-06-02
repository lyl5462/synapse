"""meeting_room_config.json 读写（Phase 2 / 双端点扩展）。

`meeting_room_config.json` 现在承载两类配置：

- **会议室全局**：host_llm_endpoint_key、worker_llm_endpoint_key。
  小鲸独立配端点（能力优先），所有协作智能体共享另一端点。
- **节点级覆盖**：`node_overrides[<node_id>]` 可覆盖 prompt_supplement / host /
  worker / llm_endpoint_key（节点级 llm_endpoint_key 仅覆盖 worker）。业务技能由 Profile 配置，不在此持久化。

历史字段 `meeting_skill_id` 已废弃（规范内嵌于代码），读取时静默忽略、写入时不再保存。
"""

from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from filelock import FileLock

from synapse.config import settings
from synapse.rd_sop.manifest import is_system_node

logger = logging.getLogger(__name__)

CONFIG_VERSION = "2"
DEFAULT_LLM_ENDPOINT_KEY = "default"
_BUNDLED_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "meeting_room_config.default.json"


def rd_meeting_config_dir() -> Path:
    return settings.synapse_home / "rd_meeting"


def meeting_room_config_path() -> Path:
    return rd_meeting_config_dir() / "meeting_room_config.json"


def meeting_room_config_lock_path() -> Path:
    return rd_meeting_config_dir() / "meeting_room_config.lock"


def _fallback_meeting_room_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "host_llm_endpoint_key": DEFAULT_LLM_ENDPOINT_KEY,
        "worker_llm_endpoint_key": DEFAULT_LLM_ENDPOINT_KEY,
        "node_overrides": {},
    }


@lru_cache(maxsize=1)
def _load_bundled_default_config() -> dict[str, Any]:
    """读取出厂默认配置（随包分发 meeting_room_config.default.json）。"""
    try:
        data = json.loads(_BUNDLED_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取出厂 meeting_room_config 失败: %s", exc)
        return _fallback_meeting_room_config()
    if not isinstance(data, dict):
        return _fallback_meeting_room_config()
    cleaned = copy.deepcopy(data)
    cleaned.pop("meeting_skill_id", None)
    cleaned.setdefault("version", CONFIG_VERSION)
    cleaned.setdefault("host_llm_endpoint_key", DEFAULT_LLM_ENDPOINT_KEY)
    cleaned.setdefault("worker_llm_endpoint_key", DEFAULT_LLM_ENDPOINT_KEY)
    overrides = cleaned.get("node_overrides")
    cleaned["node_overrides"] = overrides if isinstance(overrides, dict) else {}
    return cleaned


def default_meeting_room_config() -> dict[str, Any]:
    return copy.deepcopy(_load_bundled_default_config())


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
    # 老版本 meeting_skill_id 字段已废弃（规范内嵌于代码），静默忽略
    overrides = data.get("node_overrides")
    merged["node_overrides"] = (
        _strip_legacy_override_fields(overrides) if isinstance(overrides, dict) else {}
    )
    return merged


_SAVABLE_OVERRIDE_KEYS = (
    "enabled",
    "human_confirm",
    "prompt_supplement",
    "host_profile_id",
    "worker_profile_ids",
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
            entry.pop("skill_ids", None)
            if is_system_node(str(node_id)):
                entry.pop("human_confirm", None)
            cleaned[str(node_id)] = entry
    return cleaned


def _strip_legacy_override_fields(overrides: dict[str, Any]) -> dict[str, Any]:
    """读取时剔除已废弃字段，避免 API 继续暴露 skill_ids。"""
    if not overrides:
        return {}
    out: dict[str, Any] = {}
    for node_id, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        entry = {k: v for k, v in ov.items() if k != "skill_ids"}
        if is_system_node(str(node_id)):
            entry.pop("human_confirm", None)
        if entry:
            out[str(node_id)] = entry
    return out


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
        # 老版本 meeting_skill_id 已废弃；忽略 payload 中的该字段
        merged.pop("meeting_skill_id", None)
        if "node_overrides" in payload:
            merged["node_overrides"] = _normalize_overrides(payload.get("node_overrides"))

        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged
