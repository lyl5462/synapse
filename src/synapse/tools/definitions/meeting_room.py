"""研发会议室专用工具定义。"""

MEETING_ROOM_TOOLS = [
    {
        "name": "submit_meeting_work_plan",
        "category": "Meeting Room",
        "description": (
            "Submit a structured work allocation plan for the current R&D meeting room node. "
            "REQUIRED before delegate_to_agent or delegate_parallel in rd_meeting host sessions. "
            "List each worker agent_id, task, and reason based on capability cards and NODE_INTENT."
        ),
        "detail": (
            "提交研发会议室本节点的工作安排计划（主控小鲸专用）。\n\n"
            "**强制流程**：\n"
            "1. 阅读能力卡片与会议目标，拆分可委派的子任务\n"
            "2. 调用本工具提交计划（items 非空，每项含 agent_id / task / reason）\n"
            "3. 再按 plan 使用 delegate_to_agent 或 delegate_parallel\n\n"
            "**注意**：\n"
            "- agent_id 必须属于当前节点 binding 的 worker_profile_ids\n"
            "- 已开始委派后不可再修改计划\n"
            "- 不需要人工审批计划，提交后即可委派"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_summary": {
                    "type": "string",
                    "description": "本节点工作目标摘要（与 NODE_INTENT 对齐）",
                },
                "items": {
                    "type": "array",
                    "description": "工作安排条目（至少 1 条）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "计划条目 ID（如 t1），用于 delegate 时 plan_item_id 关联",
                            },
                            "agent_id": {
                                "type": "string",
                                "description": "协作智能体 Profile ID",
                            },
                            "task": {
                                "type": "string",
                                "description": "该智能体要完成的子任务描述",
                            },
                            "reason": {
                                "type": "string",
                                "description": "为何派给该智能体（能力匹配说明）",
                            },
                            "parallel_group": {
                                "type": "string",
                                "description": "可选；相同 parallel_group 可并行委派",
                            },
                        },
                        "required": ["agent_id", "task", "reason"],
                    },
                },
            },
            "required": ["goal_summary", "items"],
        },
    },
]
