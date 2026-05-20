"""SOP 节点表（与 setup-center rd-sop/constants 对齐，Phase 0 后端副本）。"""

from __future__ import annotations

STAGES: list[dict] = [
    {
        "id": 0,
        "name": "待处理",
        "nodes": [
            {"id": "pending", "name": "等待调度"},
        ],
    },
    {
        "id": 1,
        "name": "需求分析",
        "nodes": [
            {"id": "req_clarify", "name": "需求澄清"},
            {"id": "boundary", "name": "边界确认"},
            {"id": "module_func", "name": "模块功能"},
            {"id": "acceptance", "name": "验收标准"},
            {"id": "req_risk", "name": "需求风险"},
        ],
    },
    {
        "id": 2,
        "name": "需求设计",
        "nodes": [
            {"id": "func_assign", "name": "功能点分派"},
            {"id": "history_solution", "name": "历史方案"},
            {"id": "module_confirm", "name": "模块确认"},
            {"id": "func_solution", "name": "函数级方案"},
            {"id": "entropy_gen", "name": "控熵生成"},
            {"id": "solution_review", "name": "方案评审"},
        ],
    },
    {
        "id": 3,
        "name": "需求研发",
        "nodes": [
            {"id": "auto_split", "name": "自动拆单"},
            {"id": "sandbox_build", "name": "沙箱构建"},
            {"id": "env_pregen", "name": "环境预生成"},
        ],
    },
    {
        "id": 4,
        "name": "开发中",
        "nodes": [
            {"id": "task_exec", "name": "任务执行"},
            {"id": "exception_check", "name": "异常检查"},
            {"id": "task_feedback", "name": "任务反馈"},
            {"id": "diff_analysis", "name": "差异分析"},
            {"id": "env_start", "name": "环境启动"},
            {"id": "unit_test", "name": "单元自测"},
        ],
    },
    {
        "id": 5,
        "name": "代码走查",
        "nodes": [
            {"id": "dev_process_review", "name": "开发流程评审"},
            {"id": "solution_consistency", "name": "方案一致性"},
            {"id": "risk_review", "name": "风险评审"},
            {"id": "entropy_review", "name": "控熵评审"},
            {"id": "leader_review", "name": "研发组长评审"},
        ],
    },
]

_ALL_NODES: list[dict] = [
    {**n, "stage_id": s["id"], "stage_name": s["name"]}
    for s in STAGES
    for n in s["nodes"]
]

ALL_NODES = _ALL_NODES


def resolve_sop_raw_to_node_id(sop_raw: str) -> str | None:
    sop = (sop_raw or "").strip()
    if not sop:
        return None
    for n in _ALL_NODES:
        if n["id"] == sop or n["name"] == sop:
            return n["id"]
    return None


def stage_id_for_node_id(node_id: str) -> int:
    for n in _ALL_NODES:
        if n["id"] == node_id:
            return int(n["stage_id"])
    return 0


def stage_name_for_id(stage_id: int) -> str:
    for s in STAGES:
        if s["id"] == stage_id:
            return str(s["name"])
    return ""


def node_display_name(node_id: str) -> str:
    for n in _ALL_NODES:
        if n["id"] == node_id:
            return str(n["name"])
    return node_id
