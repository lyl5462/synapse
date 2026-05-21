---
name: whalecloud-dev-tool-ask-user
description: "人机问卷技能 - 按当前场景生成 questionnaire v1.0 表单 JSON，供研发会议室渲染 HITL 表单；适用于问答收集、结果确认、异常反馈。"
label: 人机问卷（Ask User）
---

# 人机问卷技能（Ask User）

当任务需要**人工处理**时，主控智能体（研发会议室中的小鲸，或其它具备本技能的 Agent）应依据当前场景生成**统一人机确认表单**，由桌面端 `MeetingHitlForm` 渲染。

Schema 定义与 Python 工具见：`src/synapse/rd_meeting/hitl_form.py`（`build_question`、`normalize_hitl_schema`、`questionnaire v1.0`）。

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

在面向用户的 Markdown 说明之后，**必须**追加问卷块（二选一，推荐 HTML 注释包裹）：

### 方式 A（推荐）：HTML 注释 + JSON

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

### 方式 B：围栏代码块

````markdown
```hitl-questionnaire
{ ... 同上 JSON，单行 type 字段不可省略 ... }
```
````

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
| `context` | 场景说明（展示在题目下方） |
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

1. **问答 / 澄清**：按议题拆 3–8 题，优先 `single`/`multiple`；开放补充用 `inputEnabled: true`。
2. **结果确认**：先 1–2 题审阅质量/风险，最后一题固定 `decision` + 可选 `comment`（`textarea`）。
3. **异常反馈**：标题点明异常类型；`decision` 或等价单选区分「继续重试 / 跳过 / 终止」；`context` 写清影响范围。

生成后自检：

- JSON 可被 `json.loads` 解析；
- 至少包含非空 `questions` 数组；
- 结果确认类必须含 `decision` 且 `approve`/`reject` value 与会议室解析一致。

---

## 与会议室其它机制的关系

- 节点配置 `human_confirm: true` 时，系统仍有**默认问卷**（`default_hitl_form_schema`）；本技能输出的 JSON **优先**覆盖默认 schema。
- 未输出 `hitl-questionnaire` 标记时，行为与 `whalecloud-dev-tool-meeting-room` §1.2 一致（配置驱动默认表单）。
- IM / 通用对话中的 `ask_user` **工具**与本技能**独立**；会议室场景请用本技能的 JSON 标记，以便 Setup Center 渲染统一表单。

---

## 参考

- 实现：`src/synapse/rd_meeting/hitl_form.py`
- 前端：`apps/setup-center/src/components/rd-manage/meeting/MeetingHitlForm.tsx`
- 示例 JSON：`scripts/hitl-form-demo-schema.json`
- 会议室规范：`whalecloud-dev-tool-meeting-room`
