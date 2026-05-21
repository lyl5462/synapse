"""会议室流程日志格式。"""

import json

from synapse.rd_meeting.flow_log import apply_flow_log_format, flow_log_to_text, is_flow_log_json
from synapse.rd_meeting.room_runtime import append_history_event


def test_flow_log_compact_json_no_newlines():
    line = flow_log_to_text({"message": "小鲸 → 需求专家"})
    assert "\n" not in line
    assert is_flow_log_json(line)
    assert json.loads(line)["message"] == "小鲸 → 需求专家"


def test_apply_flow_log_format_room_opened_only_userwork_fields():
    row = apply_flow_log_format(
        {
            "event": "room_opened",
            "room_id": "r1",
            "scope_id": "21881451",
            "userwork_updates": {"sop_node": "需求澄清", "local_process_state": "处理中"},
            "sop_display": "需求澄清",
            "local_process_state": "处理中",
            "userwork_synced": True,
            "payload": {"room_id": "r1"},
        }
    )
    assert is_flow_log_json(row["text"])
    assert "\n" not in row["text"]
    data = json.loads(row["text"])
    assert data == {"sop_node": "需求澄清", "local_process_state": "处理中"}
    assert "payload" not in row
    assert "sop_display" not in row
    assert "local_process_state" not in row


def test_append_history_event_writes_formatted_line(tmp_path, monkeypatch):
    scope_id = "flow-log-scope"
    work = tmp_path / scope_id
    work.mkdir(parents=True)

    hist = work / "room_history.jsonl"
    monkeypatch.setattr(
        "synapse.rd_meeting.room_runtime.room_history_path",
        lambda sid: hist,
    )

    append_history_event(
        scope_id,
        {"event": "delegation_started", "text": "小鲸 → 专家：任务A", "agent_id": "host"},
    )
    assert hist.is_file()
    ev = json.loads(hist.read_text(encoding="utf-8").strip())
    assert is_flow_log_json(ev["text"])
    assert "\n" not in ev["text"]
    body = json.loads(ev["text"])
    assert body["message"] == "小鲸 → 专家：任务A"
