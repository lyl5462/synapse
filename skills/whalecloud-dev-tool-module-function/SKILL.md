---
name: whalecloud-dev-tool-module-function
description: "模块功能技能 - 将原始需求按功能拆分，匹配功能架构模块列表，通过源码确认后输出需改造的模块清单。"
label: 模块功能技能
---

# 模块功能技能

将原始需求按功能拆分，匹配功能架构模块列表，通过源码确认后输出需改造的模块清单。

## 共享系统脚本（BASE_SCRIPTS_DIR）

与 SynapseService / GitNexus 交互的脚本位于技能 **`whalecloud-dev-tool-base-scripts`**（与本技能同级目录 `skills/whalecloud-dev-tool-base-scripts/`）。**BASE_SCRIPTS_DIR** 为该技能根目录（系统提示中「研发技能：whalecloud-dev-tool-base-scripts」下的 `**技能路径**:`）。下文凡写 `<BASE_SCRIPTS_DIR>/scripts/...` 均指该路径。

本技能目录下**不再**包含 `get_doc.py`、`get_repo_info.py`、`gnx-tools.js`、`detect-project-kind.js` 等副本；仅保留 `templates/` 与本 SKILL。

---

## Parameters

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `CLARIFY_DOC` | 是 | 需求澄清文档路径（`01-需求澄清.md`），包含范围定义、功能要点、澄清结论等结构化信息 |
| `PROD` | 是 | 产品名称 |
| `SYNAPSE_URL` | 是 | SynapseService 服务地址，如 `192.168.1.100:8080` |
| `GITNEXUS_URL` | 是 | GitNexus 服务地址，如 `http://127.0.0.1:11011` |
| `OUTPUT_DIR` | 否 | 输出目录，默认 `./requirements/` |
| `TMP_DIR` | 否 | 临时文件目录，默认 `{OUTPUT_DIR}/.tmp/`|
| `OUTPUT` | 否 | 输出文件名，默认 `03-模块功能.md` |
| `DEBUG` | 否 | 调试模式开关。如果显式传入 `true`，需将每一步的执行日志输出到调试文件中。默认 `false` |

> **仓库名称**：无需手动传递。技能启动时自动通过 `<BASE_SCRIPTS_DIR>/scripts/get_repo_info.py` 从 SynapseService 获取该产品关联的**所有代码仓库**列表。一个产品通常由多个仓库组合而成（如 `仓库A` + `仓库B`），最终模块功能结果整合所有仓库的源码分析结果。

---

## 核心约束（违反本技能视为未完成）

### A. 技能执行输出限制

**整个技能执行过程中，大模型的输出应遵循以下原则：**

1. **生成文档阶段**：读取模板 `templates/03-模块功能.md`，填充变量后输出 Markdown 格式的文档
2. **调试日志阶段**（仅当 `DEBUG=true` 时）：将每一步的执行日志追加写入调试文件 `{TMP_DIR}/module_function_debug.log`
3. **异常中止时**：可直接输出中止原因和缺失信息，无需走文档模板

### B. 多仓库源码确认（强制约束）

- 产品可能由**多个仓库**组成，每个仓库独立缓存至 `{TMP_DIR}/.gnx-cache/{REPO_NAME}/` 目录。
- 模块识别中凡涉及**文件路径、接口、类名**等结论，须在对应仓库缓存上通过 **`gnx-tools.js search`、`cypher`、`read` 或 `grep`** 至少提供一条可核对证据。
- **跨仓库结论必须分别确认**：对每个仓库独立执行检索操作，并在分析中标注信息来源于哪个仓库。
- 无法通过源码验证的条目必须标注 **`[待代码确认]`**，不得虚构。
- 若某仓库未获取成功，涉及该仓库的分析标注 `[待补充-{REPO_NAME}仓库未获取]`。

### C. 输出范围约束

- 本技能**只输出需改造的模块清单**，不涉及具体改造方案、改造内容或实现细节
- 输出的模块名称必须与 `FUNCTIONAL_ARCH.md` 中的模块名称保持一致
- 超出功能架构模块列表的改造范围，标识为新增模块

### D. 功能架构指导性约束

- `FUNCTIONAL_ARCH.md` 是**指导性文档，不一定完全正确**，必须通过源码确认其准确性
- 需求拆分后的功能点先按功能架构模块列表匹配，再通过源码确认匹配结果是否合理
- 源码确认可能发现功能架构描述与实际代码不一致的情况，此时以源码为准
- 每个修改模块都必须经过源码确认
- 每个新增模块需确认功能架构中确实没有可覆盖的模块

---

## 工作流程

```
Step 0 — 参数校验与环境准备
  0a. 校验必填参数：CLARIFY_DOC, PROD, SYNAPSE_URL, GITNEXUS_URL
  0b. 确认 <BASE_SCRIPTS_DIR>/scripts/get_repo_info.py、<BASE_SCRIPTS_DIR>/scripts/get_doc.py、<BASE_SCRIPTS_DIR>/scripts/gnx-tools.js 存在且可执行。
  0c. Python 命令适配：优先使用 `python3`，若不可用则尝试 `py`（Windows），均不可用则尝试 `python`。以下用 `{PYTHON}` 指代实际可用的 Python 命令。
  0d. 自动获取产品关联的所有仓库：
        → {PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_repo_info.py --server-url={SYNAPSE_URL} --prod={PROD}
      解析输出 "产品：XXX 一共有N个仓库：REPO1,REPO2"，提取所有仓库名列表，记为 GNX_REPO_LIST。
      若输出包含 "未找到仓库信息" 则**中止**并提示：该产品未关联代码仓库，请检查 PROD 参数。
  0e. 创建输出目录和临时目录（若不存在）：
        → mkdir -p {OUTPUT_DIR} {TMP_DIR} {TMP_DIR}/docs
        → 为每个仓库创建独立缓存目录：mkdir -p {TMP_DIR}/.gnx-cache/{REPO_NAME}
  0f. *(DEBUG)* 若 DEBUG=true，创建调试文件 {TMP_DIR}/module_function_debug.log，并将参数校验结果、Python 命令适配结果、GNX_REPO_LIST 写入调试日志

Step 1 — 获取项目资料（已存在则跳过）
  1a. 使用 get_doc.py 获取功能架构文档，保存到 {TMP_DIR}/docs/：
      若 {TMP_DIR}/docs/ 下已存在 FUNCTIONAL_ARCH 相关文件 → 跳过，直接读取已有文件
      否则执行：
        {PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_doc.py --doc_type=产品架构 --server_url {SYNAPSE_URL} --prod {PROD} --doc_name=FUNCTIONAL_ARCH --output {TMP_DIR}/docs
      若获取失败且无已有文件则**中止**（功能架构是本技能的核心输入）
  1b. 使用 get_doc.py 获取技术架构文档（补充参考），保存到 {TMP_DIR}/docs/：
      若 {TMP_DIR}/docs/ 下已存在 TECH_ARCH 相关文件 → 跳过，直接读取已有文件
      否则执行：
        {PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_doc.py --doc_type=产品架构 --server_url {SYNAPSE_URL} --prod {PROD} --doc_name=TECH_ARCH --output {TMP_DIR}/docs
      若获取失败且无已有文件则继续执行，仅以 FUNCTIONAL_ARCH.md 为准
  1c. 使用 gnx-tools.js materialize 下载源码到本地缓存（遍历 GNX_REPO_LIST）：
      对每个仓库：若 {TMP_DIR}/.gnx-cache/{REPO_NAME}/files/ 目录已存在且非空 → 跳过，复用已有缓存
      否则执行：
        node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js materialize --url {GITNEXUS_URL} --repo {REPO_NAME} --cache {TMP_DIR}/.gnx-cache/{REPO_NAME}
      任一仓库 materialize 失败：记录该仓库为「未能获取」，继续处理其余仓库。
      **仅当所有仓库均 materialize 失败（且无已有缓存）时才中止。**
  1d. 使用 gnx-tools.js overview 获取项目概览（遍历 GNX_REPO_LIST）：
      对每个仓库：若 {TMP_DIR}/.gnx-cache/{REPO_NAME}/overview.json 已存在且非空 → 跳过，直接读取
      否则执行：
        node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js overview --url {GITNEXUS_URL} --repo {REPO_NAME} --out {TMP_DIR}/.gnx-cache/{REPO_NAME}/overview.json
  1e. *(DEBUG)* 若 DEBUG=true，将 get_doc.py 和 gnx-tools.js 的调用命令、返回状态、overview.json 关键内容写入调试日志

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

Step 3 — 功能点匹配与源码确认
  对 FEATURE_POINTS 中的每个功能点，依次执行以下匹配流程：

  3a. **匹配功能模块**：将该功能点与 ARCH_MODULE_LIST 中的模块逐一比对，找到最匹配的功能模块
      - 匹配依据：功能描述的语义相似度、业务领域归属、CLARIFY_DOC 中的范围定义和约束与依赖
      - 一个功能点可能匹配到多个功能模块（如前台页面+后台服务都需改造）
      - 若无法匹配到任何已有模块 → 标记为"未匹配"，进入 **3d** 处理

  3b. **源码确认**（对每个匹配到的功能模块）：
      功能架构是指导性文档，必须通过源码确认匹配结论是否准确：
      - 使用 gnx-tools.js search 搜索模块关键类名/接口名（遍历 GNX_REPO_LIST）：
          node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js search --url {GITNEXUS_URL} --repo {REPO_NAME} --query "模块关键类名"
      - 使用 gnx-tools.js grep 搜索模块相关的业务逻辑代码（遍历 GNX_REPO_LIST）：
          node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js grep --cache {TMP_DIR}/.gnx-cache/{REPO_NAME} --pattern "关键类名/接口名"
      - 使用 gnx-tools.js read 读取模块核心代码文件
      - **识别核心类**：从搜索结果中提取该模块的核心类（Controller/Service/DAO/Model 等关键类），记录类名和文件路径

  3c. **确认结论**（以源码为准）：
      - 源码确认该模块确实存在且需要改造 → 确定为**修改模块**，记录核心类列表
      - 源码发现功能架构描述与实际代码不一致 → 以源码为准，调整匹配结论和核心类
      - 源码确认该模块已能覆盖需求 → 从修改列表中排除
      - 源码无法验证 → 标注 [待代码确认]

  3d. **新增模块判定**（对 3a 中"未匹配"的功能点）：
      - 若功能点无法匹配到 ARCH_MODULE_LIST 中的任何已有模块
      - 或匹配到的模块经源码确认后，发现功能范围差异过大、不适合在该模块内改造
      - 则标识为**新增模块**，说明新增原因，并通过源码检索识别核心类

  3e. *(DEBUG)* 若 DEBUG=true，将每个功能点的匹配过程（匹配到哪个模块/未匹配）、源码确认的调用命令和返回结果、确认结论（修改/无需改造/新增/待确认）写入调试日志

Step 4 — 生成模块功能文档
  4a. 汇总：需改造的模块清单（修改模块+新增模块）
  4b. 读取模板 templates/03-模块功能.md
  4c. 填充模板变量
  4d. 写入输出文件 {OUTPUT_DIR}/{OUTPUT}
  （不清理 .gnx-cache 目录，以便后续执行时复用缓存跳过下载）
```

---

## 使用脚本说明

> **平台兼容**：所有 Python 脚本优先使用 `python3`，若不可用则尝试 `py`（Windows）或 `python`。

| 脚本 | 用途 | 详细文档 |
|------|------|----------|
| `<BASE_SCRIPTS_DIR>/scripts/get_repo_info.py` | 获取产品关联的代码仓库列表 | [../whalecloud-dev-tool-base-scripts/references/get_repo_info_readme.md](../whalecloud-dev-tool-base-scripts/references/get_repo_info_readme.md) |
| `<BASE_SCRIPTS_DIR>/scripts/get_doc.py` | 从 SynapseService 下载产品文档 | [../whalecloud-dev-tool-base-scripts/references/get_doc_readme.md](../whalecloud-dev-tool-base-scripts/references/get_doc_readme.md) |
| `<BASE_SCRIPTS_DIR>/scripts/gnx-tools.js` | 与 GitNexus 交互（下载/检索/查询） | [../whalecloud-dev-tool-base-scripts/references/README-GNX-TOOLS.md](../whalecloud-dev-tool-base-scripts/references/README-GNX-TOOLS.md) |
| `<BASE_SCRIPTS_DIR>/scripts/detect-project-kind.js` | 检测项目工程类型（语言栈、构建体系） | [../whalecloud-dev-tool-base-scripts/references/README-GNX-TOOLS.md](../whalecloud-dev-tool-base-scripts/references/README-GNX-TOOLS.md) |

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 缺少必填参数（CLARIFY_DOC/PROD/SYNAPSE_URL/GITNEXUS_URL） | **中止**，列出缺失参数 |
| get_repo_info.py 返回 "未找到仓库信息" | **中止**，提示该产品未关联代码仓库 |
| FUNCTIONAL_ARCH.md 获取失败 | **中止**，功能架构是本技能的核心输入 |
| GITNEXUS_URL 不可达或**所有仓库** materialize 均失败 | **中止**，不得输出无源码确认的模块识别结果 |
| 部分仓库 materialize 失败 | 记录失败仓库名，后续检索跳过该仓库，涉及该仓库的分析标注 `[待补充-{REPO_NAME}仓库未获取]`，继续处理其他仓库 |
| TECH_ARCH.md 获取失败 | 继续执行，仅以 FUNCTIONAL_ARCH.md 为准 |
| 某仓库 search/cypher/grep 无结果 | 记录该仓库无匹配结果，继续分析其他仓库 |
| 缓存中无某文件路径 | 标 `[待代码确认]`，不得虚构内容 |
| OUTPUT_DIR 不可写 | 中止并说明 |

---

## 输出文件

- 模块功能文档：`{OUTPUT_DIR}/{OUTPUT}`，格式参考 `templates/03-模块功能.md`

---

## 完整示例

### 示例调用

```
CLARIFY_DOC: ./requirements/01-需求澄清.md,
PROD: XXX系统,
SYNAPSE_URL: 192.168.1.100:8080,
GITNEXUS_URL: http://127.0.0.1:11011,
OUTPUT_DIR: ./requirements/,
OUTPUT: 03-模块功能.md,
DEBUG: false
```