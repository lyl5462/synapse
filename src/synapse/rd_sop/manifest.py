"""SOP Manifest：节点 intent / type / default_binding（Phase 2）。"""

from __future__ import annotations

from typing import Any, Literal

from synapse.rd_sop.nodes import ALL_NODES, STAGES

PriorOutputUseMode = Literal["skill_required", "flow_required", "llm_judge"]

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
    "auto_split": "system",
    "sandbox_build": "system",
    "env_pregen": "system",
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
    "func_solution": "功能方案定位到函数级，控制改造范围，小鲸只负责检查对应方案的合理性，而产品设计专家负责方案文档的生成。",
    "entropy_gen": "生成 agent.md、rule.md 等控熵文件。",
    "solution_review": "方案评审与可行性验证。",
    "auto_split": "按需求与方案自动拆分研发子单（系统脚本）。",
    "sandbox_build": "构造研发沙箱基础环境（系统 git 落盘）。",
    "env_pregen": "拉取文档与控熵文件，预生成开发环境（系统脚本）。",
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


def is_system_node(node_id: str) -> bool:
    return NODE_TYPES.get((node_id or "").strip(), "") == "system"


def default_human_confirm(node_id: str) -> bool:
    """节点是否默认开启「人工确认」配置（与 NODE_TYPES 对齐，运行时可覆盖）。"""
    if is_system_node(node_id):
        return False
    t = NODE_TYPES.get(node_id, "")
    if t in ("human", "human_start", "ai_human", "human_multi"):
        return True
    if t == "ai_exception":
        return True
    return False


def is_human_only_node(node_id: str) -> bool:
    """已废弃：人工型节点仍走智能体协作，人工参与度由 `human_confirm` 与运行时交互决定。"""
    return NODE_TYPES.get(node_id, "") == "human"


# 节点产出文档（只读展示；归档路径 archive/<stage_name>/<node_id>/）
NODE_OUTPUTS: dict[str, list[str]] = {
    "pending": ["（系统节点，无归档产出）"],
    "req_clarify": ["需求澄清.md"],
    "boundary": ["边界确认说明.md"],
    "module_func": ["模块功能.md"],
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
    return [f"archive/<stage_name>/{node_id}/ 目录下的节点交付 Markdown"]


# 当前节点消费前序产出物的显式规则（未列出的已归档产出默认为 llm_judge）
# use_mode: skill_required | flow_required | llm_judge
NODE_PRIOR_OUTPUT_RULES: dict[str, list[dict[str, Any]]] = {
    "boundary": [
        {
            "source_node_id": "req_clarify",
            "artifacts": ["需求澄清.md"],
            "use_mode": "flow_required",
            "note": "边界判定须引用已澄清需求要点",
        },
    ],
    "module_func": [
        {
            "source_node_id": "req_clarify",
            "artifacts": ["需求澄清.md"],
            "use_mode": "skill_required",
            "note": "whalecloud-dev-tool-module-function 固定路径",
        },
    ],
    "acceptance": [
        {
            "source_node_id": "module_func",
            "artifacts": ["模块功能.md"],
            "use_mode": "flow_required",
            "note": "验收标准须基于模块功能清单",
        },
        {
            "source_node_id": "req_clarify",
            "artifacts": ["需求澄清.md"],
            "use_mode": "llm_judge",
        },
    ],
    "func_solution": [
        {
            "source_node_id": "module_confirm",
            "artifacts": ["模块范围确认.md"],
            "use_mode": "flow_required",
            "note": "函数级方案须对齐已确认模块范围",
        },
        {
            "source_node_id": "module_func",
            "artifacts": ["模块功能.md"],
            "use_mode": "flow_required",
            "note": "函数级方案须基于模块功能清单",
        },
    ],
    "solution_review": [
        {
            "source_node_id": "func_solution",
            "artifacts": ["函数级方案.md"],
            "use_mode": "flow_required",
            "note": "方案评审须对照函数级方案全文",
        },
    ],
    "unit_test": [
        {
            "source_node_id": "acceptance",
            "artifacts": ["验收标准.md"],
            "use_mode": "skill_required",
            "note": "单元测试用例须覆盖验收标准",
        },
    ],
    "solution_consistency": [
        {
            "source_node_id": "func_solution",
            "artifacts": ["函数级方案.md"],
            "use_mode": "skill_required",
            "note": "一致性检查须对照函数级方案",
        },
    ],
}


def prior_output_use_mode_for(
    consumer_node_id: str,
    *,
    source_node_id: str,
    artifact: str,
) -> tuple[PriorOutputUseMode | None, str]:
    """解析当前节点对某前序产出物的用法；无显式规则且应展示时默认 llm_judge。"""
    rules = NODE_PRIOR_OUTPUT_RULES.get((consumer_node_id or "").strip()) or []
    for rule in rules:
        if str(rule.get("source_node_id") or "") != source_node_id:
            continue
        artifacts = rule.get("artifacts")
        if isinstance(artifacts, list) and artifacts:
            if artifact not in [str(a) for a in artifacts]:
                continue
        mode = str(rule.get("use_mode") or "llm_judge")
        if mode not in ("skill_required", "flow_required", "llm_judge"):
            mode = "llm_judge"
        note = str(rule.get("note") or "").strip()
        return mode, note  # type: ignore[return-value]
    return "llm_judge", ""
