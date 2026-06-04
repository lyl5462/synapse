---
name: whalecloud-dev-tool-doc-generate
description: "通用 Markdown 文档生成工具：按 OUTPUT 文件名自动匹配 templates/ 下模板，合并 CONTEXT_JSON 与参数填充占位符，将可核验内容写入 OUTPUT_DIR。Use when generating structured Markdown deliverables from templates."
label: 文档生成工具
---

# 文档生成工具

读取本技能 `templates/` 目录下的 Markdown 模板，将上下文信息填充后保存到指定路径。后续新增模板只需在 `templates/` 增加文件，并约定调用方 `OUTPUT` 与模板文件名一致。

## 何时使用

- 流水线某阶段需要将**结构化上下文**落成固定格式 Markdown 文件。
- 调用方已完成分析/澄清/核验，仅需**选模板 → 填变量 → 写盘**。

本技能**不负责**提问、源码检索或业务分析；仅负责模板匹配、变量合并、内容可靠性约束与落盘。

---

## 内置模板

| 模板文件 | 典型 OUTPUT | 说明 |
|----------|-------------|------|
| `templates/需求澄清.md` | `需求澄清.md` | 需求澄清交付文档 |
| `templates/模块功能.md` | `模块功能.md` | 模块功能清单 |
| `templates/函数级方案.md` | `函数级方案.md` | 函数级改造方案 |

新增模板：在 `templates/` 下放置 `{文件名}.md`，调用时设 `OUTPUT` 与文件名一致即可。

---

## Parameters

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `OUTPUT_DIR` | 是 | 输出目录，如 `./requirements/` |
| `OUTPUT` | 是 | 输出文件名，须与 `templates/` 下某模板文件名一致，如 `需求澄清.md` |
| `TEMPLATE` | 否 | 显式指定模板文件名（相对 `templates/`），默认等于 `OUTPUT` |
| `CONTEXT_JSON` | 是 | 模板变量：内联 **JSON 字符串**（如 `"{\"key\":\"value\"}"`），或已存在的 UTF-8 **`.json` 文件路径**（大对象推荐） |
| `CONTEXT_FILES` | 否 | 逗号分隔的上下文文件路径（Markdown / JSON），用于抽取或补充变量 |
| `STRICT` | 否 | 默认 `false`。为 `true` 时，模板必填占位符未提供则中止 |
| `OUTPUT_MODE` | 否 | `file`（默认，仅写盘）、`content`（仅输出 Markdown 正文）、`both`（写盘并输出正文） |
| `PROD` | 否 | 产品名称等标量，可直接映射到同名模板变量 |
| `STATUS` | 否 | 文档状态，如 `draft` / `confirmed` |
| `REQUIREMENT_NAME` | 否 | 需求或文档标题类标量 |

其他与模板占位符同名的 Parameter 均可直接传入，参与填充（见 [references/template-filling.md](references/template-filling.md)）。

---

## 共享脚本（`scripts/`，`run_skill_script`）

| 脚本 | 用途 |
|------|------|
| `scripts/fill_function_solution.py` | `OUTPUT=函数级方案.md` 时**必须**调用；含 `--validate-only` 契约预检 |
| `scripts/fill_clarify.py` | `OUTPUT=需求澄清.md` 时可选，替代手填 `{{#each}}` |

**推荐**通过 `run_skill_script` 调用（`script_name` 用下表文件名即可，loader 会在 `scripts/` 下解析）：

```
run_skill_script(
  skill_name="whalecloud-dev-tool-doc-generate",
  script_name="fill_function_solution.py",
  args=[
    "skills/whalecloud-dev-tool-doc-generate/templates/函数级方案.md",
    "{OUTPUT_DIR}/.tmp/_function_solution_fill_ctx.json",
    "{OUTPUT_DIR}/.tmp/_function_solution_fill_out.md"
  ]
)
```

契约预检：

```
run_skill_script(
  skill_name="whalecloud-dev-tool-doc-generate",
  script_name="fill_function_solution.py",
  args=["--validate-only", "{OUTPUT_DIR}/.tmp/_function_solution_fill_ctx.json"]
)
```

需求澄清填充示例：

```
run_skill_script(
  skill_name="whalecloud-dev-tool-doc-generate",
  script_name="fill_clarify.py",
  args=[
    "skills/whalecloud-dev-tool-doc-generate/templates/需求澄清.md",
    "{OUTPUT_DIR}/.tmp/_clarify_fill_ctx.json",
    "{OUTPUT_DIR}/.tmp/_clarify_fill_out.md"
  ]
)
```

---

## 核心约束

### A. 职责边界

- **做**：匹配模板、读上下文、填充占位符、校验可靠性标记、通过 `write_file` 写入 `{OUTPUT_DIR}/{OUTPUT}`。
- **不做**：生成澄清问题、GitNexus 检索、业务规则推导（由上游技能完成后再调用本技能）。

### B. 内容可靠性（强制）

- 仅写入上下文或调用方已核验过的内容；**禁止虚构**代码路径、接口、类名、业务结论。
- 无法确认：`[待确认]`；缺资料：`[待补充]`；缺某仓证据：`[待补充-{REPO}仓库未获取]`。
- 填充后文档中**不得残留**未解析的 `{{` 占位符或 `{{#each` 块标记。

### C. 字符编码（强制）

本技能产出与读取的 Markdown / JSON **一律使用 UTF-8**（无 BOM）。含中文的模板、上下文与交付物**禁止**以 GBK、GB2312、GB18030、Big5 或 UTF-16 等编码读写。

| 环节 | 要求 |
|------|------|
| 读模板 `templates/*.md` | UTF-8 |
| 读 `CONTEXT_JSON` / `CONTEXT_FILES` | UTF-8；非法 JSON 或解码失败 → **中止** |
| 写 `{OUTPUT_DIR}/{OUTPUT}` | **必须** `write_file`（UTF-8，无 BOM），换行 `\n` |
| `OUTPUT_MODE=content` / `both` | 通道输出的 Markdown 正文须为 UTF-8 字符串，不得经错误编码转码 |

**写盘方式（强制）**：

- **必须**使用 Synapse `write_file` 工具写入 `{OUTPUT_DIR}/{OUTPUT}`（内置 UTF-8，自动创建父目录）。
- **禁止**通过 `run_shell`、Python `open()`、Node `fs.writeFileSync`、PowerShell `Set-Content`/`Out-File`/`>` 重定向等方式写盘（Windows 下易产出 UTF-16 或 GBK 乱码）。

```json
{
  "path": "{OUTPUT_DIR}/{OUTPUT}",
  "content": "<填充后的 Markdown 正文>"
}
```

**写后自检（含中文时必做）**：

- 用 `read_file` 读回 `{OUTPUT_DIR}/{OUTPUT}`，确认中文可读、无 U+FFFD 替换字符或典型乱码（如 `Ã©`、`ï¿½`）。
- 自检失败 → **中止**，不得交付乱码文件；检查是否误用了非 `write_file` 的写盘方式后重试。

### D. 输出模式

| OUTPUT_MODE | 行为 |
|-------------|------|
| `file` | 写盘后结束；除异常外不向用户输出解释性文字 |
| `content` | 不写盘，仅输出填充后的 Markdown 正文（无代码围栏） |
| `both` | 写盘并输出 Markdown 正文 |

上游技能若要求「生成文档阶段只能输出 Markdown」，应设 `OUTPUT_MODE=content` 或 `both`，且调用方自行保证不写额外说明。

---

## 研发会议室人机台账（HITL）

当 Host 运行时头给出节点归档下的 **`hitl_context.json` 绝对路径**且文件存在时：

1. **必须先** `read_file` 该路径（UTF-8 JSON），作为 `CONTEXT_JSON` 的主数据源（可传文件路径或解析后的对象字段）。
2. 综合 `rounds[]` 与 `confirmed_by_id` 中的全量用户确认项填充模板；**禁止**仅凭本轮对话摘要或 `人机交互清单.md` 落盘。
3. **禁止**自写 `clarify_context.json` 等替代文件名；会议室节点唯一机器台账为 `hitl_context.json`。
4. `result_confirm` 验收问卷**不得**触发整篇覆盖已生成的会议产出。

---

## 工作流程

```
Step 0 — 参数校验
  0a. 校验 OUTPUT_DIR、OUTPUT 已提供；OUTPUT_DIR 不可写则中止。
  0b. 解析 OUTPUT_MODE（默认 file）、STRICT（默认 false）、TEMPLATE（默认 OUTPUT）。

Step 1 — 读取模板
  1a. 模板路径 = 本技能目录 templates/{TEMPLATE}
  1b. 文件不存在 → 中止，列出 templates/ 下现有 .md 文件名
  1c. 以 UTF-8 读取模板正文；解码失败 → **中止**，提示检查模板文件编码

Step 2 — 收集变量
  2a. 设置 TIMESTAMP（ISO 8601）。
  2b. 合并 Parameters 中与模板同名的标量字段。
  2c. 按序以 UTF-8 读取 CONTEXT_FILES（JSON 解析为对象；Markdown 可由调用方预先结构化到 CONTEXT_JSON）；解码失败 → **中止**。
  2d. 解析 `CONTEXT_JSON`：若为已存在的 `.json` 文件路径则 `read_file` 后解析；否则视为 UTF-8 JSON 字符串并 `json.loads`。非法 JSON → **中止**。
  2e. 扫描模板占位符；STRICT=true 且必填项缺失 → 中止并列出缺失项。
  2f. 若 `OUTPUT` 为 `函数级方案.md`：
      - `CONTEXT_JSON` 不得含 `DOCUMENT_BODY`；契约与骨架见 `whalecloud-dev-tool-function-solution/references/function_solution_context.skeleton.json`
      - 合并 Step 2 变量后，可先 `run_skill_script` 预检：`script_name=fill_function_solution.py`，`args=["--validate-only", "{OUTPUT_DIR}/.tmp/_function_solution_fill_ctx.json"]`（非零 → **中止**）
      - Step 3a 执行 `scripts/fill_function_solution.py` 填充前会再次调用 `validate_context`，契约错误非零退出

Step 3 — 填充模板
  3a. 若 `OUTPUT`（或 `TEMPLATE`）为 `函数级方案.md`（**强制，禁止手填**）：
      - 将 Step 2 合并后的变量对象用 `write_file` 写入 `{OUTPUT_DIR}/.tmp/_function_solution_fill_ctx.json`（内联 `CONTEXT_JSON` 时亦须先落盘供脚本读取）
      - **必须** `run_skill_script`（见上文「共享脚本」）：`fill_function_solution.py` + 模板路径 + ctx.json + `_function_solution_fill_out.md` 三个参数
      - 脚本非零退出或校验失败 → **中止**；**禁止**手填 `{{VAR}}` / `{{#each}}` 或跳过脚本
      - `read_file` 读取 `_function_solution_fill_out.md`，**必须**以 `write_file` 写入 `{OUTPUT_DIR}/{OUTPUT}`（交付物不得仅依赖脚本 `open` 写盘）；可删除 `.tmp` 下临时文件
  3b. 其他模板：读取 `templates/{TEMPLATE}`，按 [references/template-filling.md](references/template-filling.md) 手填（替换 `{{VAR}}`、展开 `{{#each}}`、处理 `{{#if}}`）；`需求澄清.md` 可选用 `scripts/fill_clarify.py`（`run_skill_script`，ctx/out 先写入 `.tmp/`）
  3c. 空列表按规范写「（无）」或保留调用方提供的占位说明（`函数级方案.md` 由脚本处理）。
  3d. 自检：无未解析 `{{` 占位符、无 `{{#each` 残留；`函数级方案.md` 须含模板固定章节与表头（见 template-filling.md）。

Step 4 — 落盘与输出
  4a. 确认 OUTPUT_DIR 可写（write_file 会自动创建父目录）
  4b. **必须**调用 write_file 写入 {OUTPUT_DIR}/{OUTPUT}（见 §C）
  4c. 含中文时用 read_file 执行 §C 写后自检；乱码 → **中止**
  4d. 按 OUTPUT_MODE 决定是否向调用通道输出 Markdown 正文
```

---

## 调用示例

### 示例 1：模块功能文档

```
OUTPUT_DIR: ./requirements/
OUTPUT: 模块功能.md
CONTEXT_JSON: {}
PROD: XXX系统
STATUS: confirmed
OUTPUT_MODE: file
```

### 示例 2：需求澄清文档（仅输出正文）

```
OUTPUT_DIR: ./requirements/
OUTPUT: 需求澄清.md
CONTEXT_JSON: {}
OUTPUT_MODE: content
```

### 示例 3：函数级方案（上游 function-solution 技能调用）

推荐 JSON 文件路径（须含 skeleton 中全部顶层键，见 `function-solution/references/function_solution_context.skeleton.json`）：

```
OUTPUT_DIR: work/21881451/archive/需求设计/func_solution/
OUTPUT: 函数级方案.md
CONTEXT_JSON: work/21881451/archive/需求设计/func_solution/.tmp/function_solution_context.json
PROD: XXX系统
STATUS: draft
OUTPUT_MODE: file
```

**不得**使用 `DOCUMENT_BODY`；内联 JSON 亦须满足完整契约。doc-generate **必须**经 `scripts/fill_function_solution.py`（含 `validate_context`）后 `read_file` + `write_file` 落盘（见 Step 3a）。

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 缺少 OUTPUT_DIR / OUTPUT | **中止**，列出缺失参数 |
| `templates/{TEMPLATE}` 不存在 | **中止**，列出 `templates/` 下可用 `.md` 文件 |
| STRICT=true 且必填占位符缺失 | **中止**，列出缺失变量名 |
| OUTPUT_DIR 不可写 | **中止** |
| CONTEXT_JSON 非法 JSON | **中止**，说明解析错误 |
| 模板 / 上下文 / 输出文件 UTF-8 解码失败 | **中止**，指明路径与环节 |
| 写后自检发现中文乱码 | **中止**，确认是否使用了 `write_file` 后重试 |
| 未使用 `write_file` 写盘 | **中止**，改用 `write_file` 重写 |
| `OUTPUT=函数级方案.md` 未执行 `scripts/fill_function_solution.py` 或手填模板 | **中止**，按 Step 3a 重试 |
| `scripts/fill_function_solution.py` 执行失败或 `CONTEXT_JSON 契约校验失败` | **中止**，对照 skeleton.json 修正键名后重试 |

---

## 输出文件

- 主交付：`{OUTPUT_DIR}/{OUTPUT}` — 填充后的 Markdown 文档。
