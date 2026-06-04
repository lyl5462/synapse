# 模板填充规范

## 占位符语法

与现有研发文档模板一致，支持以下形式：

| 语法 | 含义 | 示例 |
|------|------|------|
| `{{VAR}}` | 标量替换 | `{{TIMESTAMP}}`、`{{PROD}}` |
| `{{#each list}}...{{/each}}` | 列表循环 | `{{#each scenarios}}...{{/each}}` |
| `{{#if flag}}...{{/if}}` | 条件块（flag 为真/非空时保留） | `{{#if sub_questions}}...{{/if}}` |
| `{{@index}}` | 循环序号（从 1 起） | 表格行号 |

## 变量来源（合并优先级从低到高）

1. 调用方通过 Parameters 传入的标量（如 `PROD`、`STATUS`）。
2. `CONTEXT_FILES` 中各 Markdown / JSON 文件解析出的字段（JSON 顶层键与模板变量同名则直接映射）。
3. `CONTEXT_JSON`（内联 JSON 字符串或 `.json` 文件路径）中的键值。
4. 系统字段：`TIMESTAMP`（当前 ISO 8601 本地时间，若无则 UTC）。

后出现的同源键覆盖先前的值。

## 内容可靠性

- **只写有据内容**：变量值须来自上下文文件、用户确认记录、源码/文档核验结果或调用方显式传入；不得臆造路径、接口、类名、数据。
- **未知留痕**：无法确认时填 `[待确认]`；缺上下文时填 `[待补充]`；缺某仓库证据时填 `[待补充-{REPO}仓库未获取]`（与 GitNexus 系列技能一致）。
- **循环块**：列表为空时保留章节标题，表格/列表区写「（无）」或调用方在 `CONTEXT_JSON` 中传入说明性占位条目。
- **覆盖率**：生成前扫描模板中全部 `{{...}}` 占位符；未提供值的标量填 `[待补充]`，并在内部（不写入正文）记录缺失列表；若 `STRICT=true` 且缺失必填变量则**中止**。

## 必填变量建议

各模板应在模板文件或本目录说明中标注「必填变量」。通用建议：

| 变量 | 说明 |
|------|------|
| `TIMESTAMP` | 自动生成 |
| `STATUS` | 如 `draft` / `confirmed` |
| 与模板标题相关的名称字段 | 如 `REQUIREMENT_NAME`、`PROD` 等，由调用方传入 |

## 函数级方案（`函数级方案.md`）

- `CONTEXT_JSON` 为**内联 JSON 字符串**或 **`.json` 文件路径**（与其它模板相同）。
- 使用结构化字段（列表 + 标量），**禁止** `DOCUMENT_BODY`；骨架见 `whalecloud-dev-tool-function-solution/references/function_solution_context.skeleton.json`。
- **必须**经 `run_skill_script` 运行 `scripts/fill_function_solution.py`（填充前 `validate_context` 校验契约），**禁止**手填 `{{VAR}}` / `{{#each}}`；脚本仅写 `.tmp` 草稿，交付物须 `read_file` + `write_file`（见 doc-generate Step 3a）。
- 可选预检：`run_skill_script(..., script_name="fill_function_solution.py", args=["--validate-only", "<context.json>"])`
- 验收：无 `{{` 残留；保留模板全部固定标题（`## 1. 方案内容` … `## 2. 附录`、`### 1.7 模块改造方案` 等）及表格列名。

## 输出

- 填充完成后得到纯 Markdown 字符串，不含 Handlebars 未解析残留（不应出现 `{{#each` 等）。
- 写入 `{OUTPUT_DIR}/{OUTPUT}`：**必须** `write_file`，UTF-8（无 BOM），换行符 `\n`。
- 文档中含中文时，变量值与正文均须为合法 Unicode 字符；**禁止**以 GBK/GB2312/GB18030/UTF-16 等编码写入后再按 UTF-8 误读。

### 写盘与字符编码（强制）

| 操作 | 要求 |
|------|------|
| 读模板、CONTEXT_FILES、CONTEXT_JSON 文件 | UTF-8 |
| 写交付物 `{OUTPUT_DIR}/{OUTPUT}` | **必须**调用 `write_file`（UTF-8，无 BOM） |
| 写后验证 | **必须**用 `read_file` 读回；含中文时检查无乱码 |
| 内存中的填充结果 | Unicode 字符串，落盘前不做非 UTF-8 转码 |

**禁止**通过 shell 重定向、Python/Node/PowerShell 脚本等方式写盘；`OUTPUT_MODE=file` 或 `both` 时落盘步骤不可省略或替代。

**写后验证**：若出现 U+FFFD 替换字符、`Ã`、`ï¿½` 等乱码特征，视为编码错误，**不得交付**，须确认使用了 `write_file` 后重试。
