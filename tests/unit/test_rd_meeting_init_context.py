"""会议室节点初始化上下文日志（JSON）。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.bootstrap import build_node_init_message
from synapse.rd_meeting.flow_log import is_flow_log_json
from synapse.rd_meeting.init_context import (
    build_node_init_log_data,
    collect_meeting_init_sections,
    format_node_init_log,
)


def test_format_node_init_log_is_json(monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_status": "pending"},
            {"synapse_url": ""},
        ),
    )
    text = format_node_init_log("demand", "21881451", node_id="req_clarify")
    assert is_flow_log_json(text)
    assert "\n" not in text
    data = json.loads(text)
    assert "order" in data
    assert "product" in data
    assert "system" in data
    assert "history_demands" not in data


def test_build_node_init_log_data_structure(monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {"locator_status": "ok", "repos": [], "docs": []},
            {"synapse_url": "http://h:10001"},
        ),
    )
    sec = build_node_init_log_data("demand", "x", node_id="req_clarify")
    assert "id" in sec["order"]
    assert "repos" in sec["product"]
    assert "history_demands" not in sec
    assert sec["system"]["synapse_url"] == "http://h:10001"
    assert collect_meeting_init_sections("demand", "x")["order"]["scope_id"] == "x"


def test_open_meeting_step1_userwork_and_init_log(monkeypatch, tmp_path):
    from synapse.rd_meeting.service import MeetingRoomService

    scope_id = "init-ctx-demand"
    uw_path = tmp_path / "userwork.json"
    uw_path.write_text(
        json.dumps(
            {
                "list": [
                    {
                        "demand_no": scope_id,
                        "demand_title": "标题A",
                        "demand_desc": "描述A",
                        "demand_impact": "",
                        "product_version_code": "PROD-X",
                        "product_version_id": 1,
                        "sop_node": "等待调度",
                        "local_process_state": "待处理",
                        "owned_work_items": [],
                    }
                ],
                "updated_at": "2026-01-01",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    work = tmp_path / "work" / scope_id
    work.mkdir(parents=True)

    for mod in (
        "synapse.api.routes.dev_iwhalecloud",
        "synapse.rd_meeting.userwork_sync",
    ):
        monkeypatch.setattr(f"{mod}._owner_order_file_name", lambda: uw_path)
        monkeypatch.setattr(f"{mod}._owner_order_file_lock_path", lambda: tmp_path / "userwork.lock")
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    hist = work / "room_history.jsonl"
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda sid: hist,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.init_context.resolve_product_for_meeting",
        lambda *_a, **_k: (
            {
                "locator_code": "ok",
                "locator_status": "产品查询成功",
                "product_version_code": "PROD-X",
                "prod": "p",
                "version": "PROD-X",
                "repos": [],
                "docs": [],
            },
            {"synapse_url": "http://127.0.0.1:10001"},
        ),
    )

    monkeypatch.setattr(
        "synapse.rd_meeting.product_context.ensure_prod_in_catalog",
        lambda p: ([{"prod": p, "version": "v", "repo_info": [], "doc_process": []}], ""),
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets.bootstrap_product_assets",
        lambda *_a, **_k: {
            "status": "ok",
            "repos": [],
            "docs": [],
            "code_root": str(work / "code"),
            "doc_root": str(work / "doc"),
            "work_order_dir": str(work),
        },
    )

    monkeypatch.setattr(
        "synapse.rd_meeting.orchestrator.schedule_run_node",
        lambda **_k: "room-key",
    )

    svc = MeetingRoomService()
    detail = svc.open_meeting("demand", scope_id, prod="p", sync_userwork=True)

    assert detail.get("node_run_scheduled") is True
    saved = json.loads(uw_path.read_text(encoding="utf-8"))
    demand = saved["list"][0]
    assert demand["local_process_state"] == "处理中"
    assert demand["sop_node"] == "需求澄清"
    assert demand["prod"] == "p"

    hist_lines = [json.loads(ln) for ln in hist.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [h["event"] for h in hist_lines]
    assert "room_opened" in events
    assert "node_init" in events

    opened = next(h for h in hist_lines if h["event"] == "room_opened")
    assert is_flow_log_json(opened["text"])
    assert "\n" not in opened["text"]
    opened_data = json.loads(opened["text"])
    assert opened_data["sop_node"] == "需求澄清"
    assert opened_data["local_process_state"] == "处理中"
    assert opened_data["prod"] == "p"
    assert "payload" not in opened

    init_row = next(h for h in hist_lines if h["event"] == "node_init")
    assert is_flow_log_json(init_row["text"])
    init_data = json.loads(init_row["text"])
    assert init_data["order"]["id"] == scope_id
    assert init_data["order"]["title"] == "标题A"
    assert "history_demands" not in init_data
    assert init_data["product"].get("locator_code") == "ok"
    assert init_data["product"].get("prod") == "p"
    assert "gitnexus_url" not in init_data.get("system", {})
    assert "gnx_cache_base_dir" not in init_data.get("system", {})
    assert init_data.get("system", {}).get("work_order_dir")
    assert init_data.get("system", {}).get("product_code_root")
    assert init_data.get("system", {}).get("product_doc_root")
    assert "小鲸" not in init_row["text"]
    assert "payload" not in init_row
