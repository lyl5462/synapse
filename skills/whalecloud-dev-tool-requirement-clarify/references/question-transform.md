# question-transform.py — 问题格式转换工具

将命令行参数转换为前端可渲染的 JSON 格式问题。

## 参数说明

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--type` | 否 | 问题类型：`single`（单选）、`multiple`（多选）、`boolean`（判断） | `--type=single` |
| `--title` | 是* | 问题标题（生成问题时必填，更新问题时必填） | `--title="限流档位的表示方式"` |
| `--context` | 否 | 问题的描述信息 | `--context="请选择限流档位表示方式"` |
| `--option1` ~ `--optionN` | 否* | 选项内容（生成问题时必填，更新时不需要） | `--option1="固定三级" --option2="数字范围自定义"` |
| `--custom` | 否 | 是否允许用户自定义输入，默认 `true` | `--custom=true` |
| `--answer` | 否* | 用户答案（更新问题时必填） | `--answer="固定三级"` |
| `--reset` | 否 | 清空记录文件 | `--reset` |
| `--read` | 否 | 读取未回答的问题并输出JSON格式 | `--read` |
| `--readall` | 否 | 读取所有问题并格式化输出（包含已解决状态） | `--readall` |
| `--update` | 否 | 更新问题答案并标记为已解决（需配合 --title 和 --answer 使用） | `--update --title="问题标题" --answer="用户答案"` |

> 注：`*` 表示在对应模式下必填

## 使用模式

### 模式一：生成单个问题

直接生成一个问题并输出：

```bash
py question-transform.py --type=single --title="限流档位的表示方式" --context="请选择限流档位表示方式" --option1="固定三级" --option2="数字范围自定义" --option3="自定义标签" --custom=true
```

**输出：**
```json
{
  "type": "questionnaire",
  "version": "1.0",
  "questions": [
    {
      "id": "q1",
      "type": "single",
      "title": "限流档位的表示方式",
      "context": "请选择限流档位表示方式",
      "options": [
        { "value": "A", "label": "固定三级", "selected": false },
        { "value": "B", "label": "数字范围自定义", "selected": false },
        { "value": "C", "label": "自定义标签", "selected": false }
      ],
      "inputEnabled": true,
      "inputPlaceholder": "或者你的答案：",
      "required": false,
      "render": {
        "layout": "vertical",
        "optionStyle": "radio",
        "showProgress": true,
        "progress": { "current": 1, "total": 1 }
      }
    }
  ]
}
```

### 模式二：累积多个问题

通过多次调用脚本，累积多个问题后统一输出：

```bash

# 逐个添加问题
py question-transform.py --type=single --title="Q1" --context="描述1" --option1="A" --option2="B"
py question-transform.py --type=multiple --title="Q2" --context="描述2" --option1="C" --option2="D"
py question-transform.py --type=boolean --title="Q3" --context="描述3"

# 读取未回答的问题（JSON格式输出）
py question-transform.py --read
```

> ⚠️ **注意**：`--read` 只返回未回答的问题，已回答的问题会被过滤掉。如需查看所有问题（含已解决状态），请使用 `--readall`。

**--read 输出：**
```json
{
  "type": "questionnaire",
  "version": "1.0",
  "questions": [
    {
      "id": "q2",
      "type": "multiple",
      "title": "Q2",
      "context": "描述2",
      "options": [...],
      "render": {
        "optionStyle": "checkbox",
        "progress": { "current": 1, "total": 1 }
      }
    }
  ]
}
```

### 模式三：更新问题答案

当用户回答问题后，可以更新记录文件中的答案并标记为已解决：

```bash
# 更新问题答案并标记为已解决
py question-transform.py --update --title="Q1" --answer="A"
```

### 模式四：查看所有问题

查看记录文件中的所有问题（含已解决状态）：

```bash
# 格式化输出所有问题
py question-transform.py --readall
```

**--readall 输出：**
```
问题1：Q1 内容：描述1 状态：已解决 用户回复：A
问题2：Q2 内容：描述2 状态：未解决
```

## 输出字段说明

| 字段 | 说明 |
|------|------|
| `type` | 固定为 `questionnaire` |
| `version` | 版本号 `1.0` |
| `questions[].id` | 问题ID |
| `questions[].type` | 问题类型：`single`（单选）、`multiple`（多选） |
| `questions[].title` | 问题标题 |
| `questions[].context` | 问题描述 |
| `questions[].options` | 选项列表 |
| `questions[].options[].value` | 选项值（A、B、C...） |
| `questions[].options[].label` | 选项显示文本 |
| `questions[].inputEnabled` | 是否启用输入框 |
| `questions[].inputPlaceholder` | 输入框占位符 |
| `questions[].render.optionStyle` | 渲染样式：`radio`（单选）、`checkbox`（多选）、`boolean`（判断） |
| `questions[].render.progress` | 进度信息（current/total） |
| `questions[].answer` | 用户回答的答案（仅在问题被更新后存在） |
| `questions[].resolved` | 问题是否已解决（true/false，仅在问题被更新后存在） |

## 记录文件

累积问题时会生成临时文件 `.questions.json`，存储在脚本同目录下：

- `--reset`：删除记录文件
- `--read`：读取未回答的问题，不删除记录文件
- `--readall`：格式化输出所有问题（含已解决状态），不删除记录文件
- `--update`：更新问题答案并标记为已解决
- 其他参数：追加到记录文件

---

## BDD 问题生成指南

本技能采用 BDD 思想生成澄清问题，遵循以下原则：

### 示例驱动原则

生成问题时，必须先推导具体示例场景，再将场景转化为问题选项。

**生成流程**：
1. 识别业务规则（蓝色卡片）
2. 推导具体示例场景（绿色卡片）
3. 将示例场景作为问题的 context（假设...）
4. 将不同行为结果作为选项

**命令示例**：

```bash
# ❌ 错误：抽象分类问题
py question-transform.py --type=single --title="限流策略的类型" --context="请选择限流策略类型" --option1="令牌桶" --option2="漏桶"

# ✅ 正确：示例驱动问题
py question-transform.py --type=single --title="限流档位的表示方式" --context="假设某接口当前限流为'中'档，运维人员希望调整为更高档位，限流档位的表示方式是？" --option1="固定三级：低/中/高" --option2="数字范围1-1000自定义" --option3="固定五档" --option4="自定义标签绑定数值"
```

### 三视角标注原则

深度澄清阶段的问题，必须在 context 中标注视角标签：

```bash
# 业务视角
py question-transform.py --type=single --title="紧急放宽限流的业务效果" --context="[业务视角] 假设电商大促期间，运维将订单接口限流从'中'紧急调为'高'，期望达到什么业务效果？" --option1="立刻放量" --option2="渐进式提升" --option3="仅影响排队顺序"

# 开发视角
py question-transform.py --type=single --title="限流器状态切换方式" --context="[开发视角] 假设接口限流从'中'变更为'高'，现有限流器的内部状态如何切换？" --option1="修改内存配置" --option2="重置令牌桶" --option3="需重启组件"

# 测试视角
py question-transform.py --type=single --title="长连接中的限流变更行为" --context="[测试视角] 假设限流策略变更过程中，有3个长连接正按旧策略处理请求，变更后的行为是？" --option1="继续按旧策略执行" --option2="立即切换可能导致请求中断" --option3="暂停等待变更完成后恢复"
```

### 问题类型选择规则

| 情境 | 问题类型 | 说明 |
|------|---------|------|
| 行为有多种可能结果 | `single` / `multiple` | 选项为不同行为结果 |
| 行为可通过代码/文档确认 | `boolean`（判断题） | 在 context 中标注证据来源 |
| 范围圈定阶段 | `single` / `multiple` | 无需三视角标注 |
| 深度澄清阶段 | `single` 为主 | 必须三视角标注 |
