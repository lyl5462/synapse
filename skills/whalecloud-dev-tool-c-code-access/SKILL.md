---
name: whalecloud-dev-tool-code-access
description: "研发会议室 C++ 代码精读。执行前必须从上下文确认三要素：USER_REQUEST（用户诉求）、ENTRY_MODULE 与 REPO_NAME（二者须从产品架构/功能文档提取，禁止臆造）。在工单路径上读代码，并通过 GitNexus 图检索辅助。"
label: C++ 代码阅读
---

# C++ 代码阅读（研发会议室）

围绕**用户诉求**与**入口模块**，在工单目录中的真实 C++ 源码上做**准确、高效**的定向阅读。

> **【三要素 — 执行本技能前必须完成】**
>
> 以下三项**不是**由用户手填的参数表，而是 Agent 从**当前会话上下文 + 产品文档**中提取并**自行确认**后方可开始读码：
>
> | 要素 | 提取来源 | 要求 |
> |------|----------|------|
> | **`USER_REQUEST`** | 用户本轮/本会话诉求、委派任务说明、需求澄清结论等上下文 | 用一句话复述诉求；说不清则**中止**并向用户确认 |
> | **`ENTRY_MODULE`** | `{PRODUCT_DOC_ROOT}/产品架构/` 下 `FUNCTIONAL_ARCH.md`、`TECH_ARCH.md`（及同目录相关文档） | **必须**能在文档中找到对应功能模块/分层/目录边界；**禁止臆造**模块名 |
> | **`REPO_NAME`** | 同上产品文档（代码影响范围表中的仓库列、`仓库名:` 路径前缀、多仓说明等），并与 `{PRODUCT_CODE_ROOT}` 下实际子目录名**交叉核对** | **禁止臆造**仓库名；文档与工单目录不一致时标 `[待确认]` 并中止或请用户确认 |

`room_opened` 已将代码 clone 至工单目录、文档落至 `doc/`。GitNexus 脚本由 **`whalecloud-dev-tool-base-scripts`** 提供，通过 `run_skill_script` 跨技能调用。

## 研发会议室：工单路径（必读）

| 用途 | 路径 |
|------|------|
| 工单根 | `{WORK_ORDER_DIR}` |
| 本仓源码根 | `{PRODUCT_CODE_ROOT}/{REPO_NAME}/`（**禁止**再传 `CODE_PATH` / `GNX_CACHE_DIR`） |
| 产品架构文档 | `{PRODUCT_DOC_ROOT}/产品架构/`（`FUNCTIONAL_ARCH.md`、`TECH_ARCH.md`） |

- **读源码**：在 `{PRODUCT_CODE_ROOT}/{REPO_NAME}/` 使用 `read_file` / `list_directory` / 工作区检索；路径标注为 `{REPO_NAME}:相对路径`。
- **读架构**：只读 `{PRODUCT_DOC_ROOT}/产品架构/`，禁止重复拉取远端文档。

## 共享脚本（run_skill_script）

```text
run_skill_script(
  skill_name="whalecloud-dev-tool-base-scripts",
  script_name="gnx-tools.js",
  args=["<子命令>", ...]
)
```

在线图检索（`search` / `explore` / `impact` / `cypher`）及可选 `overview` 见 [references/gnx-tools.md](../whalecloud-dev-tool-base-scripts/references/gnx-tools.md)。**本地读文件不以 materialize 为前提**（工单已 clone）。

---

## 何时加载

- 需核验某 C++ 功能/模块实现、调用链、配置宏、接口
- 已能从上下文归纳 **`USER_REQUEST`**，且已从**产品文档**确认 **`ENTRY_MODULE`**、**`REPO_NAME`**（非臆造）
并t- 结论须含 `{REPO_NAME}:相对路径` 证据

**不必加载**：`[无代码触点]`；仅读文档不读码。

---

## Parameters

### 三要素（必填，从上下文提取确认）

| Parameter | 必填 | 说明 |
|-----------|------|------|
| `USER_REQUEST` | 是 | **从会话上下文提取**：当前要弄清的问题、变更意图、核验点。提取后须能一句话复述；无法从上下文确定则**中止**并向用户确认，不得假设诉求。 |
| `ENTRY_MODULE` | 是 | **从产品文档提取**：须在 `{PRODUCT_DOC_ROOT}/产品架构/`（及工单内其它已落盘产品文档）中查到与该模块对应的 §3 功能名、分层名或目录边界。**禁止臆造**；文档无匹配则标 `[待确认-架构未覆盖该模块]` 并中止或请用户确认。 |
| `REPO_NAME` | 是 | **从产品文档提取**：来自架构/功能文档中的仓库列、`仓库名:路径` 前缀或多仓说明；并与 `{PRODUCT_CODE_ROOT}` 下子目录名核对一致。**禁止臆造**；文档与工单 `code/` 目录不一致则**中止**或请用户确认。 |

### 环境与工具
| `GITNEXUS_URL` | 是 | GitNexus 服务根地址（用于 `search` / `explore` / `impact` / `cypher` / 可选 `overview`） |
| `WORK_ORDER_DIR` | 否 | 工单根；系统提示「产品工作区路径」注入，如 `work/<scope>/` |
| `PRODUCT_CODE_ROOT` | 否 | 默认 `{WORK_ORDER_DIR}/code` |
| `PRODUCT_DOC_ROOT` | 否 | 默认 `{WORK_ORDER_DIR}/doc` |

**内部推导（勿要求用户传入）**

- `CODE_ROOT` = `{PRODUCT_CODE_ROOT}/{REPO_NAME}/`
- 架构目录 = `{PRODUCT_DOC_ROOT}/产品架构/`

> **入口文件映射**：在 `ENTRY_MODULE`、`REPO_NAME` 均已从文档确认后，将 `ENTRY_MODULE` 转为 `ENTRY_FILES`（头文件 / 实现 / 目录前缀），路径须带文档中的 `仓库名:` 或与 `REPO_NAME` 一致的相对路径。**禁止**在无文档依据时编造路径。

---

## 核心约束

### C0. 三要素先提取、后读码（违反视为技能未执行）

- 未形成明确的 `USER_REQUEST` / `ENTRY_MODULE` / `REPO_NAME` 之前，**不得** `read_file` 源码或调用 `gnx-tools`。
- `ENTRY_MODULE`、`REPO_NAME` 须各有一条**文档出处**（文件名 + 章节/表格/原文摘录）；无出处即视为臆造。
- 允许向用户确认三要素，但**不允许**用猜测值代替文档提取结果。

### C1. 诉求驱动，入口锚定

- 阅读须能回答 `USER_REQUEST`；无关扩圈立即停止。
- 顺序：**架构入口** → `#include` 链 → 调用链（图检索 + 本地核对）→ 必要时 `search`/`cypher`。

### C2. 证据可核对

- 结论附带 **`{REPO_NAME}:相对路径`**（及符号/行号若可读）。
- 无法验证标 **`[待代码确认]`**。

### C3. C++ 专项

- 头文件优先；入口文件优先级见下表。
- 构建事实来自 `CODE_ROOT` 下 `CMakeLists.txt` / `Makefile*`。
- 影响结论的 `#ifdef` 须写明条件编译约束。

### C4. 本地读码 vs GitNexus

- **本地**：`read_file` / 工作区 `Grep` 针对 `CODE_ROOT`（工单 clone）。
- **在线**：`run_skill_script` 调用 `gnx-tools.js` 的 `search` / `explore` / `impact` / `cypher`（及可选 `overview`）。
- **禁止**为读单个文件而要求用户传缓存目录或执行 `materialize`（会议室已由 `room_opened` 提供源码）。

---

## C++ 入口文件优先级

在 `ENTRY_FILES` 对应目录下选锚点：

| 优先级 | 模式 | 说明 |
|--------|------|------|
| 0 | 架构表列出的 `.h` / `.cpp` | **最优先** |
| 1 | 入口 `.cpp` 的 `#include "..."` 头文件 | 实现入口 |
| 2 | `<Dir>/<DirName>Mgr.h` | 管理类 |
| 3 | `<Dir>/<DirName>.h` | 同名主头 |
| 4 | `Common.h` / `Base.h` | 公共基类 |
| 5 | 目录内最大 `.h` | fallback |

---

## 工作流程

```
Phase 0 — 三要素提取确认与入口锚定
  0a. 读取 {PRODUCT_DOC_ROOT}/产品架构/（及工单内相关产品文档）；**先于读码**。
  0b. **提取 `ENTRY_MODULE`**：根据 USER_REQUEST 在 FUNCTIONAL_ARCH §3、TECH_ARCH 分层/目录表中定位模块名；记录文档出处；无匹配则中止或 `[待确认]`。
  0c. **提取 `REPO_NAME`**：从该模块「代码影响范围」、路径前缀 `仓库名:`、多仓说明中取仓库名；与 list_directory({PRODUCT_CODE_ROOT}) 核对；不一致则中止或请用户确认。
  0d. **确认 `USER_REQUEST`**：从会话/委派上下文归纳一句话诉求；含糊则向用户确认后再继续。
  0e. 校验 GITNEXUS_URL、WORK_ORDER_DIR；计算 CODE_ROOT = {PRODUCT_CODE_ROOT}/{REPO_NAME}/，目录须存在且非空。
  0f. ENTRY_MODULE + 文档 → ENTRY_FILES；写入追踪表（含每条路径的文档依据）。

Phase 1 — 工程确认（可选图线索）
  1a. 在 CODE_ROOT 读 Makefile / CMakeLists.txt：TARGET、-D、-l。
  1b. （可选）overview 写本地便于对照：
        run_skill_script(..., script_name="gnx-tools.js",
          args=["overview", "--url", "{GITNEXUS_URL}", "--repo", "{REPO_NAME}",
                "--out", "{CODE_ROOT}/overview.json"])
  1c. （可选）工程类型：
        run_skill_script(..., script_name="detect-project-kind.js",
          args=["--cache", "{CODE_ROOT}", "--overview", "{CODE_ROOT}/overview.json"])
      非 cpp_native / cpp_mixed 时注明，仅对架构标注的 C++ 路径执行本流程。

Phase 2 — 入口精读（必读，本地读码）
  对 ENTRY_FILES（按入口优先级）：
  2a. read_file("{CODE_ROOT}/<相对路径>") — 禁止臆造路径。
  2b. 提取类/方法、#include、与 USER_REQUEST 相关的逻辑。
  2c. 入口为 .cpp 时，继续 read 其 `#include` 的 .h。
  2d. 诉求涉及启动/CLI 时：在 CODE_ROOT 下 Grep `int main(`（*.cpp）。
  2e. 跨目录依赖：在 CODE_ROOT 下 Grep `#include`、类名、宏名。

Phase 3 — 诉求驱动扩展（按需、早停）
  Phase 2 不足以回答时再执行：
  3a. run_skill_script(..., args=["search", "--url", "{GITNEXUS_URL}", "--repo", "{REPO_NAME}",
        "--query", "<类名/关键词>", "--limit", "15"])
  3b. run_skill_script(..., args=["explore"|"impact", ...]) — 已知符号/target。
  3c. **回到本地验证**：对图检索给出的 filePath，用 read_file 在 CODE_ROOT 下核对上下文。
  3d. 必要时 run_skill_script(..., args=["cypher", ...])，filePath 过滤入口目录前缀。
  3e. 已能回答 USER_REQUEST 即停止。

Phase 4 — 输出阅读报告
  4a. **结论摘要**：直接回答 USER_REQUEST。
  4b. **入口与调用链**：ENTRY_MODULE → 文件 → 关键调用。
  4c. **证据表**：| 结论 | REPO:路径 | 依据（read_file / Grep / gnx-tools） |
  4d. **未决项**：`[待代码确认]` / `[待确认-架构未覆盖]`。
```

---

## gnx-tools 使用范围（会议室）

| 子命令 | 会议室是否使用 | 说明 |
|--------|----------------|------|
| `read` / `grep` / `materialize` | **否**（默认） | 本地用 `read_file` / 工作区 Grep 读 `CODE_ROOT` |
| `overview` | 可选 | 辅助 explore 选 target |
| `search` / `explore` / `impact` / `cypher` | 是 | 图检索，结果须回本地 read_file 验证 |

---

## 推荐本地 Grep 模式（C++）

在 `CODE_ROOT` 下：

```text
#include\s+\"[^\"]+"
class\s+\w+(Mgr|Manager|Ctrl|Service)
#ifdef\s+_[A-Z0-9_]+
int\s+main\s*\(
```

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 三要素未提取或 `ENTRY_MODULE`/`REPO_NAME` 无文档依据 | **中止**（禁止臆造后继续读码） |
| 其它必填项缺失 | **中止** |
| `CODE_ROOT` 不存在或为空 | **中止**（工单未 clone 或未开门） |
| 架构文档缺失或 ENTRY_MODULE 无映射 | `[待确认]`，向用户确认 |
| 图检索无结果 | 记录；结论仍给出则标 `[待代码确认]` |
| 图检索路径与本地文件不一致 | 以本地 `read_file` 为准，标注差异 |

---

## Checklist

- [ ] `USER_REQUEST`、`ENTRY_MODULE`、`REPO_NAME` 已从上下文/产品文档提取并各有一条文档或会话依据（非臆造）
- [ ] `CODE_ROOT` 可访问，架构文档已从 `{PRODUCT_DOC_ROOT}/产品架构/` 读取
- [ ] `ENTRY_FILES` 已从架构导出
- [ ] 入口文件已本地精读，`#include` 链已按需展开
- [ ] 图检索结论已在 `CODE_ROOT` 本地核对
- [ ] 每条结论含 `{REPO_NAME}:路径` 证据
