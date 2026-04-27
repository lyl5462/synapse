> ⚠ **此模板已废弃**（v1.x 遗留）。请使用拆分后的双文档模板：
> - [func-arch-template.md](func-arch-template.md) — 功能架构文档（主文档）
> - [tech-arch-template.md](tech-arch-template.md) — 技术架构文档（补充文档）

---

# {{PROJECT_NAME}} — C++ 产品架构说明（已废弃，仅供历史参考）

> **文档版本**：1.0 · **生成时间**：{{GENERATED_DATE}} · **技能**：whalecloud-dev-tool-arch-create · **证据来源**：源码阅读 + 结构化代码索引（辅助）

---

## 目录

1. [产品简介](#1-产品简介)
2. [产品定位](#2-产品定位)
   - 2.1 [定位与价值主张](#21-定位与价值主张)
   - 2.2 [典型场景](#22-典型场景)
   - 2.3 [能力范围与非目标](#23-能力范围与非目标)
   - 2.4 [关键业务能力矩阵](#24-关键业务能力矩阵)
3. [仓库与工程事实](#3-仓库与工程事实)
4. [技术栈](#4-技术栈)
5. [源码佐证与关键路径](#5-源码佐证与关键路径)
6. [系统架构总览](#6-系统架构总览)
7. [分层架构详解](#7-分层架构详解)
   - 7.1 [代理层 Proxy Layer](#71-代理层-proxy-layer)
   - 7.2 [接口层 API Layer](#72-接口层-api-layer)
   - 7.3 [数据层 Data Layer](#73-数据层-data-layer)
   - 7.4 [基础层 Infrastructure Layer](#74-基础层-infrastructure-layer)
8. [运行形态与执行流](#8-运行形态与执行流)
   - 8.1 [常驻进程（Daemon）](#81-常驻进程daemon)
   - 8.2 [工具进程（Tool/CLI）](#82-工具进程toolcli)
   - 8.3 [核心执行流说明](#83-核心执行流说明)
9. [模块依赖与变更风险](#9-模块依赖与变更风险)
10. [附录](#10-附录)

---

## 1. 产品简介

{{EXEC_SUMMARY}}

> 用 5～10 句说明：**解决什么问题**、**主要交付形态**（服务 / CLI / 库）、**技术主路径**、**当前最大风险或约束**。避免罗列内部指标数字。

---

## 2. 产品定位

### 2.1 定位与价值主张

{{PRODUCT_POSITIONING}}

<!-- 回答：为谁、解决什么痛点、与常见替代方案相比的取舍；可引用 README 或用户表述 -->

### 2.2 典型场景

{{USER_SCENARIOS}}

<!-- 表格：场景 | 面临问题 | 产品作用（结合产品特性自动营造场景，说明该场景中常见问题以及产品能发挥的作用） -->

### 2.3 能力范围与非目标

{{SCOPE_AND_NON_GOALS}}

### 2.4 关键业务能力矩阵

{{CAPABILITY_MATRIX}}

<!-- 示例（按产品语言，非图数据库字段名）：
| 能力 | 用户可感知结果 | 主要实现位置（文件/包） | 成熟度/备注 |
|------|----------------|-------------------------|-------------|
| … | … | `src/...` | … |
-->

---

## 3. 仓库与工程事实

### 3.1 README / 清单摘要

{{README_PACKAGE_SUMMARY}}

<!-- 基于对 README、package.json / pyproject / go.mod 等的实际阅读；说明入口脚本、主要 workspace、构建与运行命令 -->

### 3.2 目录与边界（来自源码树）

{{REPO_LAYOUT_NOTES}}

<!-- 顶层目录职责一句话；指出「核心业务」「适配外部系统」「测试与工具」各自落在哪些路径 -->

---

## 4. 技术栈

### 4.1 语言分布

{{TECH_STACK_TABLE}}

### 4.2 关键框架与依赖

{{FRAMEWORKS_TABLE}}

### 4.3 技术栈依赖图

<!-- ⚠ 必须调用 whalecloud-dev-tool-excalidraw 生成此图，不可用 Mermaid 文字块或描述性文字替代。
     调用时提供的描述内容：
       - 图类型：技术栈依赖关系（flowchart / layered）
       - 节点来源：Phase 1b 步骤 A 读到的构建文件（Makefile/CMakeLists/go.mod/package.json 等）
       - 节点只能使用源码中真实出现的库/框架/语言名称，不得编造
     图下方一句「图示来源」说明对应的源码路径。
-->

{{DIAGRAM_TECH_STACK}}

---

## 5. 源码佐证与关键路径

本节以**真实文件与符号**支撑上文结论，避免仅引用统计数字。

### 5.1 入口与启动路径

{{SOURCE_ENTRYPOINTS}}

<!-- 列出：主入口文件、bootstrap、HTTP listen、CLI main；每处 1～2 句 + 路径 -->

### 5.2 代表性实现摘录（设计意图说明）

{{SOURCE_SNIPPETS_ANALYSIS}}

<!-- 对 arch-data（若使用 --with-snippets）或你亲自 Read 的片段：说明「这段代码如何体现分层/业务规则/错误处理策略」，勿大段无注释粘贴 -->

---

## 6. 系统架构总览

### 6.1 分层架构概览图

<!-- ⚠ 必须调用 whalecloud-dev-tool-excalidraw 生成此图，不可用 Mermaid 文字块或描述性文字替代。
     调用时提供的描述内容：
       - 图类型：系统分层架构（layered architecture）
       - 层名称来自源码目录实际结构（非索引聚类分类）
       - 连线方向来自 #include / import 关系（Phase 1b 步骤 D Grep 验证）
       - 若 arch-data.json 中 indexQuality.clusterCollapseDetected=true，
         必须忽略 layeredClusters，改用 sourceScan.subDirectories 派生分层
     图下方一句「图示来源」说明对应的源码路径证据。
-->

{{DIAGRAM_SYSTEM_OVERVIEW}}

### 6.2 架构设计说明（结合代码依赖方向）

{{ARCHITECTURE_RATIONALE}}

<!-- 说明依赖方向、同步/异步边界、与部署单元（进程、容器）的对应关系；与第 5 节呼应 -->

---

## 7. 分层架构详解

### 7.1 代理层 Proxy Layer

**职责**：{{LAYER_PROXY_INTENT}}

**包含模块**：

{{LAYER_PROXY_CONTENT}}

**关键设计决策**：

{{LAYER_PROXY_DECISIONS}}

---

### 7.2 接口层 API Layer

**职责**：{{LAYER_API_INTENT}}

**包含模块**：

{{LAYER_API_CONTENT}}

**关键接口列表**：

{{LAYER_API_ENDPOINTS}}

---

### 7.3 数据层 Data Layer

**职责**：{{LAYER_DATA_INTENT}}

**包含模块**：

{{LAYER_DATA_CONTENT}}

**数据模型概要**：

{{DATA_MODELS}}

---

### 7.4 基础层 Infrastructure Layer

**职责**：{{LAYER_INFRA_INTENT}}

**包含模块**：

{{LAYER_INFRA_CONTENT}}

---

## 8. 运行形态与执行流

### 8.1 常驻进程（Daemon）

{{DAEMON_PROCESSES}}

---

### 8.2 工具进程（Tool/CLI）

{{TOOL_PROCESSES}}

---

### 8.3 核心执行流说明

{{EXECUTION_FLOWS_DETAIL}}

<!-- 基于入口文件实际调用序列描述核心业务流程：用户动作 → 系统步骤 → 关键符号与文件；步骤表优先于抽象描述 -->

---

## 9. 模块依赖与变更风险

### 9.1 模块间依赖概览

{{MODULE_DEPENDENCY_TABLE}}

### 9.2 高扇入模块（变更需谨慎）

{{HIGH_RISK_MODULES}}

> **说明**：高被依赖模块修改前应做**调用方与数据契约**梳理；若有代码图谱工具，可辅助做影响分析，但结论须与源码核对。

---

## 10. 附录

### 10.1 工程度量（仅供参考）

以下数字仅反映索引时的快照，**不能替代**对源码与行为的设计判断。

| 指标 | 数值 |
|------|------|
| 符号规模（函数/类/方法等） | {{METRICS_SYMBOLS}} |
| 关系统模 | {{METRICS_RELATIONS}} |
| 执行流条数 | {{METRICS_PROCESSES}} |
| 功能域（聚类）数量 | {{METRICS_CLUSTERS}} |
| 常驻 / 工具进程（启发式分类） | {{METRICS_DAEMONS}} / {{METRICS_TOOLS}} |

### 10.2 架构决策记录（ADR）

{{ADR_LIST}}

### 10.3 已知技术债务

{{TECH_DEBT}}

### 10.4 演进建议

{{RECOMMENDATIONS}}

### 10.5 数据采集说明（内部）

- **结构化索引服务**：`{{GITNEXUS_URL}}`（仅团队内部部署时使用）
- **索引中的仓库名**：`{{PROJECT_NAME}}`
- **原始采集文件**：`arch-data.json`（与本文档同目录时可附）
- **采集命令**：`node scripts/fetch-arch-data.js --url <URL> --repo <NAME>`；需要符号正文片段时加 `--with-snippets`

---

*本文档以产品与可维护性读者为主；工程度量为附录，源码阅读为论证主体。*
