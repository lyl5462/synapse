---
name: whalecloud-dev-tool-arch-create
description: "通用产品架构/技术架构文档生成技能（源码优先 + GitNexus 索引辅助）。支持多仓库产品协同分析与跨仓一致性核对；按仓库语言与构建体系自动匹配分析流程；C++ 仓库启用附录专项阅读。产出 FUNCTIONAL_ARCH + TECH_ARCH，功能文档含「遗漏功能/清单外能力」章节供产品侧补充。Examples: 多仓产品写架构说明、梳理分层与执行流、结合图谱写技术架构。"
label: 产品架构文档生成工具
---

# 产品架构文档生成（源码优先 · GitNexus 辅助）

生成**两份互不交叉**的交付：`FUNCTIONAL_ARCH.md`（功能架构）与 `TECH_ARCH.md`（技术架构）。叙述以**真实源码**为主，**GitNexus**（`gitnexus serve`）仅作入口定位、执行流与模块划分线索；不在正文反复出现工具品牌。

**语言与工程类型**：默认**不**假设仓库为 C++。必须先执行 **Phase 0.1 工程类型判定**，得到 `PROJECT_KIND` 后再选用对应的 Phase 1b 阅读策略；若判定为 **C++ 原生或 C++ 混合主体**，必须叠加 **附录 A** 中的 C++ 专项要点。

> **核心约束（违反则文档不完整）**
> 1. **图示交付与技能挂载一致（Phase 0e 判定 `DIAGRAM_MODE`）**：执行本技能前，根据 system 提示中「研发工具技能指引」是否包含 **`whalecloud-dev-tool-excalidraw`** 技能块（存在 `### 研发技能：whalecloud-dev-tool-excalidraw` 即为已挂载）选择模式：
>    - **`DIAGRAM_MODE=excalidraw`（已挂载）**：技术架构 §3.3、§4.1 必须通过 **whalecloud-dev-tool-excalidraw** 规范生成 **`tech-stack.excalidraw`**、**`sys-arch-layers.excalidraw`** 至 **OUTPUT_DIR**，并在 `TECH_ARCH.md` 中引用；**不得**仅用 Mermaid 替代这两份独立 JSON 交付物。
>    - **`DIAGRAM_MODE=mermaid`（未挂载）**：**不得**创建 `sys-arch-layers.excalidraw`、`tech-stack.excalidraw` 或任何图示用 `.excalidraw`；技术架构 §3.3、§4.1 **必须**各含至少一个可渲染的 ```mermaid 代码块（技术栈依赖图一张、分层总览一张），节点/层名须来自 Phase 1b 真实源码证据，图下附「图示来源」与路径；**禁止**在无该技能时手写 Excalidraw JSON。
> 2. **源码必须直接读取**：不能仅依赖索引快照；Phase 1b 必须读取与 `PROJECT_KIND` 匹配的**代表性源文件**（入口、构建清单、典型模块），文档中有源码路径论据。
> 3. **索引仅作定位辅助**：聚类在 embeddings=0 时不可靠，必须以源码与构建事实为准，**不得将索引分层结果不经源码验证写入文档**。
> 4. **双文档输出，内容不交叉**：功能架构文档（FUNCTIONAL_ARCH.md）不包含技术栈/分层图/运行态；技术架构文档（TECH_ARCH.md）不重复产品定位/场景/业务能力描述。
> 5. **核心功能列表必须全覆盖**：用户传入的 `CORE_FEATURES` 中每一项都必须出现在功能架构文档 §3 中，且含代码影响范围（文件级别）；多仓库时路径须标注 **`仓库名:`** 前缀。
> 6. **多仓库协同（与研发手册思路一致）**：当 `|GNX_REPO_LIST| > 1` 时，**每个仓库**独立 `materialize` / `GNX_CACHE_DIR`；凡结论涉及路径、API、配置、执行流，须在对应仓缓存上 **read/grep** 留证。**跨仓库**须写清集成证据（URL、proto、客户端、消息、DB 等）与**术语/接口前缀一致性**；证据不足标 `[待源码确认]`，禁止单仓推断他仓行为。
> 7. **遗漏功能分析为必选章节**：只要生成功能架构主文档，**§4「遗漏功能与清单外能力分析」**须按 `func-arch-template.md` 填满；用于暴露源码中已存在但未列入 `CORE_FEATURES` 的能力，并给出**产品管理人员待办**。未传 `CORE_FEATURES` 时该节改为「候选核心能力清单（待产品确认）」。

## 共享脚本（run_skill_script）

凡调用 `get_repo_info.py`、`get_doc.py`、`gnx-tools.js`、`fetch-arch-data.js`、`detect-project-kind.js`，一律通过：

```text
run_skill_script(
  skill_name="whalecloud-dev-tool-base-scripts",
  script_name="<文件名>",
  args=[...]
)
```

详见 `whalecloud-dev-tool-base-scripts` 技能 SKILL.md。本技能（arch-create）目录下**不再**提供上述脚本的副本。

## Parameters

与 `whalecloud-dev-tool-development-manual` 对齐的命名；其中 **`OUTPUT_DIR` / `OUTPUT` 在 Synapse 产品知识生成链路中与 `src/synapse/api/routes/dev_iwhalecloud_knowledge.py` 的落盘逻辑一致**。GitNexus 缓存只暴露 **`GNX_CACHE_DIR`**（与 `_gitnexus_local_data_path` 一致），不再单独引入 `TMP_DIR` 变量——二者在路径上本就不同层级，统一用 **`GNX_CACHE_DIR` + `OUTPUT_DIR`** 即可覆盖全部落盘语义。

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `GITNEXUS_URL` | 是 | GitNexus 服务根地址（`gitnexus serve`），如 `http://127.0.0.1:11011` |
| `SYNAPSE_URL` | 条件 | SynapseService 地址（`IP:PORT`，**无 `http://` 前缀**）。当需要通过脚本按产品拉取关联仓库列表时**必填**；若调用方已显式给出唯一 `REPO_NAME`（如 HTTP 任务注入），可省略 |
| `PROD` | 条件 | 产品名称。与 `SYNAPSE_URL` 同时出现时，用于 `get_repo_info.py`，**不得手填 `REPO_NAME` 替代接口结果** |
| `REPO_NAME` | 条件 | GitNexus 图谱中的仓库名。**优先**由 `run_skill_script(..., script_name="get_repo_info.py", args=["--server-url", "{SYNAPSE_URL}", "--prod", "{PROD}"])` 解析得到列表 `GNX_REPO_LIST`（多仓时逐项处理）；若用户/请求体已给出确定仓库名且无产品拉仓需求，可视为单元素列表 |
| `OUTPUT_DIR` | 否 | 架构文档产出目录（`FUNCTIONAL_ARCH.md`、`TECH_ARCH.md`、`.excalidraw` 等）。**Synapse 内置任务**下等价于 `_knowledge_docs_root(doc_type, prod_name)`，即 `{SYNAPSE_HOME}/tmp/docs/<prod_name>/<doc_type>/`；Cursor 独立执行时由用户指定或使用团队约定目录 |
| `OUTPUT` | 否 | **必选文件**：`FUNCTIONAL_ARCH.md`、`TECH_ARCH.md`。**条件文件**：仅当 **`DIAGRAM_MODE=excalidraw`**（已挂载 `whalecloud-dev-tool-excalidraw`）时，还须写入 `sys-arch-layers.excalidraw`、`tech-stack.excalidraw`（与 `dev_iwhalecloud_knowledge.py` 读取逻辑一致）。**`DIAGRAM_MODE=mermaid` 时不创建**上述 `.excalidraw`，图示仅写入 `TECH_ARCH.md` 的 Mermaid 代码块 |
| `GNX_CACHE_DIR` | 是（每仓） | 该仓库的 materialize 根；**read/grep 仅访问其下 `files/`**。`gnx-tools.js` 的 `--cache` 必须指向此目录。**Synapse 内置任务**下为 `{SYNAPSE_HOME}/tmp/gitnexus/<REPO_NAME>/`（`_gitnexus_local_data_path`）。**独立 Cursor / 研发手册式流程**下由调用方显式给定目录（常见：工作区下 `.gnx-cache/<REPO_NAME>/` 或团队约定的绝对路径），不要求再套一层「临时根」变量名 |
| **工作区仓库根** | — | 当前 Cursor 打开的 Git 工作区根。用于判断「源码是否在本地」：`arch-data.json` 的 `repoPath` 若为本机路径且落在该根下，则优先 **Read/Grep**；否则以 `GNX_CACHE_DIR` + `gnx-tools.js read|grep` 为主 |
| `PROJECT_KIND` | — | Phase 0.1 输出，如 `cpp_native` / `python` / `node_ts` / `go` / `jvm` / `mixed_polyglot` 等 |

### 仓库列表获取（禁止拍脑袋写 `REPO_NAME`）

```text
run_skill_script(
  skill_name="whalecloud-dev-tool-base-scripts",
  script_name="get_repo_info.py",
  args=["--server-url", "<SYNAPSE_URL>", "--prod", "<PROD>"]
)
```

- 解析标准输出中 `一共有N个仓库：REPO1,REPO2,...`，得到 `GNX_REPO_LIST`。
- 若输出含 `未找到仓库信息` / `未找到有效的仓库 URL`：**中止**并提示检查 `PROD` / `SYNAPSE_URL`。
- 平台 Python 选择：优先 `python3`，否则 `py`（Windows），再否则 `python`（与研发手册一致）。

### Phase 0.1 — 工程类型判定（必选，先于 Phase 0.5 / 1b）

目标：在**不臆测**的前提下，综合 **(1) 仓库内相对路径与扩展名**、**(2) materialize 缓存中的文件分布**、**(3) GitNexus 结构化信号**，得到 `PROJECT_KIND` 与置信度，并据此选择 Phase 1b 的「入口文件 / 构建清单 / 依赖验证」清单。

**推荐自动化（Cursor 终端）**：

```text
run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="detect-project-kind.js", args=["--cache", "<GNX_CACHE_DIR>", "--overview", "<GNX_CACHE_DIR>/overview.json"])
```

脚本输出 JSON 字段 `projectKind`、`confidence`、`signals`、`extHistogramTop`。将其映射为内部变量：

| `projectKind` | 含义 | Phase 1b 主策略摘要 |
|----------------|------|---------------------|
| `cpp_native` | C/C++ 为主体 + CMake/Makefile 等 | **附录 A 全文启用**（头文件入口、#include、#ifdef、Makefile 目标） |
| `cpp_mixed` | C++ 与脚本/其他语言并存 | C++ 部分走附录 A；其余语言按该语言惯例读入口与包清单 |
| `python` | Python 为主体 | `pyproject.toml`/`requirements.txt`、包布局、`__main__.py` 或 WSGI/ASGI 入口、关键模块 |
| `node_ts` | Node/TS 为主体 | `package.json`、workspace、主要 `src/` 入口、框架约定目录 |
| `go` | Go | `go.mod`、`main` 包、cmd/、internal/ |
| `jvm` | Java/Kotlin | `pom.xml`/`build.gradle`、多模块目录、Spring/Boot 入口若存在 |
| `dotnet` | .NET | `.sln`/`.csproj`、`Program.cs` 等 |
| `rust` | Rust | `Cargo.toml`、bin/lib 目标 |
| `mixed_polyglot` | 无单一主导 | 显式列出前 3～5 种扩展名占比，**与用户确认**后再定主语言；未确认前以 **`CODE_PATH`（若传入）下目录体量** 与 README（若存在）为「主线索」 |

**GitNexus 侧信号（在脚本之后人工吸收）**：

- `node ... gnx-tools.js overview ...` 的 clusters/processes：用于**命名空间/子系统**线索，不得单独作为分层依据。
- `arch-data.json`（若已跑 `fetch-arch-data.js`）中的 `suggestedSourceFiles`、`layeredClusters`：用于**补全路径前缀**与候选入口，与扩展名统计交叉验证。

**置信度规则**：`confidence < 0.55` 时，在文档 §0 或技术架构 §2 增加一句「工程类型判定为弱信号，已结合 **用户 `CODE_PATH` / 产品说明**（及仓库 README，若存在）采用 **{PROJECT_KIND}** 流程」，并列出 2～3 条证据。

### GitNexus 取数标准流程（与 Nexus / gitnexus-web Backend 对齐）

本技能**不再**以 PowerShell 拼 `Invoke-WebRequest` 或 MCP 流式接口作为默认取数方式。一律使用 **`run_skill_script(..., script_name="gnx-tools.js", args=[子命令, ...])`**（七子命令 + `materialize`），底层与 Nexus 一致：

| 子命令 | REST / 行为 | 说明 |
|--------|----------------|------|
| `materialize` | `GET /api/graph` + 按需 `GET /api/file` | **一次性**把文件正文落到 `--cache/files/`，并写 `cache/manifest.json`；可加 `--verbose` 与 `--progress-every N` 输出进度 |
| `cypher` | `POST /api/query` `{ cypher, repo }` | 与 gitnexus-web `createHttpExecuteQuery` 同源 |
| `search` | `POST /api/search` `{ query, limit, repo }` | 与 `createHttpHybridSearch` 同源 |
| `read` | **仅读 `--cache/files`** | 不打 GitNexus；无缓存则先 `materialize` |
| `grep` | **仅在 `--cache/files` 内正则** | 不打 GitNexus |
| `overview` | 固定 4 条 Cypher → `/api/query` | 与 Nexus `overview` 工具语义对齐；**推荐** `--out <path>` 直接写 UTF-8 JSON（避免 PowerShell `>` 默认 UTF-16 导致 `detect-project-kind` 解析失败） |
| `explore` | 简化 Cypher → `/api/query` | 用于定位符号/簇/流程；复杂 drill-down 可改用 `cypher` |
| `impact` | 简化 1-hop → `/api/query` | 快速上游/下游；深度分析可改用 `cypher` |

**与 Nexus「七工具」的对应关系（避免误解）**：

- **`gnx-tools.js` 与 gitnexus-web 对齐的在线子命令共 7 个**：`cypher`、`search`、`read`、`grep`、`overview`、`explore`、`impact`（均走 REST `/api/query` 或 `/api/search`，`read`/`grep` 读本地 `--cache`）。
- **`materialize`** 是额外的**离线批量**步骤（`GET /api/graph` + `GET /api/file`），常与上述七子命令**组合**使用，但语义上不算「第八个同名 Nexus 按钮」；文档里习惯与七子命令并列称为「技能取数工具集」。
- **`fetch-arch-data.js` 一次运行并不会**在进程内依次调用上述 7 个子命令；它固定拉取 **`GET /api/repo`、`/api/clusters`、`/api/processes`**，并走 **MCP `query` 多轮**。其中 **`/api/clusters`/`/api/processes` 若返回空数组**，会自动尝试合并**同目录**下由 `gnx-tools overview --out` 生成的 **`overview.json`**（与 Cypher 概览一致），也可用 **`--merge-overview <path>`** 显式指定，**`--no-auto-overview`** 可关闭自动合并。

**参数约定**：`--url` 为 `gitnexus serve` 根（如 `http://127.0.0.1:11011`），`--repo` 与代码图谱嵌入参数一致（**须与 `get_repo_info.py` 或请求体解析结果一致**，不得手编）；`--cache` 即本技能的 **`GNX_CACHE_DIR`**（每仓库一个 materialize 根，与 **`OUTPUT_DIR`** 分离）。

**完整用法**：`get_skill_info("whalecloud-dev-tool-base-scripts")` 内 `references/README-GNX-TOOLS.md`。

## 多仓库协同（产品关联性 · 一致性）

思路对齐 **`whalecloud-dev-tool-development-manual`**：产品可由**多个 Git 仓库**组成，分析时**按仓循环**取数，再在**产品层**聚合。实现上须同时保证：

1. **关联性（为何这些仓同属本产品）**  
   - 以 `PRODUCT_DESC` 与 `get_repo_info.py` 得到的 **`GNX_REPO_LIST`** 为边界，不擅自增减仓库。  
   - 从**配置、启动链、对外路由、proto/OpenAPI、消息消费、DB 访问串**中找**跨仓调用或数据流**，每条结论附带 **`仓库名:仓库内相对路径`** 证据。  
   - 单仓 HTTP 任务若只注入一个 `REPO_NAME`：仍须在文档中声明「当前任务单仓」；若产品实际多仓，应提示产品侧补充 `PROD`+`SYNAPSE_URL` 拉全量仓后再生成。

2. **一致性（多仓拼装是否自洽）**  
   - **术语**：同一业务概念在不同仓的类名/配置键/接口路径是否冲突或重复实现。  
   - **契约**：API 版本前缀、错误码区间、gRPC package 名是否对齐；发现分叉须写入功能架构 §4 或技术架构 §2.4 的「待确认」表。  
   - **证据规则**：与研发手册相同——**跨仓结论必须在各相关仓分别 grep/read 命中至少一条**，不得从一仓猜另一仓。

3. **与 `CORE_FEATURES` 的关系**  
   - 若某条核心功能跨仓：`§3` 中该条须拆子段落或表格列写清「仓 A / 仓 B 各自职责」。  
   - **§4 遗漏功能分析**须扫描**所有已缓存仓**，避免只扫主仓导致清单外能力漏报。

> 若缺少 URL / 仓库名，向用户确认。若用户**只要产品/源码文档**、无索引服务，可跳过 Phase 1 的脚本，仅做 Phase 1b～2（须明确说明「未使用结构化索引」）。

## 用户可选传入信息（优先级最高）

用户可在调用技能时一次性传入以下补充信息，**一旦传入则优先级高于源码推断和索引信号**：

### 1. 产品描述信息 `PRODUCT_DESC`

用户对产品的主要说明、关键入口和核心功能概述。

**处理规则**：
- 将产品描述作为 **Phase 2b 产品定位分析的第一手依据**，不得与源码结论产生矛盾（如有矛盾须显式标注）
- 从产品描述中提取：产品目标、面向用户/系统、主要功能边界、关键交互入口
- 在功能架构文档 §1 产品简介、§2 产品定位中**以产品描述为基础**展开，源码作为支撑论据
- 若产品描述与源码不符，优先采用产品描述，并在对应段落注明「[源码待确认：xxx]」

### 2. 代码相对路径 `CODE_PATH`

用户指定的仓库内代码相对路径（可以是目录或文件），指向核心代码所在位置。

**处理规则**：
- **Phase 1b 的源码阅读必须优先从用户指定路径开始**，再扩展到其他目录
- 若用户指定了目录，该目录下的所有子目录都必须在步骤 B 中覆盖
- 若用户指定了文件，该文件必须在步骤 C 中直接读取（不做猜测）
- 无论源码在本地还是仅存在于 GitNexus：无克隆时用 **`gnx-tools` 缓存 + read/grep**；有本地工作区时用 Cursor **Read/Grep**
- 未指定路径时，按技能默认的目录扫描策略执行
- **多仓库**：若各仓有独立 `CODE_PATH` 提示，按仓记录 `REPO_NAME → CODE_PATH`；若仅有一条全局 `CODE_PATH`，默认视为**主仓或用户指定的优先仓**的路径，其余仓仍须完整执行 Phase 0.5 / 1b 默认扫描，不得省略。
- **文档中的「仓库根 / 叙述边界」**：以用户传入的 **`CODE_PATH`**（及其向上追溯到的构建清单，如 `Makefile.incl.common`）为**主锚点**；许多工程**没有**仓库根 `README*`，属正常现象，**不得**因缺少根 README 判为数据缺口；仅在存在时作为产品简介的补充证据

### 3. 核心功能列表 `CORE_FEATURES`

用户预先定义的产品核心功能项列表，每项包含功能名称（和可选的简要说明）。

**处理规则（贯穿所有 Phase）**：

#### Phase 1b 中：
- 步骤 B/C/D 的源码阅读**必须以覆盖所有核心功能项为目标**，对每个核心功能项单独做 Grep 和文件追踪
- 每个功能项完成后，记录其**代码影响范围（文件级别）**：涉及哪些源文件（扩展名依 `PROJECT_KIND` 而定）
- 若某功能项在源码中无法找到对应实现，须明确标记「[待源码确认：xxx]」

#### Phase 2 中：
- 功能架构的能力矩阵（§2.4）和核心功能详解（§3）**必须以核心功能列表为骨架**，每项都必须出现
- 分层架构分析时，对每一层**重点说明承载了哪些核心功能**
- 运行态与执行流中，**对每个核心功能项都要描述其执行路径**（若代码支撑不足则标注）

#### Phase 4 输出中：
- 功能架构文档 §3 核心功能详解：逐项展开，包含「功能说明」和「代码影响范围（文件列表）」
- 功能架构文档 **§4 遗漏功能与清单外能力分析**：见核心约束 §7；`CORE_FEATURES` 为空时改填「候选核心能力清单」
- 技术架构文档中的分层描述：注明每层承载哪些核心功能项；**§2.4** 填写多仓组成与跨仓关联（单仓写不适用）

---

**用户传入信息的记录方式**：在 Phase 开始前，将用户传入信息整理为内部变量：
```
PRODUCT_DESC = <用户传入的产品描述>
CODE_PATH    = <用户传入的代码路径，若无则为空；多仓时可扩展为 (REPO, PATH) 列表或主仓单路径>
CORE_FEATURES = [
  { name: "功能1", desc: "..." },
  { name: "功能2", desc: "..." },
  ...
]
GNX_REPO_LIST = <get_repo_info 输出或请求体解析得到的仓库名数组>
```

### 源码访问方式判断（必须在 Phase 1b 前确认）

源码可能不在本地工作区，须先判断如何访问：

| 场景 | 判断依据 | 源码读取方式 |
|------|---------|------------|
| 源码在本地工作区 | `arch-data.json` 中 `repoPath` 指向本机路径，且路径实际存在 | 直接使用 Cursor **Read / Grep** 工具 |
| 本机无克隆（常见） | 不在本地拉仓库 | **必须先**执行 `gnx-tools.js materialize`；Phase 1b 用 **`node ... read --cache ... --path 相对路径`** 与 **`node ... grep --cache ...`**，避免高频 `GET /api/file` |
| 缓存未覆盖的个别文件 | `read` 提示 not in cache | `materialize` 默认不设文件上限，若仍缺失，可重跑 `materialize`（无需 `--max-files`）或在本任务中追加一次定向拉取（仍通过 `materialize`，**禁止**手写 PowerShell 调 `/api/file`） |

> ⚠ GitNexus 的 `/api/mcp` 仍可用于 Cursor 已注册 MCP 的高级场景，但**本技能默认取数不依赖 MCP**。Phase 1b 的「读文件 / 文本过滤」以 **`gnx-tools.js read|grep` + 本地 cache** 为主。

> ⚠ **`/api/file` 限制**：该端点**不支持目录路径**（传目录路径会返回 `EISDIR` 错误）；也**没有 `/api/tree` 端点**（返回 404）。无法通过 REST API 直接列出目录文件列表，需要从 `arch-data.json` 的 `suggestedSourceFiles`/`queryResults` 中提取文件路径，或直接猜测文件路径。

> ⚠ **远程仓库路径前缀发现**：`repoPath` 为远程绝对路径（如 `C:\Users\jetlin\gitnexus_code\ZMDB`），但 `/api/file` 使用的是**仓库内相对路径**。相对路径的正确前缀须从 `arch-data.json` 的 `suggestedSourceFiles` 或 `queryResults` 中提取（如 `BackServiceCpp/src/cpp/Zmdb/`），**不要假设相对路径直接从目录名开始**。提取方式：
```javascript
// find-paths.js（独立 JS 文件，避免 PowerShell 转义问题）
const d = require('./arch-data.json');
const paths = new Set();
function extractPaths(obj) {
  if (typeof obj === 'string') {
    const m = obj.match(/[\w./\\-]+\.(h|hpp|hh|cpp|cc|cxx|c|py|go|java|kt|ts|tsx|js|cs|rs)/g);
    if (m) m.forEach(p => paths.add(p));
    return;
  }
  if (Array.isArray(obj)) { obj.forEach(extractPaths); return; }
  if (typeof obj === 'object' && obj) Object.values(obj).forEach(extractPaths);
}
extractPaths(d.queryResults);
if (d.suggestedSourceFiles) d.suggestedSourceFiles.forEach(f => paths.add(f));
console.log([...paths].filter(p => p.includes('/')).sort().join('\n'));
```
运行：`node find-paths.js` 即可获取所有已知文件路径，从中推断仓库路径前缀。

> ⚠ **PowerShell 处理大 JSON 极慢**：`arch-data.json`（3000+ 行）用 `ConvertFrom-Json` 可能需要 60+ 秒。**应始终用 `node` 处理 JSON**：将逻辑写入独立 `.js` 文件后执行 `node xxx.js`，避免在 PowerShell 的 `-e` 参数中写复杂 JS（会有引号/转义问题）。

## Workflow

```
Phase 0 — 用户传入信息整理（必选，首先执行）
  0a. 解析用户消息，提取以下内容（若未提供则记为空）：
      - PRODUCT_DESC：产品描述信息（主要说明、关键入口、功能概述）
      - CODE_PATH：代码相对路径（目录或文件）
      - CORE_FEATURES：核心功能列表（逐项记录名称和说明）
      - PROD、SYNAPSE_URL、GITNEXUS_URL、OUTPUT_DIR、OUTPUT、各仓 **GNX_CACHE_DIR**（若用户/系统提示已给出则记录；未给出时按「Parameters」表或 Synapse 注入路径推导）
  0b. **仓库名解析（禁止手写猜测）**：
      - 若同时有 **PROD + SYNAPSE_URL**：必须执行
        `run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="get_repo_info.py", args=["--server-url", "<SYNAPSE_URL>", "--prod", "<PROD>"])`
        → 得到 `GNX_REPO_LIST`；后续每个仓库使用各自的 `GNX_CACHE_DIR`。
      - 若仅有单仓上下文（如 API 已注入 **REPO_NAME**）：`GNX_REPO_LIST = [该 REPO_NAME]`，仍须与 GitNexus `--list` 或接口结果核对拼写。
  0c. 将 CORE_FEATURES 展开为追踪表格，用于 Phase 1b 逐项打勾：
      | 功能名称 | 状态 | 涉及文件（Phase 1b 填入） | 备注 |
      |---------|------|--------------------------|------|
      | 功能1   | 待追踪 | — | — |
      ...
  0d. 若 CODE_PATH 非空，标记为「指定入口目录/文件」，Phase 1b 步骤 B/C 优先从此处开始。
  0e. **图示模式判定（必选）**：若 system 提示「研发工具技能指引」中包含 **`whalecloud-dev-tool-excalidraw`** 的技能正文块，则记 **`DIAGRAM_MODE=excalidraw`**；否则 **`DIAGRAM_MODE=mermaid`**。后续 Phase 3 仅允许执行对应分支，**禁止混用**（例如在 mermaid 模式下仍写 `.excalidraw`）。

Phase 0.1 — 工程类型判定（必选，可与 0.5b 顺序微调）
  0.1a. 若尚未有缓存：先执行下方 Phase 0.5b `materialize`（至少需要 `cache/files` 才能跑检测脚本）。
  0.1b. `run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="detect-project-kind.js", args=["--cache", "<GNX_CACHE_DIR>", "--overview", "<GNX_CACHE_DIR>/overview.json"])`
        → 解析 JSON，写入内部变量 `PROJECT_KIND`、`KIND_CONFIDENCE`、`KIND_SIGNALS`。
  0.1c. 将 `PROJECT_KIND` 与用户 **`CODE_PATH` / 产品说明** 及 README（若存在）对照；冲突时以**用户明确说明**为准，并在文档中注明依据。
  0.1d. 若 `PROJECT_KIND` 为 `cpp_native` 或 `cpp_mixed`：在后续 Phase 1b **必须执行附录 A**；其他语言按上表「主策略摘要」执行，不得套用 C++ 头文件猜测规则。

Phase 0.5 — GitNexus 缓存与 Nexus 对齐取数（有索引且要写技术/功能架构时 **必选**）
  0.5a. 为 `GNX_REPO_LIST` 中**每个** `REPO_NAME` 确定 **`GNX_CACHE_DIR`**（Synapse 内置任务下即 `tmp/gitnexus/<REPO_NAME>/`；独立 Cursor / 研发手册式流程下由调用方显式给定，常见 `.gnx-cache/<REPO_NAME>/`）。**禁止**把架构产出写到 `GNX_CACHE_DIR`（架构只进 **OUTPUT_DIR**）。
  0.5b. **按仓库循环**：
        `run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="gnx-tools.js", args=["materialize", "--url", "<GITNEXUS_URL>", "--repo", "<REPO_NAME>", "--cache", "<GNX_CACHE_DIR>", "--concurrency", "8"])`
        → 本地 `<GNX_CACHE_DIR>/files/**` 与 `manifest.json`（后续 **read/grep 只走本地**）。
        ⚠ **不要加 `--max-files` 限制**：默认不限文件数量，确保缓存覆盖仓库全量源文件，避免后续 `read: not in cache` 错误。仅在网络极慢或磁盘空间受限时才临时加上 `--max-files N`。
  0.5c. 结构化总览（可选，**每仓**，须 `--out`）：
        `run_skill_script(..., script_name="gnx-tools.js", args=["overview", "--url", "...", "--repo", "<REPO_NAME>", "--out", "<GNX_CACHE_DIR>/overview.json"])`
        **⚠ 仓库不存在处理**：
        - 若 `materialize` 报错"仓库不存在"或类似信息（404 / not found），**不要直接跳过**。
        - 应立即使用 `get_repo_info.py` 到服务端查询仓库列表：
          `run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="get_repo_info.py", args=["--url", "<GITNEXUS_URL>", "--output", "<GNX_CACHE_DIR>/repo_list.json"])`
        - 读取 `repo_list.json`，按**前缀匹配**（模糊匹配）找到实际存在的仓库名（如 `REPO_NAME=whalecloud-user` 匹配到 `whalecloud-user-service`）。
        - 用正确的仓库名**重新执行** `materialize`。
  0.5d. 按需：`search` / `explore` / `impact` / `cypher`（均通过 `gnx-tools.js` + `args` 数组调用）。

Phase 1 — 结构化信号采集（可选，与 Phase 0.5 互补，run fetch-arch-data.js）
  1. **按仓库循环**（或选定主仓后再单跑），示例：
        run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="fetch-arch-data.js", args=["--url", "<GITNEXUS_URL>", "--repo", "<REPO_NAME>", "--out", "<OUTPUT_DIR>/arch-data-<REPO_NAME>.json", "--with-snippets", ...])
     （⚠ 使用绝对路径；Windows 下不支持 && 链式命令，须用绝对路径或 working_directory 参数）
     → arch-data.json（clusters/processes/query 命中路径；--with-snippets 含符号正文片段）
     → 若 **`GET /api/clusters`/`processes` 为空** 且 **`--out` 同目录存在 `overview.json`**（一般由 Phase 0.5c 的 `gnx-tools overview --out` 生成），**自动合并**聚类与流程列表到 `rawClusters`/`rawProcesses`（`meta.overviewMerge` 记录来源）
     → 若 REST/MCP 与统计仍不一致，加 **`--debug-dump`**：将原始 `GET /api/*` 响应体与 MCP SSE 原文落盘，便于与浏览器/Nexus 对照
     ⚠ 检查 arch-data.json 中 context.stats.embeddings：若为 0，索引语义查询不可靠，
       必须以 Phase 1b 源码阅读为主要依据，索引仅供路径线索参考。

Phase 1b — 源码精读（必选；**按 `PROJECT_KIND` 选流程**，不可跳过）
  ⚠ **多仓**：对 `GNX_REPO_LIST` 中**每一仓**依次执行下列步骤 A～E（各仓使用各自的 **`GNX_CACHE_DIR`** 与 `--repo`）；所有表格、证据路径使用 **`仓库名:相对路径`**。
  步骤 A：读构建与清单（依工程类型选文件）
    - **说明文档**：若仓库存在根 **`README*`** 则阅读；**无根 README 时以 `CODE_PATH` 内说明文件或构建头注释替代**，不视为阻塞
    - 按 `PROJECT_KIND` 选择：`CMakeLists.txt`/`Makefile*`、`package.json`、`go.mod`、`Cargo.toml`、`pom.xml`/`build.gradle*`、`*.csproj`、`pyproject.toml`/`requirements.txt` 等
    - 产出：可运行单元/产物列表、外部依赖、关键编译/运行参数
  步骤 B：目录与模块边界（依工程类型）
    - 若有 `CODE_PATH`：**优先**该路径下递归代表性文件；否则从 GitNexus `suggestedSourceFiles` / `search` 结果 + 扩展名统计选目录
    - **非 C++**：按包/模块惯例（如 `src/lib`、`internal/`、`pkg/`）每层至少 1 个代表性源文件；记录 import/include 方向
    - **C++**：**必须同时执行附录 A「步骤 B」**（Mgr.h / 同名 .h 等优先级与 #include 线索）
  步骤 C：入口与启动链（依工程类型）
    - 定位 `main` / 框架入口（如 `app.py`、`index.ts`、`Program.cs` 等），读前 80～120 行；记录启动调用序列
    - **C++**：**必须同时执行附录 A「步骤 C」**
  步骤 D：依赖与交叉验证（**优先** `gnx-tools.js grep --cache <GNX_CACHE_DIR>`）
    - 按语言选择 grep 模式（import、package 引用、#include、路由注册等）
    - **C++**：**必须同时执行附录 A「步骤 D」**
    - 对 `CORE_FEATURES` 逐项更新追踪表（涉及文件列表，含仓库名）
    - **跨仓关联**：在各仓配置与入口中检索**他仓主机名、URL 路径、proto 服务名、消息 topic、DSN** 等，记录「调用方仓 → 被调方仓」候选边；无文件证据不得写死
  步骤 E：遗漏能力扫描（供功能架构 §4）
    - 在各仓入口、路由注册表、CLI 子命令、OpenAPI/Swagger/proto、对外 README 中，列出**疑似用户可见或对外契约**的行为点
    - 与 `CORE_FEATURES` 名称/描述做**显式比对**：无法归入任一列表项的 → 记入内部表 `GAP_CANDIDATES`（每条须含 `仓库名:路径` 证据）
    - 若用户未传 `CORE_FEATURES`：`GAP_CANDIDATES` 同时作为「候选核心能力」全量来源

Phase 2 — 产品与架构综合
  2a. 用户传入信息优先：PRODUCT_DESC > 对话中的用户纠偏 > 源码推断 > 索引信号
  2b. 产品层：以 PRODUCT_DESC 为基础展开产品定位；CORE_FEATURES 作为能力矩阵的骨架项
  2c. 技术层：按源码目录实际结构映射分层（clusters 作线索，源码为准）；
      对每层标注承载了哪些 CORE_FEATURES 项；**多仓时**层或模块须能映射回具体仓库
  2d. 向用户展示分层摘要（含每层对应的源码路径证据 + 覆盖的核心功能项）→ 确认或修正
  2e. 确认核心功能追踪表格完整性：所有 CORE_FEATURES 项都已有「涉及文件」记录；
      未追踪到代码的项须标记「[待源码确认]」
  2f. **清单外与一致性汇总**：
      - 将 Phase 1b-E 的 `GAP_CANDIDATES` 整理为功能架构 **§4** 表格草案，并撰写「产品管理人员待办」段落
      - 汇总多仓**术语/接口前缀/错误码**不一致点，供功能架构 §4 或技术架构 §2.4 引用（避免在 §1～3 重复长表）

Phase 3 — 图示（必须执行；按 **Phase 0e 的 `DIAGRAM_MODE` 二选一）

**当 `DIAGRAM_MODE=excalidraw` 时**：
  ⚠ 必须按 **whalecloud-dev-tool-excalidraw**（见文末「图示技能」）生成以下两张图，分别对应技术架构 §3.3、§4.1；产物为 **OUTPUT_DIR** 下的 `tech-stack.excalidraw` 与 `sys-arch-layers.excalidraw`。
  ⚠ **不得**以「仅写 Mermaid」代替上述两份 JSON 文件；Mermaid 若存在，仅可作附录性补充，非 Synapse 约定的主图示交付物。

  图 A：技术栈依赖图（§3.3）
    - 主题：技术栈依赖关系；内容来自 Phase 1b 步骤 A 构建清单

  图 B：系统分层架构概览（§4.1）
    - 主题：系统分层架构；层与连线来自 Phase 1b 目录结构与 Grep 验证的依赖方向

  生成规则（Excalidraw）：
    - 节点名称必须来自源码中真实的类名/函数名/目录名/依赖名，不得编造
    - 每张图配套文档中写 1 句「图示来源」+ 源码路径
    - 依据不足时可在图中或图下标注「[待源码补充：<缺失内容>]」

**当 `DIAGRAM_MODE=mermaid` 时**：
  ⚠ **不得**读取或执行 whalecloud-dev-tool-excalidraw；**不得**在 **OUTPUT_DIR** 创建 `*.excalidraw`（含 `tech-stack.excalidraw`、`sys-arch-layers.excalidraw`）。
  ⚠ 在组装 **TECH_ARCH.md** 时，**§3.3** 必须包含完整 **技术栈依赖** `mermaid` 代码块（推荐 `flowchart`/`graph`）；**§4.1** 必须包含完整 **分层架构总览** `mermaid` 代码块；方向与节点标签须与 Phase 1b 证据一致；图下「图示来源」+ 路径。
  ⚠ 节点与层命名规则与 Excalidraw 模式相同（真实源码符号）；多仓时在标签或子图中区分仓库亦可。

Phase 4 — 组装输出（双文档）
  ⚠ 输出至 **OUTPUT_DIR**，互不交叉；**必选**：`FUNCTIONAL_ARCH.md`、`TECH_ARCH.md`。**仅当 `DIAGRAM_MODE=excalidraw`** 时，还须写入 `sys-arch-layers.excalidraw`、`tech-stack.excalidraw`；**`DIAGRAM_MODE=mermaid` 时不要创建**上述 `.excalidraw`，图示仅在 `TECH_ARCH.md` 的 Mermaid 代码块中：
  4a. 主文档：FUNCTIONAL_ARCH.md（功能架构）
      - 按 func-arch-template.md 填写，以业务能力和用户感知为核心
      - 核心功能详解（§3）：逐项展开 CORE_FEATURES，每项含「功能说明」+「代码影响范围（文件列表）」；多仓路径带 **`仓库名:`** 前缀
      - **遗漏功能与清单外能力分析（§4）**：基于 Phase 1b-E / 2f，填满 `{{GAP_FEATURES_ANALYSIS}}` 与「产品管理人员待办」
      - 不包含：技术栈细节、分层架构图、运行时进程、编译宏、构建系统
  4b. 补充文档：TECH_ARCH.md（技术架构）
      - 按 tech-arch-template.md 填写，以技术栈、分层、运行态为核心
      - **§2.4 多仓库组成与跨仓关联**：与功能架构 §4 互补，侧重工程事实与集成证据，不重复业务能力叙述
      - 不重复功能架构中的产品定位、场景描述、业务能力
      - 每个技术层注明「承载核心功能：xxx」，与功能架构形成交叉引用而非内容重复

Phase 5 — 迭代
  7. 用户补充 → 更新 user_overrides → 仅重画受影响图（Excalidraw）或更新对应 Mermaid 块、更新对应章节
  8. 若用户新增 CORE_FEATURES 项 → 补充追踪 → 更新功能架构 §3、**§4（清单外表可能缩行或改标注）**、技术架构各层与 §2.4
```

> 脚本连接失败时检查 URL 与网络；**无服务时仍可完成文档**，须弱化「执行流/聚类」章节并标明数据缺口，但**图示（按 Phase 0e：Excalidraw 或 Mermaid）与源码阅读仍须执行**。

## Phase 1: 结构化信号采集

```text
run_skill_script(
  skill_name="whalecloud-dev-tool-base-scripts",
  script_name="fetch-arch-data.js",
  args=["--url", "<GITNEXUS_URL>", "--repo", "<REPO_NAME>", "--with-snippets"]
)
```

> ⚠ **Windows PowerShell 注意**：不支持 `&&` 链式命令，`cd <dir> && node ...` 会报 `InvalidEndOfLine` 错误。应使用绝对路径直接调用脚本，或用 `;` 分隔两条命令（前者失败时后者仍执行），或在 `working_directory` 参数中设置工作目录。

脚本访问 **`gitnexus serve`** 同源 REST/MCP（与现有部署一致）：

**REST**：`GET /api/repos`、`GET /api/repo?repo=`、`GET /api/clusters?repo=`、`GET /api/processes?repo=`

**MCP**（`POST /api/mcp`，工具 `query`）：多条概念查询；`--with-snippets` 打开 `include_content`

输出 **`arch-data.json`** 含：`context`、`techStack`、`layeredClusters`、`processInventory`、`queryResults`（含 `product`）、**`suggestedSourceFiles`**（从查询结果收集的路径列表，供 Phase 1b 精读）。

同时自动在同目录生成 **`arch-data-summary.txt`**，预提取常用字段（`embeddings`、`repoPath`、`processInventory` 各列表计数、前 10 条 `suggestedSourceFiles`、索引质量诊断），供快速查阅无需解析大 JSON。

> ⚠ **`processInventory` 字段结构**：该字段为 `{ daemon: [...], tool: [...] }` 对象，不是直接数组。访问方式：`d.processInventory.daemon`（常驻进程列表）、`d.processInventory.tool`（工具进程列表）。在独立 `.js` 脚本中使用 `[...d.processInventory.daemon, ...d.processInventory.tool]` 合并全部进程列表。`arch-data-summary.txt` 中已注明此结构，可直接引用。

### 索引质量评估（必须在 Phase 1b 前完成）

读取 `arch-data.json` 后，检查以下指标，决定索引信号的可信度：

| 检查项 | 值 | 可信度判断 |
|--------|-----|-----------|
| `context.stats.embeddings` | > 0 | 语义查询可用；= 0 则仅关键词匹配，聚类分类不可靠 |
| `context.stats.communities` | 与文件数量成比例 | 聚类粒度合理 |
| `layeredClusters.infra` 和 `proxy` | 非空 | 分类未全部塌缩到 api 层 |
| `suggestedSourceFiles` | 路径可在工作区验证 | 路径有效则作为 Phase 1b 起点 |

**若 `embeddings=0`**：
1. 在技术架构文档 §1（技术概览）开头插入以下提示段落：

   > ⚠ **索引质量说明**：本次分析时，代码索引未启用语义向量（embeddings=0），仅支持关键词匹配，聚类分类结果不可信（90% 以上可能被归到 api 层）。以下所有架构分层、模块分类均**完全依据源码目录结构与 Makefile/构建清单**推导，未采用索引分层结果。如需提升索引质量，请在索引服务所在环境执行 `npx gitnexus analyze --embeddings` 重建索引后重新生成本文档。

2. 在 Phase 1b 中增加 Grep 验证步骤（验证跨目录 `#include` 方向，不依赖索引聚类）。

## 附录 A：C++ 工程补充要点（当 `PROJECT_KIND` 为 `cpp_native` 或 `cpp_mixed` 时 **必须叠加**）

以下条款**仅**在 C++ 为主体时适用；其他语言勿套用 `#include` / `.h` 猜测规则。

### A.1 构建/清单文件（步骤 A 的 C++ 强化）

| 文件类型 | 要读取的内容 | 产出信息 |
|---------|-------------|---------|
| README*（若存在） | 产品定位、编译环境要求、运行说明 | §1 产品简介、§2 产品定位；**无则跳过**，改读 `CODE_PATH` 内注释与构建头 |
| Makefile / Makefile.incl* | 构建目标（`TARGET`/`TARGETS`）、链接库（`-l`）、编译宏（`-D`） | 可执行产物清单、外部依赖库 |
| CMakeLists.txt | `add_executable`/`add_library` 目标、`target_link_libraries` | 产物与依赖 |
| makeall / make.sh | 顶层构建流程、子目录编译顺序 | 构建拓扑 |

> C++ 项目通常**没有 go.mod / package.json**，依赖信息常在 Makefile 的 `-l` / `-I` / `-D` 中，须读 Makefile/CMake 才能写准技术栈与外部依赖。

### A.2 子目录扫描（步骤 B 的 C++ 强化）

对仓库根下每个子目录，**至少读一个头文件**，优先级：

| 优先级 | 文件模式 | 说明 |
|--------|---------|------|
| 0 | 入口 `.cpp` 里 `#include "..."` 指明的头文件 | **最可靠** |
| 1 | `<Dir>/<DirName>Mgr.h` | 管理类 |
| 2 | `<Dir>/<DirName>.h` | 同名主头 |
| 3 | `<Dir>/<DirName>Common.h` / `Base.h` | 公共与基类 |
| 4 | 目录中最大 `.h` | fallback |

记录：`class`/`struct`、public 方法、`#include` 跨目录依赖、`#ifdef` 分支。

**子目录过多**：优先含 `ctrl`/`mgr`/`service`/`core`/`agent` 等名的目录与文件数多的目录；其余列表注明「未深入」。

### A.3 可执行入口（步骤 C 的 C++ 强化）

- 搜索 `int main(` 的 `.cpp`（`App/`、`Tools/`、`cmd/` 等）；读前 100 行：产物名、`#include`、Init/Start 序列、命令行参数。

### A.4 跨目录验证（步骤 D 的 C++ 强化）

**优先** `gnx-tools.js grep --cache <GNX_CACHE_DIR>`，建议模式：

```
#include 跨目录引用；class.*(Mgr|Manager|Ctrl|Service|Worker)；int\s+main\s*\(；#ifdef\s+_[A-Z]；socket|shm_open|pthread|sem_|mq_
```

写作要求（C++ 时）：

- 每层至少引用 1 个真实 `.h`/`.cpp` 路径；禁止仅用索引命名当论据。
- `#ifdef` 重要分支须在技术架构中显式说明为**架构约束**。
- 指标放模板 §10.1 并注明「索引快照，须与源码核对」。

## Phase 2: 产品与架构综合

### 2a. 信息优先级

优先级从高到低：
1. **用户传入的 `PRODUCT_DESC`**（产品描述，最高优先级）
2. **用户传入的 `CORE_FEATURES`**（核心功能列表，分析骨架）
3. **对话中的实时纠偏**（层归属、命名、场景说明）
4. **源码目录 + 头文件接口关系**（#include/import 方向）
5. **构建目标划分**（Makefile 中的 target 组织）
6. **索引 clusters**（最低优先级，且 embeddings=0 时基本不可信）

内部可维护 `user_overrides`（layers、assignments、descriptions）。

### 2b. 产品定位分析（以 PRODUCT_DESC 为基础）

若用户传入了 `PRODUCT_DESC`：
- 直接以产品描述中的定位、目标用户、关键功能入口作为 §1/§2 的叙述起点
- 从源码中找对应的实现证据，补充论据
- 若产品描述与源码有出入，采用产品描述，并在段落末注明「[源码待确认：xxx]」

### 2c. 核心功能分析（以 CORE_FEATURES 为骨架）

若用户传入了 `CORE_FEATURES`：
- 功能架构 §3 的章节结构按功能列表逐项展开，**不得遗漏任何一项**
- 对每个功能项，汇总 Phase 1b 中的追踪结果：功能说明 + 涉及文件列表（多仓带 **`仓库名:`**）
- 在分层架构分析时，每层必须显式标注「承载核心功能：[功能名列表]」
- 在运行态分析时，关键执行流必须包含核心功能项的完整路径（如有代码依据）；**跨仓**须写清参与仓库与调用证据
- **功能架构 §4**：将 Phase 1b-E 的 `GAP_CANDIDATES` 去重、分级（高置信用户可见 vs 仅内部工具），并给出**产品管理人员待办**；不得用 §3 的复述充数

### 2d. 分层依据优先级

1. **用户明确指定**（最高优先级）
2. **源码目录 + 头文件接口关系**（#include/import 方向）
3. **构建目标划分**（Makefile 中的 target 组织）
4. **索引 clusters**（最低优先级，且 embeddings=0 时基本不可信）

**空层删除**。每层在文档中写一句 **产品侧职责**，并列出对应源码路径。

### 2e. 确认点

向用户列出：
1. 检测到的分层与每层代表性源码路径
2. 核心功能追踪完成情况（已追踪 / 未追踪到代码）

- 若用户**明确要求交互确认**（如「帮我分析一下再继续」），则等待确认后进入 Phase 3。
- 若用户**直接要求生成并保存文档**（如「生成架构文档保存到目录 X」），可在消息中展示分层摘要后**直接继续**执行 Phase 3，无需等待回复。

## Phase 3: 图示（强制执行；按 Phase 0e `DIAGRAM_MODE`）

**此步骤不可被跳过**。交付形式由 **`DIAGRAM_MODE`** 决定（见上文 Workflow Phase 3 与 Phase 0e）。

### 当 `DIAGRAM_MODE=excalidraw` 时

必须产出 **两张** `.excalidraw` JSON（`tech-stack.excalidraw`、`sys-arch-layers.excalidraw`）至 **OUTPUT_DIR**。

**「调用 whalecloud-dev-tool-excalidraw」的完整含义**：

1. 用 Read 工具读取技能文件 `../whalecloud-dev-tool-excalidraw/SKILL.md`（若在工作区 skills 目录中找不到，尝试系统 skills 目录 `C:\Users\<用户>\.cursor\skills\EXCALIDRAW-DIAGRAM-SKILL\SKILL.md`）
2. 读取 `../whalecloud-dev-tool-excalidraw/references/color-palette.md` 获取颜色规范
3. 读取 `../whalecloud-dev-tool-excalidraw/references/element-templates.md` 获取 JSON 元素模板
4. **按该技能的规则，直接用 Write 工具写出 `.excalidraw` JSON 文件**到 **OUTPUT_DIR**，文件名：`tech-stack.excalidraw`（技术栈）、`sys-arch-layers.excalidraw`（分层总览，与 `dev_iwhalecloud_knowledge.py` 读取名一致）。

> ⚠ 这不是「调用另一个 Agent」或「子进程调用」，而是读取 excalidraw 技能规范后，自己生成符合规范的 JSON 文件。不要等待外部工具响应。

**与 PNG 导出**：若团队使用 **Markdown + Excalidraw 插件（如 React 预览）** 在同页渲染 `.md` 与 `.excalidraw`，则**不必**再走 `render_excalidraw.py` 生成 PNG；技术架构文档中用 **指向 `.excalidraw` 的链接** 即可。PNG 渲染循环仅作为**无插件环境下的可选质控**（与「内嵌链接」不是同一硬性步骤）。

| 图 | 所属文档 | 章节 | 要点 |
|----|---------|------|------|
| 图 A：技术栈依赖 | TECH_ARCH.md | §3.3 | 语言 → 依赖库 → 外部系统；节点来自构建文件 |
| 图 B：系统分层 | TECH_ARCH.md | §4.1 | 分层框与依赖方向；层名来自源码目录 |

- 将生成的图以链接或嵌入约定填入 `{{DIAGRAM_TECH_STACK}}`、`{{DIAGRAM_SYSTEM_OVERVIEW}}`；图下「图示来源」+ 源码路径
- 两张 JSON 文件落盘后再进入 Phase 4

### 当 `DIAGRAM_MODE=mermaid` 时

**不要**读取 whalecloud-dev-tool-excalidraw、**不要**写入任何 `.excalidraw`。

在 **TECH_ARCH.md** 的 **§3.3**、**§4.1** 各放入 **一个完整、可渲染的** ```mermaid 代码块（技术栈依赖一张、分层总览一张），内容与 Phase 1b 证据一致；图下「图示来源」+ 路径。完成后进入 Phase 4。

## Phase 4: 文档组装（双文档）

输出两份独立文档，内容不交叉，以功能架构为主要文档：

### 4A. 功能架构文档（主文档）FUNCTIONAL_ARCH.md

使用 [func-arch-template.md](func-arch-template.md)：

1. **§1～2**：产品简介、产品定位 — 以 `PRODUCT_DESC` 为基础，源码为论据；多仓时在 §1 末用 1 段说明「本产品由 N 个代码仓组成」（仓库名与 `GNX_REPO_LIST` 一致）。
2. **§3**：核心功能详解 — 以 `CORE_FEATURES` 为骨架，逐项展开：
   - 功能说明（结合产品描述和源码分析）
   - 代码影响范围（Phase 1b 追踪到的文件列表，精确到文件级别，**`仓库名:路径`**）
   - 关键入口（主要类/方法名）
3. **§4**：**遗漏功能与清单外能力分析** — 对照 `CORE_FEATURES` 与 Phase 1b-E 结果；含「产品管理人员待办」；未传列表时改为候选能力清单
4. **§5**：业务能力矩阵 — 能力 | 用户可感知结果 | 主要实现位置 | 成熟度（实现位置列须能区分仓库）
5. **§6**：使用场景 — 以核心功能为维度描述典型场景和交互流程（跨仓场景写清链路与参与仓）
6. **§7**：功能边界与非目标
7. **§8**：ADR、技术债、演进建议（功能视角）

> **不包含**：技术栈表格、分层架构图、进程清单、编译宏、构建系统、工程度量指标

### 4B. 技术架构文档（补充文档）TECH_ARCH.md

使用 [tech-arch-template.md](tech-arch-template.md)：

1. **§1**：技术概览（1 段，引用功能架构文档，不重复产品定位）
2. **§2**：仓库与工程事实（README 摘要、目录边界、构建系统、**§2.4 多仓库与跨仓关联**）
3. **§3**：技术栈（语言分布、框架依赖、§3.3 技术栈依赖图：Excalidraw 链接或 Mermaid 块，依 `DIAGRAM_MODE`）
4. **§4**：系统分层架构（§4.1 分层总览：同上；各层详解）
   - 每层必须注明「承载核心功能：[功能名列表]」（与功能架构形成交叉引用）
5. **§5**：运行形态与执行流（常驻进程、工具进程、核心执行流）
   - 执行流需标注涉及的核心功能项；跨仓调用注明仓库
6. **§6**：模块依赖与变更风险
7. **§7**：源码佐证与关键路径
8. **§8**：附录（工程度量、数据采集说明）

> **不重复**：产品定位描述、场景分析、业务能力说明、功能边界

占位符映射：`{{INDEXED_AT}}` ← `indexedAt`；`{{REPO_ROOT_HINT}}` ← `repoPath`；`{{INDEX_STATUS}}` ← 新鲜度说明；各 `{{METRICS_*}}` 来自 `context.stats`；daemon/tool 计数来自 `processInventory`。

## Checklist

**首次生成：**

```
用户传入信息处理：
- [ ] PRODUCT_DESC 已提取（或标记为空，使用 README 替代）
- [ ] CODE_PATH 已提取（或标记为空，使用默认扫描策略）
- [ ] CORE_FEATURES 已提取并建立追踪表格（或标记为空）
- [ ] **Phase 0e**：`DIAGRAM_MODE` 已判定（system 提示含 `whalecloud-dev-tool-excalidraw` → excalidraw，否则 mermaid）

索引与源码读取：
- [ ] GITNEXUS_URL 已确认；若按产品拉仓则 **SYNAPSE_URL + PROD** 已确认且已跑 `get_repo_info.py`，`GNX_REPO_LIST` 已建立
- [ ] 每个仓库的 **`GNX_CACHE_DIR`** 已确定且与 **REPO_NAME** 一一对应（禁止与 **OUTPUT_DIR** 混用）
- [ ] `gnx-tools.js materialize` 已对各仓运行并存在 `GNX_CACHE_DIR/files`
- [ ] `detect-project-kind.js` 已运行，`PROJECT_KIND` 已记录（低置信度已说明）
- [ ] fetch-arch-data.js 已运行（或已记录「跳过索引」及原因）；若 REST/MCP 异常已尝试 `--debug-dump`
- [ ] 已检查 arch-data.json 中 embeddings 值，记录索引可信度
- [ ] 已用 --with-snippets（若运行了脚本）
- [ ] 构建文件（Makefile/CMakeLists/go.mod 等）已 Read；README 仅在存在时阅读（无则依赖 `CODE_PATH` 与清单）
- [ ] CODE_PATH 指定的路径已优先读取（若有）
- [ ] 所有顶层子目录均已读取至少一个代表性文件（或已注明跳过原因）
- [ ] 所有可执行入口文件（main）已 Read
- [ ] 已用 Grep 验证跨层 include/import 依赖方向

核心功能追踪：
- [ ] CORE_FEATURES 中每项都已完成代码追踪（文件级别，多仓带仓库前缀）
- [ ] 未追踪到代码的项已标记「[待源码确认]」
- [ ] **§4 遗漏功能分析**：`GAP_CANDIDATES` 已整理完毕；有列表时覆盖清单外项，无列表时为候选能力清单；含「产品管理人员待办」

多仓库与一致性：
- [ ] `GNX_REPO_LIST` 中**每一仓**均完成 Phase 0.5 materialize（失败仓已记录并标注后续章节）
- [ ] 跨仓结论均在相关仓分别留下 read/grep 证据
- [ ] 技术架构 **§2.4** 已填写（单仓则明确不适用）
- [ ] 产品定位（以 PRODUCT_DESC 为基础）已写（每段有源码路径作为论据）
- [ ] 动态分层已提出并与用户确认（含源码路径证据 + 覆盖的核心功能项）

图示生成（按 Phase 0e `DIAGRAM_MODE`）：
- [ ] **`DIAGRAM_MODE=excalidraw`**：已读取 whalecloud-dev-tool-excalidraw 规范；`tech-stack.excalidraw`、`sys-arch-layers.excalidraw` 已写入 **OUTPUT_DIR**；TECH_ARCH §3.3 / §4.1 已引用并附「图示来源」
- [ ] **`DIAGRAM_MODE=mermaid`**：**未**创建任何 `.excalidraw`；TECH_ARCH §3.3、§4.1 各含完整可渲染 ```mermaid 块 +「图示来源」

文档输出：
- [ ] func-arch-template 已填满（§3 CORE_FEATURES 逐项含代码影响范围；**§4 遗漏功能/候选能力**已填满）
- [ ] tech-arch-template 已填满（**§2.4** 多仓与跨仓关联；各层注明承载核心功能，不重复功能描述）
- [ ] **OUTPUT_DIR** 已含 `FUNCTIONAL_ARCH.md`、`TECH_ARCH.md`；**若 `DIAGRAM_MODE=excalidraw`** 还须含约定名两份 `.excalidraw`
- [ ] 两份文档内容不交叉（功能架构无技术栈/分层图，技术架构无产品定位/场景）
```

**迭代：** 更新 overrides → 重映射层 → 仅重画受影响图（Excalidraw）或同步修订 Mermaid、更新对应章节。
新增 CORE_FEATURES 项时：补充代码追踪 → 更新功能架构 §3 → 更新技术架构各层标注。

## Error Handling

| 错误 | 处理 |
|------|------|
| `ECONNREFUSED` | 检查 URL；跳过 Phase 1，直接从 Phase 1b 开始（仅源码路径） |
| `Repo not found` | 用脚本绝对路径加 `--list` 参数列出可用仓库名 |
| 索引过期 | 提示在索引所在环境执行 `npx gitnexus analyze --embeddings` 后重新导出 |
| 找不到脚本 `fetch-arch-data.js` | 使用 `run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="fetch-arch-data.js", args=[...])` |
| PowerShell `&&` 报 InvalidEndOfLine | 不要用 `&&`，改用绝对路径直接调用，或用 `working_directory` 参数 |
| `overview.json` / `arch-data` 解析失败、`overview:parse-failed` | PowerShell `>` 默认 **UTF-16**；**必须改用** `gnx-tools overview --out path.json`（`--out` 写 UTF-8，无此参数时控制台会打印警告提示）；或依赖已增强的 `detect-project-kind.js`（可读 UTF-16） |
| REST 与 `arch-data` 内容对不上 | 使用 `fetch-arch-data.js --debug-dump <dir>` 对照原始响应与 MCP SSE |
| `/api/mcp` 返回 406 Not Acceptable | 不通过 `/api/mcp` 做 Grep，改用 `/api/file` 读取文件后用 `Select-String` 过滤 |
| `embeddings=0` | 降级：索引仅用于路径线索，分层完全依赖 Phase 1b 源码阅读 |
| 源码不在本地工作区 | 通过 `/api/file?repo=<REPO>&path=<PATH>` REST 端点读取远程源码（见「源码访问方式判断」） |
| `/api/file` 传目录路径返回 `EISDIR` | 该端点**不支持目录**；无法通过 REST 列目录；须从 `arch-data.json` 的 `suggestedSourceFiles`/`queryResults` 提取已知文件路径推断目录结构（或写独立 `find-paths.js` 文件提取） |
| 不知道仓库内文件相对路径前缀 | 从 `arch-data.json` 的 `suggestedSourceFiles` 提取任意路径，观察公共前缀（如 `BackServiceCpp/src/cpp/Zmdb/`），作为所有后续 `/api/file` 请求的路径前缀 |
| 按 `<Dir>/<DirName>Mgr.h` 猜测头文件名失败 | 先读 App/ 入口文件（步骤 C 优先），从 `#include "子目录/真实文件名.h"` 直接获取；不要穷举猜测超过 3 次 |
| `processInventory.slice is not a function` | `processInventory` 字段结构为 `{ daemon: [...], tool: [...] }` 对象，不是直接数组；应访问 `d.processInventory.daemon` 和 `d.processInventory.tool` 分别获取各列表，或用 `[...d.processInventory.daemon, ...d.processInventory.tool]` 合并 |
| PowerShell 处理大 JSON 极慢（>60秒）| 不要用 `ConvertFrom-Json` 解析大文件；将处理逻辑写入独立 `.js` 文件，用 `node xxx.js` 执行（秒级完成）。`arch-data.json` 运行完成后会自动在同目录生成 `arch-data-summary.txt`，常用字段（embeddings、repoPath、processInventory 计数、前 10 条 suggestedSourceFiles）已预提取，可直接 `cat` 读取无需解析 JSON |
| PowerShell `node -e` 中 JS 语法报错 | **禁止在 PowerShell `node -e` 中写任何包含引号或多层逻辑的 JS**——引号/转义必然出错。改用 `Write` 工具创建独立 `.js` 文件，再 `node xxx.js` 执行。即便是单行简单 JS 也应优先写独立文件 |
| `read: not in cache` 反复出现 | `materialize` 默认无文件上限，通常是仓库有 `--max-files` 参数导致被截断；检查是否使用了 `--max-files`，若是则去掉该参数重跑 `materialize` |
| `gnx-tools.js read` 输出内容过多难以阅读 | 使用 `--lines N` 参数截断输出（如 `--lines 80` 只输出前 80 行），无需依赖 PowerShell `head` 命令 |
| 子目录过多（>20）| 按优先级选 15 个目录深入，其余列表并注明「未读取」 |
| 源码文件过大（>500行）| 读前 80 行（构造函数/类声明）+ 过滤核心方法签名 |
| CODE_PATH 路径不存在 | 向用户确认路径格式（相对路径还是绝对路径）；若仍无法访问，降级为默认目录扫描策略并告知用户 |
| CORE_FEATURES 某项无法追踪到源码 | 标记「[待源码确认]」，在功能架构文档 **§7.3** 中列出；不要因为一项未追踪到而卡住整个流程 |
| 用户未传入 PRODUCT_DESC / CORE_FEATURES | 从 README（若存在）或 **`CODE_PATH` 下文件头/模块注释** 提取产品简介作为 PRODUCT_DESC 替代；**CORE_FEATURES 为空时**：§3 按通用结构弱化骨架约束，**§4 仍须输出「候选核心能力清单（待产品确认）」**（见核心约束 §7），不得整章留空 |

## 冲突展示（去品牌化表述）

```
[用户]       AuthManager → 管理层
[索引推断]  启发式匹配 → 基础层（置信度约 72%，embeddings=0）
[源码]       ZmdbAgentMgr.h 中 include 了 Control/ 和 Interface/ ← 实际依据
→ 采用：管理层（用户优先 + 源码支撑）
```

优先级：用户明确陈述 → 源码 include/import 方向 → 用户已确认分层方案 → 高置信启发式 → 低置信启发式 → 标记待人工复核。

## Additional Resources

- [func-arch-template.md](func-arch-template.md) — 功能架构文档模板（主文档）
- [tech-arch-template.md](tech-arch-template.md) — 技术架构文档模板（补充文档）
