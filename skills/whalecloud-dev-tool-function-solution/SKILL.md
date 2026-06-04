---
name: whalecloud-dev-tool-function-solution
description: "函数级方案技能 - 将上游模块级改造需求下钻到函数级别，输出结构化伪代码与数据设计，严格依赖产品知识体系事实确认函数存在性和签名一致性；交付物通过 whalecloud-dev-tool-doc-generate 落盘为 函数级方案.md。"
label: 函数级方案技能
---

# 函数级方案技能

将上游模块级改造需求下钻到函数级别，输出结构化伪代码与数据设计，严格依赖产品知识体系事实（代码、文档）确认函数存在性和签名一致性。**严禁臆断想象**，所有结论必须有实际存在的内容作为依据。

**文档落地**：分析完成后，**必须**调用 [`whalecloud-dev-tool-doc-generate`](../whalecloud-dev-tool-doc-generate/SKILL.md) 将方案写入 `{ARCHIVE_DIR}/函数级方案.md`，不得绕过该技能直接写盘。

---

## Parameters

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `WORK_ORDER_DIR` | 是 | 工单工作目录（研发会议室注入），如 `work/21881451`。所有上游文档的固定推导路径如下：<br>`CLARIFY_DOC` = `{WORK_ORDER_DIR}/archive/需求分析/req_clarify/需求澄清.md`<br>`MODULE_DOC` = `{WORK_ORDER_DIR}/archive/需求分析/module_func/功能模块.md`<br>`BOUNDARY_DOC` = `{WORK_ORDER_DIR}/archive/需求分析/boundary/边界确认说明.md`<br>`ACCEPTANCE_DOC` = `{WORK_ORDER_DIR}/archive/需求分析/acceptance/验收标准.md`<br>`RISK_DOC` = `{WORK_ORDER_DIR}/archive/需求分析/req_risk/需求风险评估.md` |
| `PRODUCT_CODE_ROOT` | 是 | 产品代码根目录，如 `work/21881451/code`。用于代码检索和确认，支撑 Step 5 代码确认环节。 |
| `PRODUCT_DOC_ROOT` | 是 | 产品文档根目录。功能架构和技术架构文档的固定路径如下：<br>`FUNC_ARCH_DOC` = `{PRODUCT_DOC_ROOT}/产品架构/FUNCTIONAL_ARCH.md`<br>`TECH_ARCH_DOC` = `{PRODUCT_DOC_ROOT}/产品架构/TECH_ARCH.md` |
| `REPO_INFO` | 是 | 产品涉及的所有仓库信息列表，格式为：`应用模块`、`产品分支ID`、`产品分支`、`仓库地址`。示例：`- 应用模块：ZMDB - 产品分支ID: 4531 - 产品分支: CBOSS_BSS_ZMDB_V9.0_主分支 - 仓库地址: https://git-nj.iwhalecloud.com/xmjfbss/ZMDB.git`。从中抽取本次改造涉及的所有仓库，提取**产品分支ID**和**仓库地址**（可能有多组）。 |
| `ARCHIVE_DIR` | 否 | 方案输出目录。默认由 `WORK_ORDER_DIR` 推导：`{WORK_ORDER_DIR}/archive/需求设计/func_solution/`。若显式传入则使用传入值。输出为单一文件：`{ARCHIVE_DIR}/函数级方案.md` |

> **知识来源**：分析仅以实际存在的内容为依据，包括：代码（项目文件）、文档（CLARIFY_DOC、MODULE_DOC、BOUNDARY_DOC、ACCEPTANCE_DOC、RISK_DOC 由 `WORK_ORDER_DIR` 推导；FUNC_ARCH_DOC、TECH_ARCH_DOC 由 `PRODUCT_DOC_ROOT` 推导）。任何无法通过上述来源验证的结论必须标注 `[待确认]`，严禁臆断想象。

---

## 核心约束（违反本技能视为未完成）

### A. 技能执行输出限制

**整个技能执行过程中，大模型的输出应遵循以下原则：**

1. **输出阶段**：按下方「CONTEXT_JSON 字段契约」组装结构化 JSON，**必须**通过 `whalecloud-dev-tool-doc-generate` 落盘为 `{ARCHIVE_DIR}/函数级方案.md`（见 Step 10）；本技能不得直接使用 `write_file` 写交付物
2. **异常中止时**：可直接输出中止原因和缺失信息

### B. 产品知识体系事实依赖（强制约束）

- 函数设计**必须严格依赖**以下事实来源，不得凭空臆断或想象：
  | 事实来源 | 说明 |
  |---------|------|
  | **上游文档** | CLARIFY_DOC、MODULE_DOC、BOUNDARY_DOC、ACCEPTANCE_DOC、RISK_DOC（由 `WORK_ORDER_DIR` 推导）、FUNC_ARCH_DOC 和 TECH_ARCH_DOC（由 `PRODUCT_DOC_ROOT` 推导）— 从上游技能输出或本地路径读取 |
  | **代码** | 项目的实际代码文件 — 通过文件系统直接读取或检索工具获取 |
- 修改类函数**必须**通过代码确认其存在性和签名一致性
- 新增类函数**必须**确认不与已有函数冲突（同名/同签名检查）
- 删除类函数**必须**确认代码中确实存在该函数
- 函数设计中凡涉及**类名、函数签名、文件路径**等结论，必须在代码或文档中有对应支撑依据，并标注来源
- 无法通过上述事实来源验证的条目必须标注 **`[待确认]`**，不得虚构
- 每个函数的代码确认结果必须记录到附录 2.1 代码确认记录（`code_confirmations` 列表）
- 若某文档源未获取成功，涉及该文档的分析标注 `[待补充-文档未获取]`

### C. 单文件输出与文档落地约束

- **落盘方式（强制）**：交付物**仅**通过 `whalecloud-dev-tool-doc-generate` 写入；执行前**必须先 Read** 该技能 `SKILL.md` 并严格遵循其 UTF-8 / `write_file` / 写后自检要求
- **输出文件**：固定为 `{ARCHIVE_DIR}/函数级方案.md`，`OUTPUT` 须与模板 `templates/函数级方案.md` 文件名一致，不得按模块拆分为多个文件
- **模板格式一致（强制）**：doc-generate 须以 `templates/函数级方案.md` 为版式源，**必须**经 `scripts/fill_function_solution.py`（`run_skill_script`）填充后落盘；**禁止**手填占位符、手写 `## 1.` / `## 2.` 正文、增删章节标题、改表格列名或使用 `DOCUMENT_BODY`
- **模块组织方式**：以 FUNC_ARCH_DOC 中定义的**核心功能模块**（修改模块+新增模块）为逻辑单元，在 **§1.7 模块改造方案** 一章内按模块分小节输出（如 `#### 1.7.1 {模块名称}`、`#### 1.7.2 {模块名称}`），各模块的函数设计清单、伪代码、模块内部调用关系均归入对应小节
- §1.6 数据设计、§1.8 跨模块交互设计 为**全量**内容，不按模块拆文件，可在各条目下标注所属模块

### D. 上游数据驱动约束

- 函数清单**必须覆盖** MODULE_DOC 中的所有修改模块和新增模块
- 每个模块的函数设计必须与 FUNC_ARCH_DOC 中该模块的功能描述一致
- 伪代码中的技术选型（语言、框架、调用方式）必须与 TECH_ARCH_DOC 中记录的技术栈一致
- 数据设计必须满足 CLARIFY_DOC 中的约束与依赖

### E. 伪代码规范约束

- 伪代码采用**结构化伪代码**格式：包含关键逻辑分支（if/else）、循环、异常处理、核心数据结构操作
- 伪代码中**必须标注**与其他函数/模块的交互点（调用关系、数据依赖）
- 伪代码不写具体业务算法实现细节，侧重**设计意图和逻辑结构**
- 每个函数伪代码后必须附**调用关系**（上游调用、下游调用、数据依赖）

### F. 输出范围约束

- 本技能**只输出函数级方案**，不涉及具体编码实现
- 数据设计范围限于：结构体/DTO/VO定义、数据库表变更、消息/接口契约、枚举与常量
- 不输出：部署方案、运维方案、性能调优方案

---

## 工作流程

```
Step 0 — 参数校验与环境准备
  0a. 校验必填参数：WORK_ORDER_DIR, PRODUCT_CODE_ROOT, PRODUCT_DOC_ROOT, REPO_INFO
      - 推导文档路径：
        CLARIFY_DOC = `{WORK_ORDER_DIR}/archive/需求分析/req_clarify/需求澄清.md`
        MODULE_DOC = `{WORK_ORDER_DIR}/archive/需求分析/module_func/功能模块.md`
        BOUNDARY_DOC = `{WORK_ORDER_DIR}/archive/需求分析/boundary/边界确认说明.md`
        ACCEPTANCE_DOC = `{WORK_ORDER_DIR}/archive/需求分析/acceptance/验收标准.md`
        RISK_DOC = `{WORK_ORDER_DIR}/archive/需求分析/req_risk/需求风险评估.md`
        FUNC_ARCH_DOC = `{PRODUCT_DOC_ROOT}/产品架构/FUNCTIONAL_ARCH.md`
        TECH_ARCH_DOC = `{PRODUCT_DOC_ROOT}/产品架构/TECH_ARCH.md`
      - 解析 REPO_INFO：解析产品涉及的所有仓库信息，提取**产品分支ID**和**仓库地址**（可能有多组），记为 REPO_DATA
      - 推导输出路径：
        若未显式传入 ARCHIVE_DIR，则默认值为 `{WORK_ORDER_DIR}/archive/需求设计/func_solution/`
        输出文件固定为：`{ARCHIVE_DIR}/函数级方案.md`（由 Step 10 经 doc-generate 落盘）
      - 可选：创建 `{ARCHIVE_DIR}/.tmp/` 存放 `function_solution_context.json`
      - Step 10 组装 `ctx` 时**以** `skills/whalecloud-dev-tool-function-solution/references/function_solution_context.skeleton.json` **为骨架**（复制全部键后再填入分析结果）

Step 1 — 验证上游输入物可读性
  1a. 验证 CLARIFY_DOC、MODULE_DOC（由 WORK_ORDER_DIR 推导）文件存在且可读，若任一不存在则**中止**
  1b. 验证 FUNC_ARCH_DOC、TECH_ARCH_DOC（由 PRODUCT_DOC_ROOT 推导）文件存在且可读，若任一不存在则标注 `[待补充]` 后继续执行

Step 2 — 解析上游输入物
  2a. 读取 CLARIFY_DOC（需求澄清文档，路径由 WORK_ORDER_DIR 推导），提取：
      - 范围定义：IN（涉及范围）和 OUT（排除范围）
      - 功能要点列表
      - 约束与依赖：技术约束、模块依赖、数据依赖
      记为 CLARIFY_DATA
  2b. 读取 MODULE_DOC（模块功能文档，路径由 WORK_ORDER_DIR 推导），提取：
      - 需求功能拆分：功能点列表
      - 修改模块列表：模块名称 + 对应功能点 + 确认依据
      - 新增模块列表：模块名称 + 对应功能点 + 新增原因
      记为 MODULE_DATA
  2c. 读取 FUNC_ARCH_DOC（功能架构文档，路径由 PRODUCT_DOC_ROOT 推导），提取：
      - 核心功能详解：每个功能的说明、关键入口（类/方法）、代码影响范围（文件级别）
      - 业务能力矩阵
      - 使用场景与交互流程
      记为 FUNC_ARCH_DATA
  2d. 读取 TECH_ARCH_DOC（技术架构文档，路径由 PRODUCT_DOC_ROOT 推导），提取：
      - 技术栈：语言、框架、关键依赖
      - 系统分层架构：各层职责、包含模块、承载核心功能
      - 运行形态与执行流：进程、启动链、核心执行流
      - 模块依赖关系
      - 编译期约束（#ifdef 等）
      记为 TECH_ARCH_DATA
  2e. *(可选)* 读取 ACCEPTANCE_DOC（验收标准文档，路径由 WORK_ORDER_DIR 推导），提取：
      - 每个模块的验收条件列表
      - 验收方式与工具
      记为 ACCEPTANCE_DATA（可能为空）
  2f. *(可选)* 读取 BOUNDARY_DOC（边界确认文档，路径由 WORK_ORDER_DIR 推导），提取：
      - 功能边界（涉及/不涉及）
      - 技术边界（涉及/不涉及）
      记为 BOUNDARY_DATA（可能为空）
  2g. *(可选)* 读取 RISK_DOC（需求风险文档，路径由 WORK_ORDER_DIR 推导），提取：
      - 风险清单：等级、类型、说明、影响范围、应对措施
      记为 RISK_DATA（可能为空）

Step 3 — 数据设计
  对 MODULE_DATA 中的每个模块（修改模块+新增模块），结合 FUNC_ARCH_DATA 和 TECH_ARCH_DATA：

  3a. **识别数据需求**：
      - 分析模块涉及的功能点，确定需要哪些数据结构（DTO/VO/实体类）
      - 分析 CLARIFY_DATA 中的数据依赖，确定数据流向和格式
      - 分析 FUNC_ARCH_DATA 中的交互流程，确定跨模块数据交换格式

  3b. **数据结构定义**（新增/修改的结构体、DTO、VO）：
      - 对修改模块：比对 FUNC_ARCH_DATA 中该模块的代码影响范围，识别已有数据结构
      - 对新增模块：根据功能需求定义新数据结构
      - 每个数据结构标注变更类型（新增/修改/删除/无变更）

  3c. **数据库表变更**（新增表/修改字段/索引变更）：
      - 分析 TECH_ARCH_DATA 中的数据库相关依赖
      - 结合 CLARIFY_DATA 中的数据依赖，确定表变更范围
      - 每个变更标注变更类型和影响范围

  3d. **消息/接口契约**（跨模块数据交换格式）：
      - 识别模块间的数据交换点（来自 FUNC_ARCH_DATA 中的交互流程和 MODULE_DATA 中的模块依赖）
      - 定义请求/响应格式，标注调用方和被调用方

  3e. **枚举与常量定义**：
      - 从功能点中提取需要新增或修改的枚举值
      - 标注变更类型

Step 4 — 函数设计
  4a. **模块概要整理**：
      对 MODULE_DATA 中的每个模块，依次执行：
      - 从 FUNC_ARCH_DATA 中获取该模块的职责描述、所属层
      - 从 TECH_ARCH_DATA 中获取该模块的关键文件、承载核心功能
      - 确定改造类型（修改/新增）
      - 汇总涉及的功能点（来自 MODULE_DATA）

  4b. **函数识别与设计**：
      对修改模块：
        - 从 FUNC_ARCH_DATA 中提取该模块的关键入口（类/方法）
        - 从 TECH_ARCH_DATA 中提取该模块的执行流（方法调用序列）
        - 结合 MODULE_DATA 中的功能点，识别需要修改的已有函数
        - 识别需要新增的辅助函数
        - 识别需要删除的废弃函数
      对新增模块：
        - 根据功能需求设计新增函数
        - 参考同层已有模块的函数组织方式（来自 TECH_ARCH_DATA）

  4c. **函数签名设计**：
      - 为每个函数确定：函数名、入参列表（类型+名称）、出参（类型）、所属类/文件
      - 修改类函数：保留原签名格式，仅标注需要修改的参数或返回值
      - 新增类函数：参考同模块/同层已有函数的命名和参数风格

  4d. **函数伪代码编写**（结构化伪代码）：
      对每个函数编写结构化伪代码，包含：
      - 关键逻辑分支（if/else）：标注条件判断逻辑
      - 循环结构：标注遍历/迭代对象
      - 异常处理：标注可能抛出的异常和处理方式
      - 核心数据结构操作：标注读写的数据结构
      - 与其他函数/模块的交互点：标注调用关系
      - 不写具体业务算法实现细节

  4e. **模块内部调用关系**：
      - 绘制模块内函数间的调用链
      - 标注调用方向和调用方式（同步/异步/回调）

Step 5 — 代码确认
  对 Step 4 中识别的所有函数进行代码确认：
  代码检索范围为 PRODUCT_CODE_ROOT 指向的代码目录。

  5a. **修改类函数确认**：
      - 在 PRODUCT_CODE_ROOT 代码目录中搜索函数名和相关的类文件路径
      - 读取对应文件，验证函数签名一致性
      - 确认结论：
        ✓ 函数存在且签名一致 → 确认为修改函数
        ✓ 函数存在但签名不一致 → 以代码为准，调整函数设计方案
        ✓ 函数不存在 → 标注 `[待确认]`，可能为新增函数误分类

  5b. **新增类函数确认**：
      - 在 PRODUCT_CODE_ROOT 代码目录中检查同名/同签名函数是否已存在
      - 确认结论：
        ✓ 无冲突 → 确认为新增函数
        ✓ 存在同名函数 → 以代码为准，调整为修改函数或重命名
        ✓ 无法验证 → 标注 `[待确认]`

  5c. **删除类函数确认**：
      - 在 PRODUCT_CODE_ROOT 代码目录中确认该函数确实存在
      - 确认结论：
        ✓ 函数存在 → 确认可删除
        ✓ 函数不存在 → 标注 `[待确认]`，可能已被删除

  5d. **代码确认记录**：
      - 对每个函数记录：确认类型、确认依据（文件路径+检索结果）、确认状态
      - 无法确认的条目汇总到附录 2.2 待确认项清单（`pending_items` 列表）

Step 6 — 跨模块交互设计
  6a. **模块间函数调用关系**：
      - 汇总所有涉及跨模块调用的函数
      - 标注调用方式（同步调用/异步消息/HTTP/RPC/共享内存等，来自 TECH_ARCH_DATA）
      - 构建调用关系表

  6b. **数据流向**：
      - 基于 Step 3 的数据设计，绘制跨模块的数据流向图
      - 标注数据的产出方和消费方

  6c. **接口契约汇总**：
      - 汇总 Step 3 中定义的跨模块消息/接口契约
      - 构建契约汇总表

Step 7 — 约束与风险应对落实
  7a. **技术约束在函数中的体现**：
      - 逐条检查 CLARIFY_DATA 中的技术约束和 TECH_ARCH_DATA 中的编译期约束
      - 在函数设计中标注每条约束如何体现（如条件编译分支、参数校验、异常捕获等）

  7b. **风险应对措施落实**（仅当 RISK_DATA 存在时）：
      - 逐条检查 RISK_DATA 中的风险和应对措施
      - 在函数设计中标注每个风险应对措施如何落实
      - 若无 RISK_DATA，此节简化为"无需求风险输入，风险应对留待后续补充"

  7c. **边界约束落实**（仅当 BOUNDARY_DATA 存在时）：
      - 逐条检查 BOUNDARY_DATA 中的功能边界和技术边界
      - 在函数设计中标注边界约束如何体现（如参数校验、权限检查、范围限制等）
      - 若无 BOUNDARY_DATA，此节简化为"无边界确认输入，边界约束留待后续补充"

Step 8 — 验收映射（仅当 ACCEPTANCE_DATA 存在时生成完整版）
  8a. 逐条检查 ACCEPTANCE_DATA 中的验收条件
  8b. 将每个验收条件映射到对应的函数
  8c. 确定验证方式（单元测试/集成测试/手动验证）
  8d. 若无 ACCEPTANCE_DATA，此节简化为"无验收标准输入，验收映射留待后续补充"

Step 9 — 影响评估
  9a. **性能影响分析**：
      - 识别代码变更中的性能敏感点（循环、数据库操作、文件IO、网络调用、大数据处理）
      - 评估每项变更的资源消耗类型（CPU/内存/磁盘IO/网络带宽）
      - 对无法规避的性能影响，标注原因和已采取的规避措施
      - 输出格式：| 变更点 | 性能影响类型 | 影响程度 | 无法规避原因 | 规避措施 |

  9b. **功能影响分析**：
      - **直接影响**：本次需求直接涉及的功能模块
      - **间接影响**：被依赖的上游/下游功能
      - **潜在影响**：可能触发的边界场景和异常流程
      - 输出格式：| 影响类型 | 影响模块 | 影响说明 | 影响范围 | 备注 |

  9c. **配置变更说明**：
      - 从 CLARIFY_DOC 和 TECH_ARCH_DOC 中提取配置项
      - 区分**运行时配置**和**构建期配置**
      - 标注配置变更的影响范围（全局/模块级/实例级）
      - 输出格式：| 配置项 | 变更类型 | 配置位置 | 影响范围 | 变更说明 |

  9d. **升级风险**：
      - **数据迁移**：评估数据库Schema变更是否需要数据迁移脚本
      - **接口兼容**：评估新旧接口的向后兼容性
      - **回滚方案**：评估回滚难度和影响范围
      - **灰度策略**：评估灰度发布可行性
      - 输出格式：| 风险类型 | 风险描述 | 风险等级 | 规避措施 | 回滚预案 |

  9e. **安全影响**：
      - 识别新增/修改的输入点（API/文件上传/用户输入）
      - 评估敏感数据处理（加密/脱敏/日志记录）
      - 检查权限变更影响范围
      - 输出格式：| 安全维度 | 影响说明 | 影响程度 | 安全措施 | 备注 |

  9f. **兼容性影响**：
      - **本兼容**：新旧版本数据/接口兼容性
      - **硬件平台**：CPU架构（x86/ARM）兼容性
      - **操作系统**：Windows/Linux/国产化系统兼容性
      - **数据库**：数据库版本兼容性和Schema变更
      - **中间件**：Redis/Kafka/MySQL等组件版本兼容性
      - **浏览器**：前端页面的浏览器兼容性
      - 输出格式：| 兼容类型 | 兼容项 | 当前版本 | 目标版本 | 兼容性评估 | 说明 |

  9g. **UI/UE设计**：
      - 从 CLARIFY_DOC 提取界面相关需求
      - 分析新增/修改的页面和组件
      - 评估对用户体验的影响（操作流程/加载速度/错误提示）
      - 输出格式：| 界面元素 | 变更类型 | 变更说明 | 设计注意事项 | 验收要点 |

Step 10 — 文档落地（调用 whalecloud-dev-tool-doc-generate）
  10a. 复制 `references/function_solution_context.skeleton.json` 为 `ctx` 骨架，按「CONTEXT_JSON 字段契约」将 Step 1–9 映射填入（键名须与模板占位符**逐字**一致）
      - **必须包含**骨架中全部标量键与全部列表键（无数据则 `[]`，标量无数据则 `"[待补充]"` 或分析结论）
      - §1.7 仅用 `modules[]`（含嵌套 `functions[]`），`#### 1.7.N` 由 doc-generate 的 `scripts/fill_function_solution.py` 按模板生成，不得在 JSON 里自写 Markdown 标题
      - **禁止** `DOCUMENT_BODY`、禁止在 JSON 中携带预渲染的 `## 1.` / `## 2.` 正文
      - **禁止**下列错误键名（`scripts/fill_function_solution.py` 会报错中止，勿与 `solution_review.json` 等其它技能混用）：
        - 顶层：`requirement_name`→`REQUIREMENT_NAME`；`status`→`STATUS`；`demand_id`/`config_xml`/`verification` 等无契约字段
        - `repos[]`：`repo_name`/`repo_path`/`files`→`branch_id`/`repo_url`/`change_desc`
        - `modules[].functions[]`：`func_signature`/`func_name`/`pseudo_code`→`signature`/`pseudocode` 等契约字段
        - `data_structures[]`：`file`/`definition`→`name`/`change_type`/`module`/`description`
  10b. 将 `ctx` 写入 `{ARCHIVE_DIR}/.tmp/function_solution_context.json`（UTF-8，无 BOM），记为 CONTEXT_PATH；或序列化为内联字符串 `CONTEXT_JSON_STR = json.dumps(ctx, ensure_ascii=False)`（二选一，**推荐文件路径**）
  10c. **使用 `Skill` 工具调用** `whalecloud-dev-tool-doc-generate`（`OUTPUT` 必须为 `函数级方案.md`）：
      - OUTPUT_DIR: `{ARCHIVE_DIR}`
      - OUTPUT: `函数级方案.md`
      - CONTEXT_JSON: CONTEXT_PATH **或** CONTEXT_JSON_STR（与需求澄清等模板相同）
      - PROD、STATUS、REQUIREMENT_NAME: 与技能 Parameters 一致（也可写入 `ctx`）
      - OUTPUT_MODE: `file`
  10d. 确认 doc-generate 已执行 `scripts/fill_function_solution.py` 并以 `write_file` 写入 `{ARCHIVE_DIR}/函数级方案.md`；验收：
      - 无 `{{` / `{{#each` 残留；含模板固定章节与表头
      - 与模板对照：章节层级、表格列名、页眉字段名一致
      - 中文可读，无乱码；落盘失败则**中止**
```

---

## 文档落地（whalecloud-dev-tool-doc-generate）

本技能**只负责分析与正文组装**；**写盘一律委托** `whalecloud-dev-tool-doc-generate`。

| 项 | 值 |
|----|-----|
| 下游技能 | `whalecloud-dev-tool-doc-generate` |
| 模板 | `templates/函数级方案.md`（与 `OUTPUT` 同名） |
| OUTPUT_DIR | `{ARCHIVE_DIR}`（默认 `{WORK_ORDER_DIR}/archive/需求设计/func_solution/`） |
| OUTPUT | `函数级方案.md` |
| 数据契约 | 结构化 `CONTEXT_JSON`（见下节）；doc-generate **必须**经 `scripts/fill_function_solution.py` 填充模板 |

### 调用示例

```
OUTPUT_DIR: work/21881451/archive/需求设计/func_solution/
OUTPUT: 函数级方案.md
CONTEXT_JSON: work/21881451/archive/需求设计/func_solution/.tmp/function_solution_context.json
PROD: XXX系统
STATUS: draft
OUTPUT_MODE: file
```

或内联 JSON 字符串：`CONTEXT_JSON: "{\"REQUIREMENT_NAME\":\"……\",\"modules\":[...],\"repos\":[...]}"`

> **注意**：`CONTEXT_JSON` 与需求澄清等文档相同，支持**文件路径或内联字符串**；**禁止** `DOCUMENT_BODY`。伪代码换行在 JSON 内用 `\n`。

---

## CONTEXT_JSON 字段契约

与 `templates/函数级方案.md` 占位符一一对应。列表无数据时填 `[]`（doc-generate `scripts/fill_function_solution.py` 表体写「（无）」，**保留**表头与章节标题）。

**骨架文件（强制）**：`references/function_solution_context.skeleton.json`（含全部顶层键默认值）；机器可读约束见同目录 `function_solution_context.schema.json`。落盘前由 `whalecloud-dev-tool-doc-generate/scripts/fill_function_solution.py` 的 `validate_context` 校验。

**`ctx` 顶层键清单（须全部出现）**

标量：`REQUIREMENT_NAME`, `DEMAND_DESC`, `scope_overview`, `tech_stack_constraints`, `data_flow_diagram`, `function_stats`, `code_confirm_rate`, `PROD`, `STATUS`（后两者也可仅经 doc-generate Parameters 传入）

列表：`repos`, `terms`, `data_structures`, `db_changes`, `message_contracts`, `enums`, `modules`, `cross_module_calls`, `interface_summary`, `tech_constraints`, `risk_mitigations`, `boundary_constraints`, `performance_impacts`, `functional_impacts`, `config_changes`, `upgrade_risks`, `security_impacts`, `compatibility_impacts`, `ui_ue`, `acceptance_mapping`, `code_confirmations`, `pending_items`

### 标量字段

| 字段 | 模板位置 | 说明 |
|------|----------|------|
| `REQUIREMENT_NAME` | 页眉 | CLARIFY_DATA 需求名称 |
| `DEMAND_DESC` | §1.1 | 需求背景 |
| `scope_overview` | §1.2 | 涉及模块 / 新增模块概述 |
| `tech_stack_constraints` | §1.4 | 技术栈与编译约束；缺 TECH_ARCH 时含 `[待补充-缺少技术架构文档]` |
| `data_flow_diagram` | §1.8.2 | 数据流向（文本/ASCII） |
| `function_stats` | §2.3 | 如 `共计 5 个函数（新增 2 个，修改 2 个，删除 1 个）` |
| `code_confirm_rate` | §2.3 | 如 `85%` |
| `PROD` / `STATUS` | 页眉 | 可由 Parameters 传入，须写入 JSON 或 Parameters |

`TIMESTAMP` 由 doc-generate 自动生成，无需上游传入。

### 列表字段（对象数组）

| 字段 | § | 对象键（每行） |
|------|---|----------------|
| `repos` | 1.3 | `branch_id`, `repo_url`, `change_desc` |
| `terms` | 1.5 | `term`, `meaning` |
| `data_structures` | 1.6.1 | `name`, `change_type`, `module`, `description` |
| `db_changes` | 1.6.2 | `table_name`, `change_type`, `field_changes`, `description` |
| `message_contracts` | 1.6.3 | `interface_name`, `caller`, `callee`, `request_fields`, `response_fields` |
| `enums` | 1.6.4 | `name`, `change_type`, `values`, `description` |
| `modules` | 1.7 | 见下表 |
| `cross_module_calls` | 1.8.1 | `caller_module`, `callee_module`, `function_name`, `call_mode` |
| `interface_summary` | 1.8.3 | `interface_name`, `request_format`, `response_format`, `provider`, `consumer` |
| `tech_constraints` | 1.9.1 | `constraint`, `implementation` |
| `risk_mitigations` | 1.9.2 | `risk`, `measure`, `implementation` |
| `boundary_constraints` | 1.9.3 | `constraint`, `implementation` |
| `performance_impacts` | 1.10.1 | `change_point`, `impact_type`, `severity`, `unavoidable_reason`, `mitigation` |
| `functional_impacts` | 1.10.2 | `impact_type`, `module`, `description`, `scope`, `remark` |
| `config_changes` | 1.10.3 | `config_item`, `change_type`, `location`, `scope`, `description` |
| `upgrade_risks` | 1.10.4 | `risk_type`, `description`, `level`, `mitigation`, `rollback` |
| `security_impacts` | 1.10.5 | `dimension`, `description`, `severity`, `measures`, `remark` |
| `compatibility_impacts` | 1.10.6 | `compat_type`, `item`, `current_version`, `target_version`, `assessment`, `description` |
| `ui_ue` | 1.10.7 | `element`, `change_type`, `description`, `design_notes`, `acceptance_points` |
| `acceptance_mapping` | 1.11 | `criterion`, `mapped_function`, `verification` |
| `code_confirmations` | 2.1 | `function`, `confirm_type`, `evidence`, `status` |
| `pending_items` | 2.2 | `item`, `description`, `priority` |

### `modules[]` 与嵌套 `functions[]`

| 键 | 说明 |
|----|------|
| `module_name` | 模块名称（生成 `#### 1.7.N` 标题） |
| `layer` | 所属层 |
| `responsibility` | 职责 |
| `change_type` | 改造类型（修改/新增） |
| `feature_points` | 涉及功能点 |
| `key_files` | 关键文件 |
| `internal_call_graph` | 模块内调用链（文本） |
| `functions` | 函数数组，每项见下 |

`functions[]` 每项：`signature`, `inputs`, `outputs`, `class_file`, `responsibility`, `change_type`, `pseudocode`（结构化伪代码正文）, `call_relations`（上游/下游/数据依赖）

### JSON 片段示例

完整键集合以 `references/function_solution_context.skeleton.json` 为准；以下为填充后的片段：

```json
{
  "REQUIREMENT_NAME": "索引优先级在线变更",
  "DEMAND_DESC": "……",
  "scope_overview": "修改模块：索引服务；新增模块：无",
  "tech_stack_constraints": "C++17；ZMDB 9.0 分支",
  "data_flow_diagram": "……",
  "function_stats": "共计 3 个函数（新增 1 个，修改 2 个，删除 0 个）",
  "code_confirm_rate": "100%",
  "PROD": "XXX系统",
  "STATUS": "draft",
  "repos": [{"branch_id": "4531", "repo_url": "https://git.example/ZMDB.git", "change_desc": "索引优先级改造"}],
  "terms": [],
  "data_structures": [],
  "db_changes": [],
  "message_contracts": [],
  "enums": [],
  "modules": [{
    "module_name": "索引模块",
    "layer": "服务层",
    "responsibility": "索引维护",
    "change_type": "修改",
    "feature_points": "在线调优先级",
    "key_files": "IndexMgr.cpp",
    "internal_call_graph": "setPriority → validate → persist",
    "functions": [{
      "signature": "setIndexPriority(idx, pri)",
      "inputs": "idx: int, pri: int",
      "outputs": "bool",
      "class_file": "IndexMgr.cpp",
      "responsibility": "设置索引优先级",
      "change_type": "修改",
      "pseudocode": "IF idx invalid THEN RETURN false\n  persist(pri)\n  RETURN true",
      "call_relations": "上游: API.setPriority；下游: persist"
    }]
  }],
  "code_confirmations": [{"function": "setIndexPriority", "confirm_type": "修改", "evidence": "IndexMgr.cpp:L42", "status": "已确认"}],
  "pending_items": [],
  "cross_module_calls": [],
  "interface_summary": [],
  "tech_constraints": [],
  "risk_mitigations": [],
  "boundary_constraints": [],
  "performance_impacts": [],
  "functional_impacts": [],
  "config_changes": [],
  "upgrade_risks": [],
  "security_impacts": [],
  "compatibility_impacts": [],
  "ui_ue": [],
  "acceptance_mapping": []
}
```

无 RISK_DATA / BOUNDARY_DATA / ACCEPTANCE_DATA 时，`risk_mitigations`、`boundary_constraints`、`acceptance_mapping` 可各放一条说明性记录（如 `risk`: `无需求风险输入`）或留空数组。

---

## 伪代码编写规范

### 结构化伪代码格式

```
函数名(参数列表) -> 返回类型
  // 职责：一句话描述函数职责
  
  TRY
    // 1. 参数校验
    IF 参数不合法 THEN
      THROW IllegalArgumentException("具体校验失败原因")
    END IF
    
    // 2. 核心逻辑
    FOR EACH item IN collection DO
      IF 满足条件 THEN
        // 处理逻辑
        CALL 另一个函数(参数)   // → [模块名.函数名]
      ELSE
        // 分支逻辑
      END IF
    END FOR
    
    // 3. 结果封装
    RETURN 结果对象
  CATCH 异常类型 AS e
    LOG ERROR "操作失败: " + e.message
    THROW BusinessException(错误码, 错误信息)
  END TRY
```

### 调用关系标注规范

- **上游调用**：列出调用本函数的外部函数，格式 `模块名.函数名`
- **下游调用**：列出本函数调用的其他函数，格式 `模块名.函数名`
- **数据依赖**：列出本函数读写的数据结构/表，格式 `数据结构名.操作类型`（操作类型：读/写/修改）

### 模块内部调用关系格式

```
函数A → 函数B → 函数C
              → 函数D
     → 函数E
函数F → 函数B
     → 函数G → 函数H
```

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 缺少必填参数（WORK_ORDER_DIR/PRODUCT_DOC_ROOT/PROD） | **中止**，列出缺失参数 |
| CLARIFY_DOC 或 MODULE_DOC（由 WORK_ORDER_DIR 推导）文件不存在 | **中止**，提示文档路径无效 |
| FUNC_ARCH_DOC 或 TECH_ARCH_DOC（由 PRODUCT_DOC_ROOT 推导）文件不存在 | 标注 `[待补充]` 后继续执行 |
| 代码检索无结果 | 标注 `[待确认]`，不得虚构内容 |
| 上游文档中某模块无代码影响范围 | 标注 `[缺少代码影响范围]`，尝试通过代码检索补充 |
| 输出目录创建失败或 doc-generate 落盘失败 | **中止**，提示路径权限或下游技能错误信息 |
| `scripts/fill_function_solution.py` 报 `CONTEXT_JSON 契约校验失败` | **中止**，从 skeleton.json 复制骨架并修正键名（见 Step 10a 禁止项列表）后重试 |
| 未调用 doc-generate 而直接 write_file 写交付物 | **视为未完成**，须改用 doc-generate 重写 |
