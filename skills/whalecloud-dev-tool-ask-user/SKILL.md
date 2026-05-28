---
name: whalecloud-dev-tool-ask-user
description: "人机问卷技能 - 按当前场景生成 questionnaire v1.0 表单 JSON，供研发会议室渲染 HITL 表单；适用于问答收集、结果确认、异常反馈。"
label: 人机问卷（Ask User）
---

# 人机问卷技能（Ask User）

当任务需要**人工处理**时，主控智能体（研发会议室中的小鲸，或其它具备本技能的 Agent）应依据当前场景生成**统一人机确认表单**，由桌面端 `MeetingHitlForm` 渲染。

Schema 定义与 Python 工具见：`src/synapse/rd_meeting/hitl_form.py`（`build_question`、`normalize_hitl_schema`、`questionnaire v1.0`）。

> **首选方式（强约束）**：研发会议室主控请**直接调用** `submit_hitl_questionnaire(kind, questions, summary, ...)` 工具提交问卷，工具返回成功后立即停止后续输出。**只有**工具不可用时才使用本技能描述的「HTML 注释 + JSON」Markdown 标记块作为兼容回退。

> **题目颗粒度（强约束）**：**每个独立可决策点对应一道独立题**，禁止把 N 个决策点合并成一道「整体确认 / 部分修改 / 拒绝」单选。如果交付物里列了 14 个 P0 待澄清问题，`questions[]` **就必须有 14 道（或更多）题**，每道题把「默认结论」作为推荐选项之一（标 ✅ 推荐）。即使你已经给出推荐值，仍要让用户对每个决策点单独表态——这是会议室人工确认的核心价值。

> **`summary`（若通过 `submit_hitl_questionnaire` 提交）**：只写本节点待确认简表，**不要**写「### 下一步」、SOP 后续节点名、Worker 文档里的 Phase 路线图；细则见 `whalecloud-dev-tool-meeting-room` SKILL §4.5.2。

---

## 何时使用

| 场景 | `kind` 建议 | `await_confirm` |
|------|-------------|-----------------|
| 会议期间向用户收集澄清 / 选项 | `interactive` | `false` |
| 节点交付前的结果确认（含归档推进） | `result_confirm` | `true` |
| 异常、风险不可控、质量不达标需人工裁决 | `exception` | `false` 或 `true` |

**研发会议室**：主控在回复**末尾**附带下方「输出标记 + JSON」后，系统将 `room_state.status` 置为 `human_intervention` 并渲染表单；**不得**同时宣称已归档或已推进下一节点。

---

## 输出格式（强制）

在面向用户的 Markdown 说明之后，**必须**追加问卷块（HTML 注释包裹 + JSON）：

### 输出格式：HTML 注释 + JSON

```markdown
（面向用户的进展说明、待确认总结等，可含 `# 交付结论`）

<!-- hitl-questionnaire:v1 kind=interactive await_confirm=false -->
```json
{
  "type": "questionnaire",
  "version": "1.0",
  "title": "需求澄清 — 请确认",
  "description": "请逐项回答后提交，小鲸将据此继续本节点议程。",
  "render": {
    "layout": "stepped",
    "showOverallProgress": true,
    "accent": "blue",
    "animate": true
  },
  "questions": [ ... ]
}
```
<!-- /hitl-questionnaire -->
```

### 标记属性

| 属性 | 取值 | 说明 |
|------|------|------|
| `kind` | `interactive` / `result_confirm` / `exception` | 介入类型，写入 `room_state.intervention_kind` |
| `await_confirm` | `true` / `false` | `true`：表单提交后走归档确认；`false`：仅收集意见并唤醒智能体继续 |

未写 `await_confirm` 时：含 `# 交付结论` 或 `kind=result_confirm` 视为 `true`，否则为 `false`。

---

## Questionnaire v1.0 Schema

顶层字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 是 | 固定 `"questionnaire"` |
| `version` | 是 | 固定 `"1.0"` |
| `title` | 推荐 | 表单标题 |
| `description` | 推荐 | 说明文案 |
| `questions` | 是 | 题目数组 |
| `render` | 否 | `layout`: `stepped`/`flat`；`accent`: `blue`/`violet`/`emerald` |

### 单题 `questions[]` 结构

| 字段 | 说明 |
|------|------|
| `id` | 唯一 ID；**结果确认**须含 `decision`（`approve`/`reject`）、可选 `comment` |
| `type` | `single` / `multiple` / `text` / `textarea`；判断题用 `single` + `optionStyle: boolean` |
| `title` | 题目标题 |
| `context` | **用户可见**的场景说明（展示在题目下方）。**强约束**：title 含「（N项）」须逐条列出 N 条完整内容；「是否满足/完整/覆盖」类签收题须嵌入章节/清单全文（从归档 Markdown 摘录）。禁止仅写「含 A/B/C 维度」关键词（工具会拒绝） |
| `options` | `[{ "value", "label", "selected": false }]` |
| `required` | 是否必填 |
| `inputEnabled` | 是否允许选项外的自定义输入 |
| `inputPlaceholder` | 自定义输入占位符 |
| `render.optionStyle` | `radio` / `checkbox` / `boolean` |
| `render.progress` | `{ "current", "total" }`（可省略，服务端会补全） |

### 题型示例

**判断题：**

```json
{
  "id": "quality_ok",
  "type": "single",
  "title": "产出是否可接受？",
  "context": "请对照上方待确认总结判断。",
  "options": [
    { "value": "true", "label": "是", "selected": false },
    { "value": "false", "label": "否", "selected": false }
  ],
  "inputEnabled": true,
  "inputPlaceholder": "如有具体问题请说明：",
  "render": { "optionStyle": "boolean" }
}
```

**单选（固定 value，便于后端解析）：**

```json
{
  "id": "decision",
  "type": "single",
  "title": "确认结论",
  "required": true,
  "options": [
    { "value": "approve", "label": "通过 — 归档并进入下一节点", "selected": false },
    { "value": "reject", "label": "不通过 — 返工本节点", "selected": false }
  ],
  "render": { "optionStyle": "radio" }
}
```

---

## 场景化生成指引

1. **问答 / 澄清**：按议题拆 3–8 题，优先 `single`/`multiple`；每题末尾补充输入框与问卷末「还有什么需要补充」由桌面端组件**自动追加**，无需手写 `inputEnabled` 或补充题。
2. **结果确认**：先 1–2 题审阅质量/风险，最后一题固定 `decision` + 可选 `comment`（`textarea`）。
3. **异常反馈**：标题点明异常类型；`decision` 或等价单选区分「继续重试 / 跳过 / 终止」；`context` 写清影响范围。

生成后自检：

- JSON 可被 `json.loads` 解析；
- 至少包含非空 `questions` 数组；
- 结果确认类必须含 `decision` 且 `approve`/`reject` value 与会议室解析一致。
- **`kind=interactive` 时**：每题 `options[]` 只含该题互斥选项（禁止把 Q1～QN 塞进一题）；选项写在 `options` 而非 `title`/`context`（`A. … B. …` 须进 `options[]`）。

**服务端自动修复（仅 `interactive`）**：

| 违规形态 | 系统行为 |
|----------|----------|
| 选项写在 `context`/`title`，`options` 为空 | 尝试从题面提取 `A./1./可选：` 等到 `options[]`；提取失败 → **拒绝提交** |
| 单题 `options ≥ 5` 且各 option 像独立决策点（Q1、✅ 推荐、维度：结论） | **拒绝提交**，要求拆成多题 |
| 真正的开放题（题面无选项模式） | 仍降级为 `textarea` 供手写 |

实现见 `src/synapse/rd_meeting/questionnaire_repair.py`。

---

## 与会议室其它机制的关系

- **会中澄清 / 异常介入**：问卷**仅**来自本技能输出的 `hitl-questionnaire`（或协作写入的 `.questions.json`）；系统**不会**生成默认题目。
- **结果确认**（节点归档验收）：无动态问卷时可使用 `default_hitl_form_schema` 结构化字段；本技能输出仍优先覆盖。
- 未输出有效 `hitl-questionnaire` 时，Setup Center 不展示表单，需在对话区说明或请主控重新产出问卷。
- IM / 通用对话中的 `ask_user` **工具**与本技能**独立**；会议室场景请用本技能的 JSON 标记，以便 Setup Center 渲染统一表单。

---

## 参考

- 实现：`src/synapse/rd_meeting/hitl_form.py`、`src/synapse/rd_meeting/questionnaire_repair.py`
- 前端：`apps/setup-center/src/components/rd-manage/meeting/MeetingHitlForm.tsx`
- 示例 JSON：`scripts/hitl-form-demo-schema.json`
- 会议室规范：`whalecloud-dev-tool-meeting-room`
