"""会议室节点子阶段（P2）：辅助 UI 与 prompt，非硬编排 FSM。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_meeting.room_runtime import load_room_state, save_room_state

NodePhase = Literal[
    "idle",
    "running",
    "clarify_gate",
    "result_gate",
    "exception_gate",
    "document",
    "completed",
]

_VALID: set[str] = {
    "idle",
    "running",
    "clarify_gate",
    "result_gate",
    "exception_gate",
    "document",
    "completed",
}


def get_phase(scope_id: str) -> str:
    rs = load_room_state(scope_id) or {}
    phase = str(rs.get("phase") or "idle")
    return phase if phase in _VALID else "idle"


def set_phase(scope_id: str, phase: str, *, extra: dict[str, Any] | None = None) -> None:
    if phase not in _VALID:
        phase = "running"
    rs = dict(load_room_state(scope_id) or {})
    rs["phase"] = phase
    if extra:
        rs.update(extra)
    save_room_state(scope_id, rs)


def phase_prompt_hint(scope_id: str, *, human_confirm: bool) -> str:
    if not human_confirm:
        return ""
    phase = get_phase(scope_id)
    hints = {
        "clarify_gate": "当前处于**会中人工确认**阶段：用户提交问卷后将继续本节点。",
        "result_gate": "当前处于**结果确认**阶段：用户 approve 后才可归档推进。",
        "exception_gate": "当前处于**异常人工介入**阶段：请根据用户反馈调整策略。",
        "document": "当前处于**文档生成**阶段：请产出 NODE_OUTPUTS 约定文件名。",
        "running": "当前节点执行中：可按需输出会中问卷（interactive）或继续委派。",
    }
    line = hints.get(phase, "")
    if not line:
        return ""
    return f"\n## 节点子阶段（phase={phase}）\n{line}\n"
