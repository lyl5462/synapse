"""会议室节点子阶段：读写委托给 ``meeting_pipeline.json``（与 pipeline.phase 同步）。"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.pipeline import MeetingPipeline

NodePhase = str

_VALID = {
    "idle",
    "running",
    "clarify_gate",
    "result_gate",
    "exception_gate",
    "completed",
    "waiting",
}


def get_phase(scope_id: str) -> str:
    if MeetingPipeline.exists(scope_id):
        ph = MeetingPipeline.load(scope_id).phase
        return ph if ph in _VALID else "idle"
    from synapse.rd_meeting.room_runtime import load_room_state

    rs = load_room_state(scope_id) or {}
    phase = str(rs.get("phase") or "idle")
    return phase if phase in _VALID else "idle"


def set_phase(scope_id: str, phase: str, *, extra: dict[str, Any] | None = None) -> None:
    if phase not in _VALID:
        phase = "running"
    pipe = MeetingPipeline.load(scope_id)
    if extra:
        ctx = pipe.data.get("context")
        if not isinstance(ctx, dict):
            ctx = {}
        ctx.update(extra)
        pipe.data["context"] = ctx
    pipe.set_phase(phase, sync_room_state=True)
    pipe.save()


def phase_prompt_hint(scope_id: str, *, human_confirm: bool) -> str:
    if not human_confirm:
        return ""
    phase = get_phase(scope_id)
    hints = {
        "clarify_gate": "当前处于**会中人工确认**阶段：用户提交问卷后将继续本节点。",
        "result_gate": "当前处于**结果确认**阶段：用户 approve 后才可归档推进。",
        "exception_gate": "当前处于**异常人工介入**阶段：请根据用户反馈调整策略。",
        "running": "当前节点执行中：可按需输出会中问卷（interactive）或继续委派。",
        "waiting": "当前流程待机：等待调度下一流程步骤（见 meeting_pipeline.json）。",
    }
    line = hints.get(phase, "")
    if not line:
        return ""
    return f"\n## 节点子阶段（phase={phase}）\n{line}\n"
