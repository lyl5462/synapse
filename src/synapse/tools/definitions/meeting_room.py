"""研发会议室专用工具定义。"""

MEETING_ROOM_TOOLS = [
    {
        "name": "submit_hitl_questionnaire",
        "category": "Meeting Room",
        "description": (
            "Submit a structured HITL questionnaire (questionnaire v1.0) for the current R&D "
            "meeting room node. REQUIRED whenever you need user confirmation: clarify gates, "
            "result confirmation, or exception escalation. Once submitted the room enters "
            "human_intervention immediately; do NOT claim the questionnaire is delivered without "
            "calling this tool."
        ),
        "detail": (
            "提交研发会议室本节点的人机问卷（主控小鲸专用，结构化版本）。\n\n"
            "**优先级最高**：在异常 / 结果确认 / 会中澄清场景，**必须**调用本工具，"
            "替代旧的 ``<!-- hitl-questionnaire -->`` Markdown 标记块。\n\n"
            "**调用即锁定**：返回成功后，房间立即进入 ``human_intervention``，"
            "你应停止后续工具调用与正文输出；系统会忽略本轮后续文本，以工具写入的 schema 为准。\n\n"
            "**参数要点**：\n"
            "- ``kind``：``interactive``（会中澄清）/ ``result_confirm``（节点终稿确认）/ ``exception``（异常裁决）\n"
            "- ``await_confirm``：true 表示提交后等待确认才推进；result_confirm 默认 true，其余默认 false\n"
            "- ``questions``：至少 1 条 questionnaire v1.0 题目；每题需含 id / type / title\n"
            "- ``summary``：可选 Markdown，**会渲染在表单顶部**「待确认总结」；写核心变化、产出文件、与 questions 对齐的简表；"
            "**禁止**写 ``### 下一步``、SOP 下一节点预告、Worker 文档 Phase 1~N 路线图（见 meeting-room SKILL §4.5.2）\n\n"
            "**context 可审阅性（强约束，工具会校验）**：\n"
            "- title 含「（N项）」「共 N 条」→ context 须逐条列出 N 条完整内容（Markdown 列表/表格）；\n"
            "- 「是否满足/完整/覆盖」类签收题 → context 须嵌入该章节/清单全文或逐条列表（从归档 Markdown read_file 摘录）；\n"
            "- **禁止** context 仅写「含 A/B/C 维度」类关键词。\n\n"
            "**题目颗粒度（强约束）**：每个独立可决策点 = 一道独立题。\n"
            "- 禁止把 N 个决策点合并成一道「整体确认 / 部分修改 / 拒绝」单选；\n"
            "- 即使你已经给出推荐默认结论，**仍要**把每个决策点单独成题，把默认结论作为推荐选项；\n"
            "- 如果交付文档列出 14 个 P0 问题，``questions`` 必须 ≥14 道。\n"
            "- 系统会校验：当 ``summary`` 中明显列举了多个待确认项却只给 1~2 道题时，"
            "工具会拒绝提交并要求按颗粒度规则重新组织。\n\n"
            "**题型与人工输入（强约束）**：\n"
            "- ``type`` 必须按决策语义选择：互斥用 ``single``；**可同时成立的多项必须用 ``multiple``**；"
            "二元用 ``boolean``；短/长输入用 ``text`` / ``textarea``。禁止把可多选的决策强行拆成多个 ``boolean``。\n"
            "- 每题人工输入框与末尾补充题由桌面端表单组件**自动追加**，无需在 ``questions`` 里设置 "
            "``inputEnabled`` 或手写补充题。\n\n"
            "**人工确认开关（``human_confirm: true``）下的硬约束**：\n"
            "- **每次**收到 Worker 响应、**每次**做下一步决策前（重派 / 换人 / 收敛 / 归档），"
            "都必须先调用本工具（``kind=\"interactive\"``）与用户交互，再继续推进；\n"
            "- 严禁自行替用户「拍板」「自动通过」「自动重派」。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["interactive", "result_confirm", "exception"],
                    "description": "介入类型",
                },
                "await_confirm": {
                    "type": "boolean",
                    "description": "true 表示提交后须用户确认才推进；省略时按 kind 推断",
                },
                "title": {"type": "string", "description": "表单标题"},
                "description": {"type": "string", "description": "表单说明"},
                "summary": {
                    "type": "string",
                    "description": (
                        "可选；表单上方待确认总结。仅列本节点待确认要点简表（与 questions 编号一致）；"
                        "禁止 ### 下一步、确认后进入某阶段、Phase 1~N 路线图、SOP 下一节点预告"
                    ),
                },
                "questions": {
                    "type": "array",
                    "description": "questionnaire v1.0 题目数组（至少 1 条）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["single", "multiple", "boolean", "text", "textarea"],
                            },
                            "title": {"type": "string"},
                            "context": {
                                "type": "string",
                                "description": (
                                    "题目下方展示的场景说明；签收/（N项）类题须嵌入完整待审阅正文"
                                    "（Markdown 列表或表格），禁止仅写维度关键词"
                                ),
                            },
                            "required": {"type": "boolean"},
                            "options": {"type": "array"},
                            "inputEnabled": {"type": "boolean"},
                            "inputPlaceholder": {"type": "string"},
                            "render": {"type": "object"},
                        },
                        "required": ["id", "type", "title"],
                    },
                },
            },
            "required": ["kind", "questions"],
        },
    },
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
