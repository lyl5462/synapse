---
name: whalecloud-dev-tool-requirement-clarify
description: "需求澄清技能 - 分析原始需求，结合 GitNexus 源码检索，生成需要澄清的问题列表，逐轮向用户确认直到需求清晰。"
label: 需求澄清技能
---

# 需求澄清技能

通过分析原始需求信息，结合 GitNexus 源码检索能力，逐轮向用户确认关键点，确保需求清晰可理解。

## 共享系统脚本（BASE_SCRIPTS_DIR）

与 SynapseService / GitNexus 交互的脚本位于技能 **`whalecloud-dev-tool-base-scripts`**（`skills/whalecloud-dev-tool-base-scripts/`）。**BASE_SCRIPTS_DIR** 为其根目录（系统提示中「研发技能：whalecloud-dev-tool-base-scripts」的 `**技能路径**:`）。`get_repo_info.py`、`get_doc.py`、`gnx-tools.js` 等须用 `<BASE_SCRIPTS_DIR>/scripts/...` 调用。

**例外**：`question-transform.py` 仍在本技能（`whalecloud-dev-tool-requirement-clarify`）目录的 `scripts/` 下，用于生成前端可渲染问题 JSON。

---

> ⚠️ **【强制警告】技能执行输出约束**
> 
> **本技能执行过程中，大模型只能输出以下内容：**
> - **提问阶段**：通过 `scripts/question-transform.py` 脚本生成的 JSON 格式问题
> - **生成文档阶段**：读取模板后填充的 Markdown 格式文档
> 
> **严格禁止输出任何其他内容**（解释、说明、提示、调试信息、日志等）
> 
> **违反此约束视为技能未完成。**

---

## Parameters

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `DEMAND_DESC` | 是 | 原始的需求描述内容 |
| `DEMAND_IMPACT` | 是 | 原始的需求影响内容 |
| `PROD_FEATURE` | 是 | 产品包含的功能模块列表信息 |
| `PROD` | 是 | 产品名称 |
| `SYNAPSE_URL` | 是 | SynapseService 服务地址，如 `192.168.1.100:8080` |
| `GITNEXUS_URL` | 是 | GitNexus 服务地址，如 `http://127.0.0.1:11011` |
| `GNX_REPO` | 否 | GitNexus 仓库名称，如 `MyProj@@branch`。若不传入，则自动通过 `<BASE_SCRIPTS_DIR>/scripts/get_repo_info.py` 获取产品关联的全部仓库 |
| `OUTPUT_DIR` | 否 | 输出目录，默认 `./requirements/` |
| `TMP_DIR` | 否 | 临时文件目录，默认 `{OUTPUT_DIR}/.tmp/`，其下存储 `docs/`（架构文档）和 `.gnx-cache/`（源码缓存，按仓库分目录） |
| `OUTPUT` | 否 | 输出文件名，默认 `01-需求澄清.md` |
| `USER_ANSWER` | 否 | 用户回复的内容（首次提问时为空） |

> **仓库名称**：无需手动传递。技能启动时自动通过 `<BASE_SCRIPTS_DIR>/scripts/get_repo_info.py` 从 SynapseService 获取该产品关联的**所有代码仓库**列表。一个产品通常由多个仓库组合而成（如 `仓库A` + `仓库B`），最终需求澄清结果整合所有仓库的源码分析结果。

---

## 核心约束（违反本技能视为未完成）

### A. 技能执行输出限制（强制约束）

**整个技能执行过程中，大模型只能输出以下内容：**

1. **提问阶段**：通过 `scripts/question-transform.py` 脚本生成并输出 JSON 格式的问题（可直接被前端渲染）
2. **生成文档阶段**：读取模板 `templates/01-需求澄清.md`，填充变量后输出 Markdown 格式的文档

**禁止输出任何其他内容**：
- 不得输出任何解释、说明、上下文等信息
- 不得输出 "正在分析"、"请稍等"、"以下是问题" 等提示
- 不得输出代码块标记（```json、```markdown 等），直接输出原始内容
- 不得输出任何调试信息、日志信息

**违反此约束视为技能未完成。**

### B. 多仓库源码核验（强制约束）

- 产品可能由**多个仓库**组成，每个仓库独立缓存至 `{TMP_DIR}/.gnx-cache/{REPO_NAME}/` 目录。
- 需求分析中凡涉及**模块路径、接口、依赖关系、关键符号**等结论，须在对应仓库缓存上通过 **`gnx-tools.js search`、`cypher`、`read` 或 `grep`** 至少提供一条可核对证据。
- **跨仓库结论必须分别核验**：对每个仓库独立执行检索操作，并在分析中标注信息来源于哪个仓库。
- 无法通过源码验证的条目必须标注 **`[待代码确认]`**，不得虚构。
- 若某仓库未获取成功，涉及该仓库的分析标注 `[待补充-{REPO_NAME}仓库未获取]`。

### C. 问题生成（必须使用脚本）

**必须使用 `scripts/question-transform.py` 脚本生成问题**，不得自行构造 JSON 输出。

详细使用说明请参考 [references/question-transform.md](references/question-transform.md)。

**输出限制**：
- 不得输出任何解释、说明、上下文等信息
- 只能输出脚本生成的 JSON 内容

### D. BDD 驱动的需求澄清（强制约束）

本技能采用 BDD（行为驱动开发）思想指导需求澄清过程，核心原则：

#### D1. 示例驱动：用具体场景代替抽象分类

**生成问题时必须先推导具体示例，再将示例转化为选择题。**

禁止：
- 生成纯抽象分类问题，如"索引优先级的类型？"（选项：Hash/B+Tree/主键）
- 生成无场景的判断题，如"是否需要审批？"（选项：是/否）

要求：
- 每个问题必须包含一个**假设场景**，描述具体的前置条件和操作
- 选项必须描述**不同行为结果**，而非单纯分类
- 场景中的角色、操作、状态要具体可感知

**示例对比**：

| 类型 | ❌ 禁止（抽象分类） | ✅ 要求（示例驱动） |
|------|-------------------|-------------------|
| 单选题 | 索引优先级的类型？A.Hash B.B+Tree C.主键 | 假设索引优先级为"中"，运维人员想调更高，优先级表示方式？A.固定三级高/中/低 B.数字1-100自定义 C.固定五级 D.自定义标签 |
| 判断题 | 变更是否需要审批？ | 假设开发人员小李想将自己索引优先级从"低"调为"高"，操作流程？A.直接修改无需审批 B.修改后通知DBA C.提交申请DBA审批 D.仅DBA可修改 |
| 判断题 | 是否立即生效？ | 假设有3个查询正使用该索引（按"中"优先级调度），变更为"高"后的行为？A.立即切换 B.旧任务完成后新任务用新值 C.队列切换 D.需人工确认 |

#### D2. 三视角问题：业务/开发/测试

**深度澄清阶段（非首次提问）的每条业务规则必须从三个视角各生成至少一个问题。**

| 视角 | 问题模板 | 关注点 | 存量产品中的特殊意义 |
|------|---------|--------|-------------------|
| 👔 业务视角 | "当 X 时，期望的**业务结果**是什么？" | 业务意图和期望效果 | 确认业务意图，避免做错东西 |
| 💻 开发视角 | "这个变更会影响**现有哪些模块/接口**？内部如何实现？" | 技术实现和存量影响 | 识别存量代码的影响范围 |
| 🧪 测试视角 | "如果 Y（异常情况），**应该怎样处理**？" | 边缘情况和异常路径 | 暴露存量产品中最容易出问题的场景 |

**三视角问题生成规则**：
- 首轮范围圈定问题不受三视角约束（聚焦范围即可）
- 深度澄清阶段，每条业务规则至少生成 3 个问题（业务×1 + 开发×1 + 测试×1）
- 测试视角问题**必须包含异常或边缘场景**，不能是正常路径
- 每个问题的 context 字段中标注视角标签：`[业务视角]`、`[开发视角]`、`[测试视角]`

#### D3. 业务规则拆解：示例映射四色法

**分析需求时必须使用示例映射（Example Mapping）拆解业务规则。**

| 颜色 | 含义 | 在本技能中的对应 |
|------|------|----------------|
| 🟡 黄色 | 用户故事/特性 | DEMAND_DESC 原始需求 |
| 🔵 蓝色 | 业务规则（验收标准） | 从需求中提取的行为规则 |
| 🟢 绿色 | 具体示例（场景） | 转化为问题的假设场景 |
| 🔴 红色 | 问题/不确定之处 | 必须生成的澄清问题 |

**拆解流程**：
1. **黄色卡片前置确认**：先通过需求动机挖掘（三层追问：触发场景 → 痛点 → 期望收益）确认黄色卡片（用户故事）的**真实动机**，而非仅使用 DEMAND_DESC 的表面文字
2. 基于动机确认后的黄色卡片，拆解为蓝色卡片（业务规则列表）
3. 为每条蓝色卡片推导绿色卡片（具体示例），推导方向由动机确认结果引导
4. 识别红色卡片（无法从源码/文档确认的问题）
5. 绿色卡片转化为示例驱动的问题选项，红色卡片转化为判断题或开放题

---

## 工作流程

```
技能调用流程（四阶段流水线）：

本技能采用四阶段流水线结构，每个阶段有明确的输入、产出和职责边界。
阶段之间形成依赖链：Phase 1 的产出是 Phase 2 的输入，Phase 2 的产出是 Phase 3 的输入，以此类推。

【阶段概览】
Phase 0 — 环境准备：参数校验 + 仓库获取 + 目录创建 + 资料下载（仅首次执行）
Phase 1 — 代码范围圈定：源码检索 + 模块分析 + 范围确认问题（代码检索前置）
Phase 2 — 需求背景挖掘：三层动机追问 + 背景分析（触发场景 → 痛点 → 期望收益）
Phase 3 — 用户故事：示例映射四色卡片 + 规则确认（蓝卡 → 绿卡 → 红卡）
Phase 4 — 深度澄清：三视角问题生成 + 源码核验 + 行为场景生成（最终交付）
```

---

### Phase 0 — 环境准备（首次调用必执行）

**触发条件**：首次调用技能（无论 USER_ANSWER 是否为空，均需判断是否已完成环境准备）

**执行步骤**：

  0a. 校验必填参数：对照 Parameters 章节，校验所有标记为"是"的参数均已提供

  0b. Python 命令适配：优先使用 `python3`，若不可用则尝试 `py`（Windows），均不可用则尝试 `python`。以下用 `{PYTHON}` 指代实际可用的 Python 命令。

  0c. 自动获取产品关联的所有仓库：
        → {PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_repo_info.py --server-url={SYNAPSE_URL} --prod={PROD}
      解析输出 "产品：XXX 一共有N个仓库：REPO1,REPO2"，提取所有仓库名列表，记为 GNX_REPO_LIST。
      若用户传入了 GNX_REPO（单仓库兼容模式），则 GNX_REPO_LIST = [GNX_REPO]，跳过此步骤。
      若输出包含 "未找到仓库信息" 则**中止**并提示：该产品未关联代码仓库，请检查 PROD 参数。

  0d. 创建输出目录和临时目录（若不存在）：
        → mkdir -p {OUTPUT_DIR} {TMP_DIR} {TMP_DIR}/docs
        → 为每个仓库创建独立缓存目录：mkdir -p {TMP_DIR}/.gnx-cache/{REPO_NAME}

  0e. 执行 question-transform.py --reset --output_dir {TMP_DIR} 清理之前的问题列表

  0f. 使用 get_doc.py 获取产品架构文档，保存到 {TMP_DIR}/docs/
        {PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_doc.py --doc_type=产品架构 --server_url {SYNAPSE_URL} --prod {PROD} --doc_name=TECH_ARCH.md --output {TMP_DIR}/docs
        {PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_doc.py --doc_type=产品架构 --server_url {SYNAPSE_URL} --prod {PROD} --doc_name=FUNCTIONAL_ARCH.md --output {TMP_DIR}/docs

  0g. 使用 gnx-tools.js materialize 下载源码到本地缓存（遍历 GNX_REPO_LIST）：
        对每个仓库依次执行：
          node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js materialize --url {GITNEXUS_URL} --repo {REPO_NAME} --cache {TMP_DIR}/.gnx-cache/{REPO_NAME}
        任一仓库 materialize 失败：记录该仓库为「未能获取」，继续处理其余仓库。
        **仅当所有仓库均 materialize 失败时才中止。**

  0h. 使用 gnx-tools.js overview 获取项目概览（遍历 GNX_REPO_LIST）：
        对每个仓库依次执行：
          node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js overview --url {GITNEXUS_URL} --repo {REPO_NAME} --out {TMP_DIR}/.gnx-cache/{REPO_NAME}/overview.json

**产出**：环境准备完成，所有仓库源码已缓存，架构文档已获取

**后续动作**：进入 Phase 1

---

### Phase 1 — 代码范围圈定

**触发条件**：环境准备已完成，需要确定代码检索范围

**输入**：架构文档（TECH_ARCH.md + FUNCTIONAL_ARCH.md）+ 各仓库 overview.json

**执行步骤**：

  1a. 分析架构文档，定位与需求相关的功能模块，提取模块名称和描述

  1b. 分析各仓库的 overview.json，建立"模块 → 仓库"的映射关系

  1c. 根据 DEMAND_DESC + DEMAND_IMPACT + PROD_FEATURE，推导初步搜索关键词

  1d. 使用 gnx-tools.js search 初步检索（遍历 GNX_REPO_LIST，基于关键词）：
        对每个仓库分别执行：
          node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js search --url {GITNEXUS_URL} --repo {REPO_NAME} --query "关键词"
        汇总检索结果，标注每条结果所属仓库

  1e. 使用 gnx-tools.js grep 本地二次搜索（在关键模块路径下搜索）：
        对每个仓库分别执行：
          node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js grep --cache {TMP_DIR}/.gnx-cache/{REPO_NAME} --pattern "关键词"

  1f. 汇总代码检索结果，形成"相关模块清单 + 相关仓库清单 + 核心入口文件/函数"

  1g. 生成范围圈定问题：
        - 涉及哪些功能模块？（列出检索到的相关模块，标注所属仓库）
        - 涉及哪些代码仓库？（从 GNX_REPO_LIST 列出，帮助用户确认是否排除部分仓库）
        - 核心应用入口或触发场景是什么？（用检索到的具体代码位置描述）
        - 是否需要排除某些模块或场景？
        **注意**：范围圈定问题遵循约束 D1 示例驱动，但不需要三视角标注

**产出**：
- 内部维护：相关模块/仓库/入口清单（供后续阶段使用）
- 对外输出：通过 question-transform.py --read 输出的 JSON 问题（等待用户确认）

**后续动作**：通过 question-transform.py --read 输出 JSON 问题 → 等待用户回答 USER_ANSWER → 进入 Phase 2

---

### Phase 2 — 需求背景挖掘

**触发条件**：用户已回答范围圈定问题（USER_ANSWER 包含范围确认信息）

**输入**：Phase 1 的范围清单 + DEMAND_DESC + DEMAND_IMPACT + PROD_FEATURE

**执行步骤**：

  2a. 解析 USER_ANSWER，更新范围圈定信息

  2b. 使用 question-transform.py --update 更新问题记录

  2c. **需求动机挖掘**（遵循约束 D1 示例驱动）：
        对原始需求从三个层面逐层追问，生成动机澄清问题：

        第一层：触发场景 — "这个需求是在什么业务场景下产生的？"
        示例驱动格式，例如：
          "假设您是一名运维人员，请问产生'索引优先级在线变更'需求的典型场景是？"
          A.大促/突发流量期间临时调整  B.日常运维效率优化  C.故障恢复时的紧急调度  D.新业务上线前的规划调整

        第二层：痛点与期望 — "当前不支持此功能时，遇到了什么问题？"
        示例驱动格式，例如：
          "假设您发现某个查询突然变慢，当前只能通过离线方式调整索引优先级，这个过程中最大的痛点是？"
          A.需要重启服务导致业务中断  B.调整生效周期太长影响响应速度  C.无法区分紧急和普通查询的调度优先级  D.运维操作步骤繁琐容易出错

        第三层：期望收益 — "解决了这个痛点后，期望达到什么业务效果？"
        示例驱动格式，例如：
          "假设索引优先级在线变更功能已上线，您最期望看到的第一个改善是？"
          A.故障恢复时间从小时级缩短到分钟级  B.大促期间可动态调度资源无需提前规划  C.运维操作从5步简化为1步  D.不同业务线的查询不再互相抢占资源

        **动机挖掘的价值**：决定后续示例映射的推导方向——
        - 触发场景 → 决定场景优先级（紧急场景 vs 日常场景，边缘情况不同）
        - 痛点 → 决定存量行为改造方向（"不能在线调" vs "调了但太慢"）
        - 期望收益 → 决定验收标准的衡量维度（响应速度 vs 操作简化 vs 资源隔离）

  2d. 结合用户圈定的模块范围和入口场景，推导关键搜索线索和关键词（用于后续代码检索）

  2e. 生成动机挖掘问题（遵循约束 D1 示例驱动）：
        - 动机挖掘问题（3题）：触发场景 + 痛点与期望 + 期望收益

**产出**：
- 内部维护：动机挖掘结果（触发场景 + 痛点 + 期望收益）
- 对外输出：通过 question-transform.py --read 输出的 JSON 问题（等待用户回答）

**后续动作**：通过 question-transform.py --read 输出 JSON 问题 → 等待用户回答 USER_ANSWER → 进入 Phase 3

---

### Phase 3 — 用户故事（示例映射四色卡片）

**触发条件**：用户已回答动机挖掘问题（USER_ANSWER 包含动机确认信息）

**输入**：Phase 2 的动机挖掘结果 + Phase 1 的范围清单 + DEMAND_DESC

**执行步骤**：

  3a. 解析 USER_ANSWER，更新动机挖掘结果

  3b. 使用 question-transform.py --update 更新问题记录

  3c. **示例映射拆解**（遵循约束 D3）：
        - **黄色卡片前置确认**：将动机挖掘的三个层面结果（触发场景、痛点、期望收益）作为黄色卡片的真实动机，而非仅使用 DEMAND_DESC 的表面文字
        - 拆解为蓝色卡片列表（业务规则），每条规则是一个独立的行为约束，推导方向由动机确认结果引导
        - 为每条蓝色卡片推导绿色卡片（具体示例），场景优先级由触发场景决定
        - 识别红色卡片（无法从源码/文档确认的问题），痛点决定哪些红色卡片优先级更高
        - **内部维护**四色卡片清单（**不得输出**到任何位置，仅供后续阶段推导使用）

  3d. 生成用户故事确认问题（示例驱动）：
        - 我们理解的需求包含以下业务规则（列出蓝卡），是否正确？
        - 每个规则的核心场景（列出绿卡示例），是否符合您的预期？
        **注意**：此步骤将四色卡片从"内部维护"转化为可交互确认的环节

  3e. **源码核验**（在生成确认问题前）：
        - 使用 gnx-tools.js grep 检索关键代码路径，验证蓝色卡片中的规则是否与现有代码行为一致
        - 对可通过源码确认的规则，标注证据来源
        - 对无法确认的规则，保持为红色卡片

**产出**：
- 内部维护：确认后的四色卡片清单（蓝卡 + 绿卡 + 红卡）
- 对外输出：通过 question-transform.py --read 输出的 JSON 问题（等待用户确认规则）

**后续动作**：通过 question-transform.py --read 输出 JSON 问题 → 等待用户回答 USER_ANSWER → 进入 Phase 4

---

### Phase 4 — 深度澄清（三视角）

**触发条件**：用户已确认用户故事（USER_ANSWER 包含规则确认信息）

**输入**：Phase 3 确认后的蓝卡/绿卡/红卡列表 + 所有源码缓存

**执行步骤**：

  4a. 解析 USER_ANSWER，更新规则确认信息

  4b. 使用 question-transform.py --update 更新问题记录

  4c. **增量源码检索**（如有必要）：
        - 基于 Phase 2 推导的关键词，执行 gnx-tools.js search/grep 补充检索
        - 使用 gnx-tools.js cypher 查询模块依赖关系
        - 结合架构文档和所有仓库的源码检索结果，分析问题答案

  4d. **三视角问题生成**（遵循约束 D2）：
        对每条蓝色卡片（业务规则），分别从三个视角生成问题：
        - 👔 业务视角：1 个问题，聚焦"期望的业务结果"
        - 💻 开发视角：1 个问题，聚焦"现有模块/接口的影响和实现方式"
        - 🧪 测试视角：1 个问题，聚焦"异常/边缘场景的处理"
        每条规则至少 3 个问题，确保三个视角均被覆盖

  4e. 问题内容必须遵循示例驱动（约束 D1），每个问题包含具体假设场景

  4f. 识别可通过源码/文档直接确认的问题，降级为判断题（在 context 中标注证据来源）

  4g. 对每个澄清问题执行 question-transform.py --output_dir {TMP_DIR} 添加问题
        **三视角标注规则**：在 context 参数中添加视角标签前缀：
        - 业务视角问题：--context="[业务视角] 具体场景描述..."
        - 开发视角问题：--context="[开发视角] 具体场景描述..."
        - 测试视角问题：--context="[测试视角] 具体场景描述..."

  4h. 执行 question-transform.py --read --output_dir {TMP_DIR} 获取所有未回答的问题

  4i. **输出 JSON**：将上一步获取的 JSON 内容直接输出（不得添加任何解释、注释或额外内容）

**产出**：
- 对外输出：通过 question-transform.py --read 输出的 JSON 问题（等待用户回答）

**后续动作**：通过 question-transform.py --read 输出 JSON 问题 → 等待用户回答 USER_ANSWER → 循环 Phase 4 直到无新问题 → 进入完成阶段

---

### 完成阶段 — 生成需求澄清文档

**触发条件**：没有新的待确认点（用户回答后无新问题产生，或用户明确表示需求已澄清完成）

**执行步骤**：

  5a. 执行 question-transform.py --readall --output_dir {TMP_DIR} 获取所有已回答的问题

  5b. **生成行为场景**：将所有已回答的澄清问题转化为 Gherkin 格式的行为场景
        - 每条蓝色卡片（业务规则）对应一个 Feature 或 Rule
        - 每组三视角问答合并为一个 Scenario（Given = 前置条件，When = 操作，Then = 期望结果）
        - 测试视角问答转化为独立的边缘场景 Scenario
        - 每个场景标注来源（用户确认 / 源码核验）

  5c. 读取模板 `templates/01-需求澄清.md`，填充变量（含行为场景）生成需求澄清文档

  5d. 写入输出文件 {OUTPUT_DIR}/{OUTPUT}

  5e. 清理中间产物：删除 {TMP_DIR}/.gnx-cache/ 目录（含各仓库子目录）和 {TMP_DIR}/.questions.json 文件

**产出**：读取模板 `templates/01-需求澄清.md`，填充变量后输出的 Markdown 文档 `{OUTPUT_DIR}/{OUTPUT}`

---

## 使用脚本说明

### get_doc.py

脚本路径：`<BASE_SCRIPTS_DIR>/scripts/get_doc.py`（见技能 `whalecloud-dev-tool-base-scripts`）

用于从 SynapseService 获取产品架构文档：

| 命令 | 说明 |
|------|------|
| `--doc_type=产品架构` | 获取产品架构文档 |
| `--doc_type=产品需求` | 获取产品需求文档 |
| `--doc_type=产品方案` | 获取产品方案文档 |
| `--server_url XXX` | SynapseService 服务地址 |
| `--prod XXX` | 产品名称 |
| `--doc_name XXX` | 可选，指定文件名进行过滤（支持模糊匹配） |
| `--output XXX` | 可选，指定输出目录，文档将保存到此目录 |

示例：
```bash
{PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_doc.py --doc_type=产品架构 --server_url {SYNAPSE_URL} --prod {PROD} --doc_name=TECH_ARCH --output {TMP_DIR}/docs
```

### question-transform.py

脚本路径：`scripts/question-transform.py`

详细使用说明请参考 [references/question-transform.md](references/question-transform.md)。

### gnx-tools.js

脚本路径：`<BASE_SCRIPTS_DIR>/scripts/gnx-tools.js`

用于与 GitNexus 交互，检索源码获取答案：

| 命令 | 说明 |
|------|------|
| `materialize --url XXX --repo YYY --cache ZZZ` | 下载源码到本地缓存（`--cache {TMP_DIR}/.gnx-cache`） |
| `overview --url XXX --repo YYY --out ZZZ` | 获取项目概览，了解整体架构 |
| `search --url XXX --repo YYY --query ZZZ` | 混合检索 |
| `cypher --url XXX --repo YYY --cypher "..."` | 图查询 |
| `explore --url XXX --repo YYY --target ZZZ` | 探索特定模块的依赖关系 |
| `read --cache XXX --path YYY` | 读取缓存文件（`--cache {TMP_DIR}/.gnx-cache`） |
| `grep --cache XXX --pattern ZZZ` | 本地正则搜索（`--cache {TMP_DIR}/.gnx-cache`） |

示例：
```bash
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js materialize --url {GITNEXUS_URL} --repo {REPO_NAME} --cache {TMP_DIR}/.gnx-cache/{REPO_NAME}
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js overview --url {GITNEXUS_URL} --repo {REPO_NAME} --out {TMP_DIR}/.gnx-cache/{REPO_NAME}/overview.json
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js search --url {GITNEXUS_URL} --repo {REPO_NAME} --query "关键词"
```

### get_repo_info.py

脚本路径：`<BASE_SCRIPTS_DIR>/scripts/get_repo_info.py`

用于从 SynapseService 获取产品关联的代码仓库列表：

| 参数 | 说明 | 必填 |
|------|------|------|
| `--server-url` | 服务地址 | 是 |
| `--prod` | 产品名称 | 是 |

详细文档见 [../whalecloud-dev-tool-base-scripts/references/get_repo_info_readme.md](../whalecloud-dev-tool-base-scripts/references/get_repo_info_readme.md)。

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 缺少必填参数（DEMAND_DESC/DEMAND_IMPACT/PROD_FEATURE/PROD/SYNAPSE_URL/GITNEXUS_URL） | **中止**，列出缺失参数 |
| get_repo_info.py 返回 "未找到仓库信息" | **中止**，提示该产品未关联代码仓库 |
| SYNAPSE_URL 不可达或 get_doc.py 下载失败 | 若架构文档缺失则**中止** |
| GITNEXUS_URL 不可达或**所有仓库** materialize 均失败 | **中止**，不得输出无源码核验的澄清结果 |
| 部分仓库 materialize 失败 | 记录失败仓库名，后续检索跳过该仓库，涉及该仓库的分析标注 `[待补充-{REPO_NAME}仓库未获取]`，继续处理其他仓库 |
| 某仓库 search/cypher/grep 无结果 | 记录该仓库无匹配结果，继续分析其他仓库 |
| 缓存中无某文件路径 | 标 `[待代码确认]`，不得虚构内容 |
| OUTPUT_DIR 不可写 | 中止并说明 |

---

## 输出文件

- 需求澄清文档：`{OUTPUT_DIR}/{OUTPUT}`，格式参考 `templates/01-需求澄清.md`
- 记录文件：`.questions.json`（脚本同目录下）

