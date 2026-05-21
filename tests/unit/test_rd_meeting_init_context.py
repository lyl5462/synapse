"""会议室节点初始化上下文日志。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.bootstrap import build_node_init_message
from synapse.rd_meeting.init_context import format_node_init_log
from synapse.rd_meeting.room_runtime import append_history_event


def test_format_node_init_log_sections():
    text = format_node_init_log("demand", "21881451", node_id="req_clarify")
    assert "【工单信息】" in text
    assert "【产品信息】" in text
    assert "【系统信息】" in text


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

    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync._owner_order_file_name",
        lambda: uw_path,
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.userwork_sync._owner_order_file_lock_path",
        lambda: tmp_path / "userwork.lock",
    )

    def _work_root():
        return tmp_path / "work"

    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", _work_root)
    hist = work / "room_history.jsonl"
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda sid: hist,
    )

    svc = MeetingRoomService()
    detail = svc.open_meeting("demand", scope_id, sync_userwork=True, auto_run_first_node=False)

    assert detail.get("auto_run_started") is not True
    saved = json.loads(uw_path.read_text(encoding="utf-8"))
    demand = saved["list"][0]
    assert demand["local_process_state"] == "处理中"
    assert demand["sop_node"] == "需求澄清"

    hist_lines = [json.loads(ln) for ln in hist.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [h["event"] for h in hist_lines]
    assert "room_opened" in events
    assert "node_init" in events
    init_row = next(h for h in hist_lines if h["event"] == "node_init")
    assert "【工单信息】" in init_row["text"]
    assert "【产品信息】" in init_row["text"]
    assert "【系统信息】" in init_row["text"]
    assert "小鲸" not in init_row["text"]
    assert "21881451" in init_row["text"] or scope_id in init_row["text"]
