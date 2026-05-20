"""Phase 4：meeting_room_config v2 + binding 双端点 + service 暴露字段。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.config_store import (
    CONFIG_VERSION,
    DEFAULT_LLM_ENDPOINT_KEY,
    DEFAULT_MEETING_SKILL_ID,
    default_meeting_room_config,
    load_meeting_room_config,
    save_meeting_room_config,
)
from synapse.rd_meeting.service import MeetingRoomService


@pytest.fixture
def isolated_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    cfg_dir = tmp_path / "rd_meeting"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "synapse.rd_meeting.config_store.rd_meeting_config_dir",
        lambda: cfg_dir,
    )
    return cfg_dir


def test_default_config_contains_v2_fields():
    cfg = default_meeting_room_config()
    assert cfg["version"] == CONFIG_VERSION
    assert cfg["host_llm_endpoint_key"] == DEFAULT_LLM_ENDPOINT_KEY
    assert cfg["worker_llm_endpoint_key"] == DEFAULT_LLM_ENDPOINT_KEY
    assert cfg["meeting_skill_id"] == DEFAULT_MEETING_SKILL_ID
    assert cfg["node_overrides"] == {}


def test_load_v1_config_upgrades_to_v2(isolated_config_dir: Path):
    """旧版（v1）只有 version / node_overrides，缺失字段应以默认补全。"""
    cfg_path = isolated_config_dir / "meeting_room_config.json"
    cfg_path.write_text(
        json.dumps({"version": "1", "node_overrides": {"boundary": {"prompt_supplement": "x"}}}),
        encoding="utf-8",
    )
    cfg = load_meeting_room_config()
    assert cfg["host_llm_endpoint_key"] == DEFAULT_LLM_ENDPOINT_KEY
    assert cfg["worker_llm_endpoint_key"] == DEFAULT_LLM_ENDPOINT_KEY
    assert cfg["meeting_skill_id"] == DEFAULT_MEETING_SKILL_ID
    assert cfg["node_overrides"] == {"boundary": {"prompt_supplement": "x"}}


def test_save_meeting_room_config_partial_write(isolated_config_dir: Path):
    """部分写：未提供的字段应保留旧值，且空字符串不会覆盖默认。"""
    save_meeting_room_config(
        {
            "host_llm_endpoint_key": "reasoning-heavy",
            "worker_llm_endpoint_key": "worker-pool",
        }
    )
    cfg = load_meeting_room_config()
    assert cfg["host_llm_endpoint_key"] == "reasoning-heavy"
    assert cfg["worker_llm_endpoint_key"] == "worker-pool"

    save_meeting_room_config(
        {
            "node_overrides": {
                "boundary": {"prompt_supplement": "x", "ignored_field": 1},
            }
        }
    )
    cfg = load_meeting_room_config()
    assert cfg["host_llm_endpoint_key"] == "reasoning-heavy", "未传字段应保留旧值"
    assert cfg["node_overrides"]["boundary"] == {"prompt_supplement": "x"}, "白名单外字段应被剔除"

    save_meeting_room_config({"host_llm_endpoint_key": "   "})
    cfg = load_meeting_room_config()
    assert cfg["host_llm_endpoint_key"] == "reasoning-heavy", "空白值不应覆盖"


def test_resolve_binding_includes_room_level_endpoints(isolated_config_dir: Path):
    save_meeting_room_config(
        {
            "host_llm_endpoint_key": "host-strong",
            "worker_llm_endpoint_key": "worker-cheap",
        }
    )
    binding = resolve_node_binding("boundary")
    assert binding["host_llm_endpoint_key"] == "host-strong"
    assert binding["worker_llm_endpoint_key"] == "worker-cheap"
    assert binding["llm_endpoint_key"] == "worker-cheap"
    assert binding["meeting_skill_id"] == DEFAULT_MEETING_SKILL_ID


def test_node_override_only_changes_worker_endpoint(isolated_config_dir: Path):
    save_meeting_room_config(
        {
            "host_llm_endpoint_key": "host-strong",
            "worker_llm_endpoint_key": "worker-cheap",
            "node_overrides": {
                "entropy_gen": {"llm_endpoint_key": "long-context"},
            },
        }
    )
    other = resolve_node_binding("boundary")
    assert other["llm_endpoint_key"] == "worker-cheap"
    assert other["host_llm_endpoint_key"] == "host-strong"

    overridden = resolve_node_binding("entropy_gen")
    assert overridden["llm_endpoint_key"] == "long-context", "节点级覆盖应作用于 worker 端点"
    assert overridden["host_llm_endpoint_key"] == "host-strong", "Host 端点不受节点覆盖影响"
    assert overridden["worker_llm_endpoint_key"] == "long-context"


def test_service_exposes_new_config_fields(isolated_config_dir: Path):
    save_meeting_room_config(
        {
            "host_llm_endpoint_key": "host-strong",
            "worker_llm_endpoint_key": "worker-cheap",
        }
    )
    svc = MeetingRoomService()
    cfg = svc.get_meeting_room_config()
    assert cfg["host_llm_endpoint_key"] == "host-strong"
    assert cfg["worker_llm_endpoint_key"] == "worker-cheap"
    assert cfg["meeting_skill_id"] == DEFAULT_MEETING_SKILL_ID
    assert "meeting_skill" in cfg
    assert isinstance(cfg["meeting_skill"], dict)
    assert "exists" in cfg["meeting_skill"]


def test_service_put_meeting_room_config_validates_types(isolated_config_dir: Path):
    svc = MeetingRoomService()
    with pytest.raises(ValueError):
        svc.put_meeting_room_config({"host_llm_endpoint_key": 123})
    with pytest.raises(ValueError):
        svc.put_meeting_room_config({"node_overrides": "not-an-object"})

    saved = svc.put_meeting_room_config(
        {
            "host_llm_endpoint_key": "host-strong",
            "node_overrides": {"boundary": {"prompt_supplement": "hello"}},
        }
    )
    assert saved["host_llm_endpoint_key"] == "host-strong"
    assert saved["node_overrides"]["boundary"]["prompt_supplement"] == "hello"
