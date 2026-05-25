---
name: whalecloud-dev-tool-module-function
description: "模块功能技能 - 将原始需求按功能拆分，匹配功能架构模块列表，基于产品知识体系事实确认后输出需改造的模块清单和涉及的核心类列表。"
label: 模块功能技能
---

# 模块功能技能

将原始需求按功能拆分，匹配功能架构模块列表，严格依赖产品知识体系事实（代码、文档、需求澄清文档）确认后输出需改造的模块清单。**严禁臆断想象**，所有结论必须有实际存在的内容作为依据。

## 共享系统脚本（BASE_SCRIPTS_DIR）

与 SynapseService 交互的脚本位于技能 **`whalecloud-dev-tool-base-scripts`**（与本技能同级目录 `skills/whalecloud-dev-tool-base-scripts/`）。**BASE_SCRIPTS_DIR** 为该技能根目录（系统提示中「研发技能：whalecloud-dev-tool-base-scripts」下的 `**技能路径**:`）。下文凡写 `<BASE_SCRIPTS_DIR>/scripts/...` 均指该路径。

## 研发会议室：工单目录读代码 / 文档（优先）

在研发会议室中，`room_opened` 已将产品资产落盘到工单目录。**凡需读取代码或产品文档，必须优先使用下列路径，禁止臆造目录，也不要重复调用 `get_doc.py` 拉取已在工单目录中的文档。**

| 用途 | 路径约定 | 说明 |
|------|----------|------|
| 工单根目录 | `{WORK_ORDER_DIR}` | 系统提示「产品工作区路径」或委派参数，形如 `work/<scope_id>/` |
| 产品代码 | `{PRODUCT_CODE_ROOT}/<repo_name>/` | 默认 `{WORK_ORDER_DIR}/code/<repo_name>/` |
| 产品文档 | `{PRODUCT_DOC_ROOT}/<doc_type>/` | 默认 `{WORK_ORDER_DIR}/doc/<doc_type>/`；架构文档在 `产品架构/` |

- **FUNCTIONAL_ARCH / TECH_ARCH**：优先读 `{PRODUCT_DOC_ROOT}/产品架构/`
- **代码确认**（Step 3）：在 `{PRODUCT_CODE_ROOT}` 各仓库目录内检索，路径标注为 `<repo_name>/相对路径`

---

## Parameters

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `CLARIFY_DOC` | 是 | 需求澄清文档路径（通常为工单 `archive/` 下 `需求澄清.md`），须为可读绝对/相对路径 |
| `PROD` | 是 | 产品名称 |
| `WORK_ORDER_DIR` | 否 | 工单工作目录（研发会议室注入），如 `work/21881451`。提供时**必须**从此目录读代码/文档 |
| `PRODUCT_CODE_ROOT` | 否 | 产品代码根目录，默认 `{WORK_ORDER_DIR}/code` |
| `PRODUCT_DOC_ROOT` | 否 | 产品文档根目录，默认 `{WORK_ORDER_DIR}/doc` |
| `SYNAPSE_URL` | 否 | SynapseService 地址。仅当工单目录无架构文档时，用于 `get_doc.py` 回退 |
| `TMP_DIR` | 否 | 临时目录（回退下载用），默认 `./.tmp/`，其下 `docs/` |
| `DEBUG` | 否 | 调试模式开关。如果显式传入 `true`，需将每一步的执行日志输出到调试文件中。默认 `false` |

> **知识来源**：分析仅以实际存在的内容为依据，包括：代码（项目文件）、文档（FUNCTIONAL_ARCH、TECH_ARCH）、需求澄清文档（CLARIFY_DOC）。任何无法从上述来源验证的结论必须标注 `[待确认]`，严禁臆断想象。

---

## 核心约束（违反本技能视为未完成）

### A. 技能执行输出限制

**整个技能执行过程中，大模型的输出应遵循以下原则：**

1. **生成文档阶段**：按照下方「输出内容格式」章节的结构，直接输出 Markdown 格式的文档
2. **调试日志阶段**（仅当 `DEBUG=true` 时）：将每一步的执行日志写入调试文件 `{TMP_DIR}/module_function_debug.log`
3. **异常中止时**：可直接输出中止原因和缺失信息，无需走文档格式

### B. 产品知识体系事实依赖（强制约束）

- 模块识别**必须严格依赖**以下三类事实来源，不得凭空臆断或想象：
  | 事实来源 | 说明 |
  |---------|------|
  | **需求澄清文档** | `CLARIFY_DOC`（01-需求澄清.md）— 包含范围定义、功能要点、澄清结论、约束与依赖 |
  | **文档** | 优先 `{PRODUCT_DOC_ROOT}/产品架构/`（FUNCTIONAL_ARCH、TECH_ARCH）；否则 SynapseService / `{TMP_DIR}/docs/` |
  | **代码** | 优先 `{PRODUCT_CODE_ROOT}/<repo_name>/`；通过文件系统或检索工具读取，禁止臆造路径 |
- 模块识别中凡涉及**文件路径、接口、类名**等结论，必须在代码或文档中有对应支撑依据，并标注来源。
- 无法通过上述事实来源验证的条目必须标注 **`[待确认]`**，不得虚构。
- 若某文档源未获取成功，涉及该文档的分析标注 `[待补充-文档未获取]`。

### C. 输出范围约束

- 本技能**只输出需改造的模块清单**，不涉及具体改造方案、改造内容或实现细节
- 输出的模块名称必须与 `FUNCTIONAL_ARCH.md` 中的模块名称保持一致
- 超出功能架构模块列表的改造范围，标识为新增模块

### D. 事实驱动的模块确认（强制约束）

- `FUNCTIONAL_ARCH.md` 是**指导性文档，不一定完全正确**，必须通过实际代码确认其准确性
- 需求拆分后的功能点先按功能架构模块列表匹配，再通过代码确认匹配结果是否合理
- 代码确认可能发现功能架构描述与实际代码不一致的情况，此时以代码为准
- 每个修改模块都必须经过代码确认
- 每个新增模块需确认功能架构中确实没有可覆盖的模块
- 所有确认结论必须有具体的文件路径或文档引用作为依据

---

## 工作流程

```
Step 0 — 参数校验与环境准备
  0a. 校验必填参数：CLARIFY_DOC, PROD
  0b. Python 命令适配：优先使用 `python3`，若不可用则尝试 `py`（Windows），均不可用则尝试 `python`。以下用 `{PYTHON}` 指代实际可用的 Python 命令。
  0c. **解析工单目录**（研发会议室优先）：
        - 若提供 `WORK_ORDER_DIR`：`CODE_ROOT = PRODUCT_CODE_ROOT`（缺省 `{WORK_ORDER_DIR}/code`），`DOC_ROOT = PRODUCT_DOC_ROOT`（缺省 `{WORK_ORDER_DIR}/doc`）
        - 否则：`DOC_ROOT` 回退 `{TMP_DIR}/docs`，`mkdir -p {TMP_DIR} {TMP_DIR}/docs`
  0d. *(DEBUG)* 若 DEBUG=true，创建调试文件 `{TMP_DIR}/module_function_debug.log`（或 `{WORK_ORDER_DIR}/module_function_debug.log`），写入参数与目录解析结果

Step 1 — 获取项目资料（已存在则跳过）
  1a. 读取 CLARIFY_DOC，验证文档存在且可读，若不存在则**中止**
  1b. **功能架构文档**（优先 `{DOC_ROOT}/产品架构/`，禁止重复下载）：
      若该目录下已有 FUNCTIONAL_ARCH 相关 `.md` → 直接读取
      否则且 `SYNAPSE_URL` 已提供 →
        `{PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_doc.py --doc_type=产品架构 --server_url {SYNAPSE_URL} --prod {PROD} --doc_name=FUNCTIONAL_ARCH --output {DOC_ROOT}/产品架构`
      若获取失败且无已有文件则**中止**
      若既无工单目录文档又无 `SYNAPSE_URL`，需人工提供 FUNCTIONAL_ARCH.md 路径
  1c. **技术架构文档**（补充，同 1b 优先读 `{DOC_ROOT}/产品架构/`）：
      已有 TECH_ARCH 相关文件 → 跳过下载
      否则且 `SYNAPSE_URL` 已提供 → get_doc 输出到 `{DOC_ROOT}/产品架构`
      失败则继续，仅以 FUNCTIONAL_ARCH 为准
  1d. *(DEBUG)* 若 DEBUG=true，记录文档来源路径（工单目录 vs get_doc 回退）及命令状态

Step 2 — 提取功能模块列表与需求拆分
  2a. 读取 FUNCTIONAL_ARCH.md，提取"核心功能详解"章节中的**功能模块列表**（每个模块的名称、功能描述、涉及的源代码文件），记为 ARCH_MODULE_LIST
  2b. 读取 CLARIFY_DOC（需求澄清文档），提取以下结构化信息：
      - **范围定义**：IN（涉及范围）和 OUT（排除范围）
      - **功能要点**：需求涉及的功能点列表
      - **澄清结论**：关键确认点的总结
      - **约束与依赖**：模块依赖、技术约束、数据依赖
  2c. 将功能要点与 ARCH_MODULE_LIST 的划分粒度对齐，形成最终的 FEATURE_POINTS：
      - 若功能要点按页面粒度划分（如"前台页面-用户管理页面"），保持页面级别
      - 若功能要点按服务粒度划分（如"后台服务-用户管理"），保持服务级别
      - 若功能要点粒度与 ARCH_MODULE_LIST 不对齐，按 ARCH_MODULE_LIST 的粒度重新拆分
      - OUT 范围内的功能点排除，不纳入 FEATURE_POINTS
  2d. *(DEBUG)* 若 DEBUG=true，将 ARCH_MODULE_LIST（模块名称+描述+源代码文件）、CLARIFY_DOC 提取的结构化信息、FEATURE_POINTS（功能点列表+拆分推理）写入调试日志

Step 3 — 功能点匹配与代码确认
  对 FEATURE_POINTS 中的每个功能点，依次执行以下匹配流程：

  3a. **匹配功能模块**：将该功能点与 ARCH_MODULE_LIST 中的模块逐一比对，找到最匹配的功能模块
      - 匹配依据：功能描述的语义相似度、业务领域归属、CLARIFY_DOC 中的范围定义和约束与依赖
      - 一个功能点可能匹配到多个功能模块（如前台页面+后台服务都需改造）
      - 若无法匹配到任何已有模块 → 标记为"未匹配"，进入 **3d** 处理

  3b. **代码确认**（对每个匹配到的功能模块）：
      功能架构是指导性文档，必须通过实际代码确认匹配结论是否准确：
      - 在 `{PRODUCT_CODE_ROOT}`（或 `{WORK_ORDER_DIR}/code`）下各 `<repo_name>/` 目录中搜索模块关键类名/接口名
      - 在关键模块路径下搜索相关业务逻辑代码
      - 读取模块核心代码文件（路径格式：`<repo_name>/相对路径`）
      - **识别核心类**：从搜索结果中提取该模块的核心类（Controller/Service/DAO/Model 等），记录类名与**工单代码目录内**文件路径

  3c. **确认结论**（以代码为准）：
      - 代码确认该模块确实存在且需要改造 → 确定为**修改模块**，记录核心类列表和来源路径
      - 代码发现功能架构描述与实际代码不一致 → 以代码为准，调整匹配结论和核心类
      - 代码确认该模块已能覆盖需求 → 从修改列表中排除
      - 代码无法验证 → 标注 `[待确认]`

  3d. **新增模块判定**（对 3a 中"未匹配"的功能点）：
      - 若功能点无法匹配到 ARCH_MODULE_LIST 中的任何已有模块
      - 或匹配到的模块经代码确认后，发现功能范围差异过大、不适合在该模块内改造
      - 则标识为**新增模块**，说明新增原因，并通过代码检索识别核心类

  3e. *(DEBUG)* 若 DEBUG=true，将每个功能点的匹配过程（匹配到哪个模块/未匹配）、代码确认的检索结果、确认结论（修改/无需改造/新增/待确认）写入调试日志

Step 4 — 生成模块功能文档
  4a. 汇总：需改造的模块清单（修改模块+新增模块）
  4b. 按照「输出内容格式」章节的结构，直接输出 Markdown 格式的文档
```

---

## 使用脚本说明

> **平台兼容**：所有 Python 脚本优先使用 `python3`，若不可用则尝试 `py`（Windows）或 `python`。

| 脚本 | 用途 | 详细文档 |
|------|------|----------|
| `<BASE_SCRIPTS_DIR>/scripts/get_doc.py` | **回退**：工单目录无文档时从 SynapseService 下载 | [../whalecloud-dev-tool-base-scripts/references/get_doc_readme.md](../whalecloud-dev-tool-base-scripts/references/get_doc_readme.md) |

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 缺少必填参数（CLARIFY_DOC/PROD） | **中止**，列出缺失参数 |
| CLARIFY_DOC 文件不存在 | **中止**，提示需求澄清文档路径无效 |
| 工单目录与 get_doc 均无 FUNCTIONAL_ARCH | **中止**，功能架构是本技能的核心输入 |
| SYNAPSE_URL 未提供且工单目录 / 本地均无 FUNCTIONAL_ARCH | **中止**，提示需提供路径或 SYNAPSE_URL |
| TECH_ARCH.md 获取失败 | 继续执行，仅以 FUNCTIONAL_ARCH.md 为准 |
| 代码检索无结果 | 标注 `[待确认]`，不得虚构内容 |

---

## 输出内容格式

模块功能文档按以下结构直接输出 Markdown：

```markdown
# 模块功能

> **生成时间**: {当前时间}
> **需求名称**: {需求名称}
> **状态**: {状态}

---

## 原始需求

{DEMAND_DESC}

---

## 需求功能拆分

| # | 功能点 | 说明 |
|---|--------|------|
{逐个列出功能点}
| {序号} | {功能点名称} | {功能点说明} |

---

## 修改模块

> 以下模块来自功能架构文档，经代码确认后确定需要改造。

| # | 功能模块名称 | 对应功能点 | 核心类 | 确认依据 |
|---|-------------|----------|--------|---------|
{逐个列出修改模块}
| {序号} | {模块名称} | {对应功能点} | {核心类列表} | {确认依据} |

## 新增模块

> 以下功能点超出功能架构模块列表范围，需新增模块。

| # | 模块名称 | 对应功能点 | 核心类 | 新增原因 | 确认依据 |
|---|---------|----------|--------|---------|---------|
{逐个列出新增模块}
| {序号} | {模块名称} | {对应功能点} | {核心类列表} | {新增原因} | {确认依据} |
```

---

## 完整示例

### 示例调用

```
CLARIFY_DOC: ./requirements/01-需求澄清.md,
PROD: XXX系统,
SYNAPSE_URL: 192.168.1.100:8080,
DEBUG: false
```