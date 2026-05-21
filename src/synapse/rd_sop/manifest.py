"""SOP Manifest：节点 intent / type / default_binding（Phase 2）。"""

from __future__ import annotations

from typing import Any

from synapse.rd_sop.nodes import ALL_NODES, STAGES

DEFAULT_HOST_PROFILE_ID = "default"
DEFAULT_LLM_ENDPOINT_KEY = "default"

# 与 setup-center rd-sop/constants 对齐的节点类型
# human/human_start=人工主导；ai=AI主导；ai_human=协同；system=系统独立
NODE_TYPES: dict[str, str] = {
    "pending": "system",
    "req_clarify": "human",
    "boundary": "ai",
    "module_func": "ai",
    "acceptance": "ai",
    "req_risk": "human",
    "func_assign": "ai",
    "history_solution": "ai",
    "module_confirm": "ai",
    "func_solution": "ai",
    "entropy_gen": "ai",
    "solution_review": "ai_human",
    "auto_split": "ai",
    "sandbox_build": "ai",
    "env_pregen": "ai",
    "task_exec": "human_start",
    "exception_check": "ai",
    "task_feedback": "system",
    "diff_analysis": "human",
    "env_start": "system",
    "unit_test": "ai",
    "dev_process_review": "ai",
    "solution_consistency": "ai",
    "risk_review": "ai",
    "entropy_review": "ai",
    "leader_review": "ai_human",
}

NODE_INTENTS: dict[str, str] = {
    "pending": "等待进入智能研发流水线。",
    "req_clarify": "识别需求模糊点，交互式完善需求说明。",
    "boundary": "识别跨产品边界，确保单需求单产品。",
    "module_func": "功能模块拆分，为设计做准备。",
    "acceptance": "为功能模块设定验收标准。",
    "req_risk": "高风险需求人工评估影响与工作量。",
    "func_assign": "按功能点分派给 Worker 并行处理。",
    "history_solution": "检索历史方案并与当前需求映射。",
    "module_confirm": "确认改造的代码模块范围。",
    "func_solution": "功能方案定位到函数级，控制改造范围。",
    "entropy_gen": "生成 agent.md、rule.md 等控熵文件。",
    "solution_review": "方案评审与可行性验证。",
    "auto_split": "按需求与方案自动拆分研发子单。",
    "sandbox_build": "构造研发沙箱基础环境。",
    "env_pregen": "拉取代码与控熵文件，预生成开发环境。",
    "task_exec": "人工确认后启动研发任务执行。",
    "exception_check": "检测执行异常并决定是否升级人工。",
    "task_feedback": "反馈执行进度供人工观察。",
    "diff_analysis": "研发人员完成代码差异分析。",
    "env_start": "启动环境并编译运行。",
    "unit_test": "按验收标准生成并执行单元测试。",
    "dev_process_review": "开发流程规范评审。",
    "solution_consistency": "方案与实现一致性检查。",
    "risk_review": "风险项评审。",
    "entropy_review": "控熵文件合规评审。",
    "leader_review": "研发组长综合审批。",
}


def default_binding_for_node(node_id: str) -> dict[str, Any]:
    return {
        "host_profile_id": DEFAULT_HOST_PROFILE_ID,
        "worker_profile_ids": [DEFAULT_HOST_PROFILE_ID],
        "skill_ids": [],
        "llm_endpoint_key": DEFAULT_LLM_ENDPOINT_KEY,
    }


def get_node_manifest_entry(node_id: str) -> dict[str, Any] | None:
    for n in ALL_NODES:
        if str(n["id"]) == node_id:
            nid = str(n["id"])
            return {
                "id": nid,
                "name": str(n.get("name") or nid),
                "stage_id": int(n.get("stage_id") or 0),
                "stage_name": str(n.get("stage_name") or ""),
                "type": NODE_TYPES.get(nid, "ai"),
                "intent": NODE_INTENTS.get(nid, ""),
                "default_binding": default_binding_for_node(nid),
            }
    return None


def list_manifest_nodes() -> list[dict[str, Any]]:
    return [get_node_manifest_entry(str(n["id"])) for n in ALL_NODES if get_node_manifest_entry(str(n["id"]))]


def list_manifest_stages() -> list[dict[str, Any]]:
    return [{"id": s["id"], "name": s["name"], "nodes": [str(n["id"]) for n in s["nodes"]]} for s in STAGES]


def next_node_id(current_node_id: str) -> str | None:
    ids = [str(n["id"]) for n in ALL_NODES]
    try:
        idx = ids.index(current_node_id)
    except ValueError:
        return None
    if idx + 1 >= len(ids):
        return None
    return ids[idx + 1]


def is_human_gate_node(node_id: str) -> bool:
    """节点 SOP 类型是否偏人工（仅用于默认配置/UI 提示，不驱动运行时门控）。"""
    t = NODE_TYPES.get(node_id, "")
    return "human" in t or t in ("human_start", "ai_human", "ai_exception", "human_multi")


def default_human_confirm(node_id: str) -> bool:
    """节点是否默认开启「人工确认」配置（与 NODE_TYPES 对齐，运行时可覆盖）。"""
    t = NODE_TYPES.get(node_id, "")
    if t in ("human", "human_start", "ai_human", "human_multi"):
        return True
    if t == "ai_exception":
        return True
    return False


def is_human_only_node(node_id: str) -> bool:
    """已废弃：人工型节点仍走智能体协作，人工参与度由 `human_confirm` 与运行时交互决定。"""
    return NODE_TYPES.get(node_id, "") == "human"


# 节点产出文档（只读展示；归档路径 archive/<stage_id>/<node_id>/）
NODE_OUTPUTS: dict[str, list[str]] = {
    "pending": ["（系统节点，无归档产出）"],
    "req_clarify": ["需求澄清记录.md", "01-需求澄清.md"],
    "boundary": ["边界确认说明.md"],
    "module_func": ["模块功能拆分.md", "03-模块功能.md"],
    "acceptance": ["验收标准.md"],
    "req_risk": ["需求风险评估.md"],
    "func_assign": ["功能点分派清单.md"],
    "history_solution": ["历史方案映射.md"],
    "module_confirm": ["模块范围确认.md"],
    "func_solution": ["函数级方案.md"],
    "entropy_gen": ["agent.md", "rule.md", "控熵文件包"],
    "solution_review": ["方案评审结论.md"],
    "auto_split": ["研发子单拆分清单.md"],
    "sandbox_build": ["沙箱构建说明.md"],
    "env_pregen": ["环境预生成报告.md"],
    "task_exec": ["任务执行记录.md"],
    "exception_check": ["异常检查报告.md"],
    "task_feedback": ["任务反馈摘要.md"],
    "diff_analysis": ["代码差异分析.md"],
    "env_start": ["环境启动日志.md"],
    "unit_test": ["单元测试报告.md"],
    "dev_process_review": ["开发流程评审.md"],
    "solution_consistency": ["方案一致性检查.md"],
    "risk_review": ["风险评审.md"],
    "entropy_review": ["控熵评审.md"],
    "leader_review": ["研发组长评审结论.md"],
}


def node_output_artifacts(node_id: str) -> list[str]:
    """返回节点产出说明列表（用于配置 UI 只读展示）。"""
    items = NODE_OUTPUTS.get(node_id)
    if items:
        return list(items)
    return [f"archive/<stage_id>/{node_id}/ 目录下的节点交付 Markdown"]
