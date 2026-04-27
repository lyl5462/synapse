---
name: whalecloud-dev-tool-arch-create
description: "通用产品架构/技术架构文档生成技能（源码优先 + GitNexus 索引辅助）。按仓库语言与构建体系自动匹配分析流程；C++ 仓库启用附录中的专项阅读策略。Examples: 写架构说明、梳理分层与执行流、结合图谱写技术架构、产出 FUNCTIONAL_ARCH + TECH_ARCH 双文档。"
---

# 产品架构文档生成（源码优先 · GitNexus 辅助）

生成**两份互不交叉**的交付：`FUNCTIONAL_ARCH.md`（功能架构）与 `TECH_ARCH.md`（技术架构）。叙述以**真实源码**为主，**GitNexus**（`gitnexus serve`）仅作入口定位、执行流与模块划分线索；不在正文反复出现工具品牌。

**语言与工程类型**：默认**不**假设仓库为 C++。必须先执行 **Phase 0.1 工程类型判定**，得到 `PROJECT_KIND` 后再选用对应的 Phase 1b 阅读策略；若判定为 **C++ 原生或 C++ 混合主体**，必须叠加 **附录 A** 中的 C++ 专项要点。

> **核心约束（违反则文档不完整）**
> 1. **图示必须用 whalecloud-dev-tool-excalidraw 生成**：技术架构文档 §3.3 技术栈、§4.1 架构总览两张图必须通过调用 `whalecloud-dev-tool-excalidraw` 生成，不可用纯 Mermaid 文字块替代，不可省略。
> 2. **源码必须直接读取**：不能仅依赖索引快照；Phase 1b 必须读取与 `PROJECT_KIND` 匹配的**代表性源文件**（入口、构建清单、典型模块），文档中有源码路径论据。
> 3. **索引仅作定位辅助**：聚类在 embeddings=0 时不可靠，必须以源码与构建事实为准，**不得将索引分层结果不经源码验证写入文档**。
> 4. **双文档输出，内容不交叉**：功能架构文档（FUNCTIONAL_ARCH.md）不包含技术栈/分层图/运行态；技术架构文档（TECH_ARCH.md）不重复产品定位/场景/业务能力描述。
> 5. **核心功能列表必须全覆盖**：用户传入的 `CORE_FEATURES` 中每一项都必须出现在功能架构文档 §3 中，且含代码影响范围（文件级别）。

## Parameters (auto-detected from context)

| Parameter | How agent gets it | Example |
|-----------|------------------|---------|
| `GITNEXUS_URL` | From user message or config | `http://127.0.0.1:11011`（与 `gitnexus serve` 同源，非 Web 前端地址） |
| `REPO_NAME` | From user message or repo listing | `MyProject_user` |
| `GNX_CACHE_DIR` | 本次任务选定的 materialize 输出目录 | 如 `./.gnx-cache/MyProj_main`；**read/grep 仅访问其下 `files/`** |
| **工作区仓库根** | 当前打开的 Git 工作区根目录 | 若有本地克隆，仍可用 Cursor Read/Grep；无克隆则依赖 `GNX_CACHE_DIR` |
| **`PROJECT_KIND`** | Phase 0.1 输出 | 如 `cpp_native` / `python` / `node_ts` / `go` / `jvm` / `mixed_polyglot` 等 |

### Phase 0.1 — 工程类型判定（必选，先于 Phase 0.5 / 1b）

目标：在**不臆测**的前提下，综合 **(1) 仓库内相对路径与扩展名**、**(2) materialize 缓存中的文件分布**、**(3) GitNexus 结构化信号**，得到 `PROJECT_KIND` 与置信度，并据此选择 Phase 1b 的「入口文件 / 构建清单 / 依赖验证」清单。

**推荐自动化（Cursor 终端）**：

```text
node <技能绝对路径>/scripts/detect-project-kind.js --cache <GNX_CACHE_DIR> [--overview <GNX_CACHE_DIR>/overview.json]
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

本技能**不再**以 PowerShell 拼 `Invoke-WebRequest` 或 MCP 流式接口作为默认取数方式。一律使用技能内脚本 **`scripts/gnx-tools.js`**（七子命令 + `materialize`），底层与 Nexus 一致：

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

**参数约定**：`--url` 为 `gitnexus serve` 根（如 `http://127.0.0.1:11011`），`--repo` 与代码图谱嵌入参数一致；`--cache` 为本次任务专用目录（可放在工作区下 `.gnx-cache/`）。

**完整用法与 Cursor 验证步骤**：见同目录 `scripts/README-GNX-TOOLS.md`。

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
- 技术架构文档中的分层描述：注明每层承载哪些核心功能项

---

**用户传入信息的记录方式**：在 Phase 开始前，将用户传入信息整理为内部变量：
```
PRODUCT_DESC = <用户传入的产品描述>
CODE_PATH    = <用户传入的代码路径，若无则为空>
CORE_FEATURES = [
  { name: "功能1", desc: "..." },
  { name: "功能2", desc: "..." },
  ...
]
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
  0b. 将 CORE_FEATURES 展开为追踪表格，用于 Phase 1b 逐项打勾：
      | 功能名称 | 状态 | 涉及文件（Phase 1b 填入） | 备注 |
      |---------|------|--------------------------|------|
      | 功能1   | 待追踪 | — | — |
      ...
  0c. 若 CODE_PATH 非空，标记为「指定入口目录/文件」，Phase 1b 步骤 B/C 优先从此处开始。

Phase 0.1 — 工程类型判定（必选，可与 0.5b 顺序微调）
  0.1a. 若尚未有缓存：先执行下方 Phase 0.5b `materialize`（至少需要 `cache/files` 才能跑检测脚本）。
  0.1b. `node .../scripts/detect-project-kind.js --cache <GNX_CACHE_DIR> [--overview <GNX_CACHE_DIR>/overview.json]`
        → 解析 JSON，写入内部变量 `PROJECT_KIND`、`KIND_CONFIDENCE`、`KIND_SIGNALS`。
  0.1c. 将 `PROJECT_KIND` 与用户 **`CODE_PATH` / 产品说明** 及 README（若存在）对照；冲突时以**用户明确说明**为准，并在文档中注明依据。
  0.1d. 若 `PROJECT_KIND` 为 `cpp_native` 或 `cpp_mixed`：在后续 Phase 1b **必须执行附录 A**；其他语言按上表「主策略摘要」执行，不得套用 C++ 头文件猜测规则。

Phase 0.5 — GitNexus 缓存与 Nexus 对齐取数（有索引且要写技术/功能架构时 **必选**）
  0.5a. 选择 `--cache` 目录（建议工作区内 `.gnx-cache/<repo>/`）。
  0.5b. 执行：`node <技能绝对路径>/scripts/gnx-tools.js materialize --url <GITNEXUS_URL> --repo <REPO_NAME> --cache <CACHE_DIR> --concurrency 8`
        → 本地 `<CACHE_DIR>/files/**` 与 `manifest.json`（后续 **read/grep 只走本地**）。
        ⚠ **不要加 `--max-files` 限制**：默认不限文件数量，确保缓存覆盖仓库全量源文件，避免后续 `read: not in cache` 错误。仅在网络极慢或磁盘空间受限时才临时加上 `--max-files N`。
  0.5c. 结构化总览（可选但推荐）：`node ... gnx-tools.js overview --url ... --repo ... --out <CACHE_DIR>/overview.json`（**必须加 `--out`**，不要依赖 PowerShell `>` 重定向，`>` 默认 UTF-16 编码会导致下游脚本解析失败）
  0.5d. 按需检索：`node ... gnx-tools.js search ...`、`node ... gnx-tools.js explore ...`、`node ... gnx-tools.js impact ...`，或直接用 `cypher` 子命令。

Phase 1 — 结构化信号采集（可选，与 Phase 0.5 互补，run fetch-arch-data.js）
  1. node <技能绝对路径>/scripts/fetch-arch-data.js --url <GITNEXUS_URL> --repo <REPO_NAME> --with-snippets [--debug-dump <CACHE_DIR>/debug-fetch] [--merge-overview <path>] [--no-auto-overview]
     （⚠ 使用绝对路径；Windows 下不支持 && 链式命令，须用绝对路径或 working_directory 参数）
     → arch-data.json（clusters/processes/query 命中路径；--with-snippets 含符号正文片段）
     → 若 **`GET /api/clusters`/`processes` 为空** 且 **`--out` 同目录存在 `overview.json`**（一般由 Phase 0.5c 的 `gnx-tools overview --out` 生成），**自动合并**聚类与流程列表到 `rawClusters`/`rawProcesses`（`meta.overviewMerge` 记录来源）
     → 若 REST/MCP 与统计仍不一致，加 **`--debug-dump`**：将原始 `GET /api/*` 响应体与 MCP SSE 原文落盘，便于与浏览器/Nexus 对照
     ⚠ 检查 arch-data.json 中 context.stats.embeddings：若为 0，索引语义查询不可靠，
       必须以 Phase 1b 源码阅读为主要依据，索引仅供路径线索参考。

Phase 1b — 源码精读（必选；**按 `PROJECT_KIND` 选流程**，不可跳过）
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
    - 对 `CORE_FEATURES` 逐项更新追踪表（涉及文件列表）

Phase 2 — 产品与架构综合
  2a. 用户传入信息优先：PRODUCT_DESC > 对话中的用户纠偏 > 源码推断 > 索引信号
  2b. 产品层：以 PRODUCT_DESC 为基础展开产品定位；CORE_FEATURES 作为能力矩阵的骨架项
  2c. 技术层：按源码目录实际结构映射分层（clusters 作线索，源码为准）；
      对每层标注承载了哪些 CORE_FEATURES 项
  2d. 向用户展示分层摘要（含每层对应的源码路径证据 + 覆盖的核心功能项）→ 确认或修正
  2e. 确认核心功能追踪表格完整性：所有 CORE_FEATURES 项都已有「涉及文件」记录；
      未追踪到代码的项须标记「[待源码确认]」

Phase 3 — 图示（必须执行，不可省略）
  ⚠ 本 Phase 是强制步骤：必须调用 whalecloud-dev-tool-excalidraw 生成以下两张图，图分别用于两份文档。
  ⚠ 不得用 Mermaid 代码块替代 whalecloud-dev-tool-excalidraw 的调用——Mermaid 是备注用途，图示产物必须来自该技能。

  图 A：技术栈依赖图（技术架构文档 §3.3）
    - 调用 whalecloud-dev-tool-excalidraw，主题：技术栈依赖关系
    - 展示：语言/运行时 → 核心框架/库 → 外部依赖（数据库/消息队列等）
    - 内容来自 Phase 1b 步骤 A 读到的构建文件和依赖声明

  图 B：系统分层架构概览图（技术架构文档 §4.1）
    - 调用 whalecloud-dev-tool-excalidraw，主题：系统分层架构
    - 展示：各架构层（从用户侧到数据侧）、层间依赖方向、每层承载的核心功能标注
    - 内容来自 Phase 1b 步骤 B/C 读到的目录结构和入口文件

  生成规则：
    - 提供给 whalecloud-dev-tool-excalidraw 的描述中，节点名称必须来自源码中真实的类名/函数名/目录名，不得编造
    - 每张图下方写 1 句「图示来源说明」，注明对应的源码路径证据
    - 若某图暂无充分源码依据，先生成占位图，再在图下标注「[待源码补充：<缺失内容>]」

Phase 4 — 组装输出（双文档）
  ⚠ 输出两份文档，互不交叉：
  4a. 主文档：FUNCTIONAL_ARCH.md（功能架构）
      - 按 func-arch-template.md 填写，以业务能力和用户感知为核心
      - 核心功能详解（§3）：逐项展开 CORE_FEATURES，每项含「功能说明」+「代码影响范围（文件列表）」
      - 不包含：技术栈细节、分层架构图、运行时进程、编译宏、构建系统
  4b. 补充文档：TECH_ARCH.md（技术架构）
      - 按 tech-arch-template.md 填写，以技术栈、分层、运行态为核心
      - 不重复功能架构中的产品定位、场景描述、业务能力
      - 每个技术层注明「承载核心功能：xxx」，与功能架构形成交叉引用而非内容重复

Phase 5 — 迭代
  7. 用户补充 → 更新 user_overrides → 仅重画受影响图、更新对应章节
  8. 若用户新增 CORE_FEATURES 项 → 补充追踪 → 更新功能架构 §3 和技术架构各层标注
```

> 脚本连接失败时检查 URL 与网络；**无服务时仍可完成文档**，须弱化「执行流/聚类」章节并标明数据缺口，但**图示和源码阅读不受影响，仍须执行**。

## Phase 1: 结构化信号采集

```powershell
# 始终使用 --with-snippets 以获取符号正文片段（用于验证索引聚类是否准确）
# 注意：脚本路径为技能目录下的绝对路径，不要用相对路径 scripts/fetch-arch-data.js
node "<技能目录绝对路径>\scripts\fetch-arch-data.js" --url <GITNEXUS_URL> --repo <REPO_NAME> --with-snippets

# 示例（Windows PowerShell，不支持 && 链式命令，须分开执行或用 ; 分隔）：
node "D:\git\ai_dev\GitNexus\.cursor\skills\whalecloud-dev-tool-arch-create\scripts\fetch-arch-data.js" --url http://10.x.x.x:11011 --repo ZMDB --with-snippets
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
- 对每个功能项，汇总 Phase 1b 中的追踪结果：功能说明 + 涉及文件列表
- 在分层架构分析时，每层必须显式标注「承载核心功能：[功能名列表]」
- 在运行态分析时，关键执行流必须包含核心功能项的完整路径（如有代码依据）

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

## Phase 3: 图示（强制执行）

**此步骤不可被跳过**，必须生成技术架构所需的 **两张** `.excalidraw` JSON 文件（与核心约束 §1 一致）。

### 实际操作流程

"调用 whalecloud-dev-tool-excalidraw" 的完整含义是：

1. 用 Read 工具读取技能文件 `../whalecloud-dev-tool-excalidraw/SKILL.md`（若在工作区 skills 目录中找不到，尝试系统 skills 目录 `C:\Users\<用户>\.cursor\skills\EXCALIDRAW-DIAGRAM-SKILL\SKILL.md`）
2. 读取 `../whalecloud-dev-tool-excalidraw/references/color-palette.md` 获取颜色规范
3. 读取 `../whalecloud-dev-tool-excalidraw/references/element-templates.md` 获取 JSON 元素模板
4. **按该技能的规则，直接用 Write 工具写出 `.excalidraw` JSON 文件**到目标目录

> ⚠ 这不是「调用另一个 Agent」或「子进程调用」，而是读取 excalidraw 技能规范后，自己生成符合规范的 JSON 文件。不要等待外部工具响应。

**与 PNG 导出**：若团队使用 **Markdown + Excalidraw 插件（如 React 预览）** 在同页渲染 `.md` 与 `.excalidraw`，则**不必**再走 `render_excalidraw.py` 生成 PNG；技术架构文档中用 **指向 `.excalidraw` 的链接** 即可。PNG 渲染循环仅作为**无插件环境下的可选质控**（与「内嵌链接」不是同一硬性步骤）。

### 两张图的调用时机

| 图 | 所属文档 | 章节 | 调用描述要点 |
|----|---------|------|-------------|
| 图 A：技术栈依赖图 | 技术架构文档 | §3.3 | 语言 → 依赖库 → 外部系统；节点来自构建文件 |
| 图 B：系统分层架构 | 技术架构文档 | §4.1 | 从用户入口到数据层的分层框；层名来自源码目录；各层注明核心功能 |

### 图示与文档的合并

- 将 whalecloud-dev-tool-excalidraw 生成的图（嵌入链接或内嵌内容）放入对应章节的 `{{DIAGRAM_*}}` 占位符处
- 图下方补一句「图示来源」，说明对应源码路径
- 两张图都完成后再进入 Phase 4 组装文档

## Phase 4: 文档组装（双文档）

输出两份独立文档，内容不交叉，以功能架构为主要文档：

### 4A. 功能架构文档（主文档）FUNCTIONAL_ARCH.md

使用 [func-arch-template.md](func-arch-template.md)：

1. **§1～2**：产品简介、产品定位 — 以 `PRODUCT_DESC` 为基础，源码为论据。
2. **§3**：核心功能详解 — 以 `CORE_FEATURES` 为骨架，逐项展开：
   - 功能说明（结合产品描述和源码分析）
   - 代码影响范围（Phase 1b 追踪到的文件列表，精确到文件级别）
   - 关键入口（主要类/方法名）
3. **§4**：业务能力矩阵 — 能力 | 用户可感知结果 | 主要实现位置 | 成熟度
4. **§5**：使用场景 — 以核心功能为维度描述典型场景和交互流程
5. **§6**：功能边界与非目标
6. **§7**：ADR、技术债、演进建议（功能视角）

> **不包含**：技术栈表格、分层架构图、进程清单、编译宏、构建系统、工程度量指标

### 4B. 技术架构文档（补充文档）TECH_ARCH.md

使用 [tech-arch-template.md](tech-arch-template.md)：

1. **§1**：技术概览（1 段，引用功能架构文档，不重复产品定位）
2. **§2**：仓库与工程事实（README 摘要、目录边界、构建系统）
3. **§3**：技术栈（语言分布、框架依赖、技术栈依赖图 A）
4. **§4**：系统分层架构（分层架构概览图 B、各层详解）
   - 每层必须注明「承载核心功能：[功能名列表]」（与功能架构形成交叉引用）
5. **§5**：运行形态与执行流（常驻进程、工具进程、核心执行流）
   - 执行流需标注涉及的核心功能项
6. **§6**：模块依赖与变更风险
7. **§7**：附录（工程度量、数据采集说明）

> **不重复**：产品定位描述、场景分析、业务能力说明、功能边界

占位符映射：`{{INDEXED_AT}}` ← `indexedAt`；`{{REPO_ROOT_HINT}}` ← `repoPath`；`{{INDEX_STATUS}}` ← 新鲜度说明；各 `{{METRICS_*}}` 来自 `context.stats`；daemon/tool 计数来自 `processInventory`。

## Checklist

**首次生成：**

```
用户传入信息处理：
- [ ] PRODUCT_DESC 已提取（或标记为空，使用 README 替代）
- [ ] CODE_PATH 已提取（或标记为空，使用默认扫描策略）
- [ ] CORE_FEATURES 已提取并建立追踪表格（或标记为空）

索引与源码读取：
- [ ] GITNEXUS_URL / REPO_NAME（若用脚本）已确认
- [ ] `gnx-tools.js materialize` 已运行并存在 `GNX_CACHE_DIR/files`
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
- [ ] CORE_FEATURES 中每项都已完成代码追踪（文件级别）
- [ ] 未追踪到代码的项已标记「[待源码确认]」

分析与确认：
- [ ] 产品定位（以 PRODUCT_DESC 为基础）已写（每段有源码路径作为论据）
- [ ] 动态分层已提出并与用户确认（含源码路径证据 + 覆盖的核心功能项）

图示生成：
- [ ] 已调用 whalecloud-dev-tool-excalidraw 生成图 A（技术栈）并内嵌到技术架构 §3.3
- [ ] 已调用 whalecloud-dev-tool-excalidraw 生成图 B（架构总览）并内嵌到技术架构 §4.1

文档输出：
- [ ] func-arch-template 已填满（CORE_FEATURES 逐项含代码影响范围）
- [ ] tech-arch-template 已填满（各层注明承载核心功能，不重复功能描述）
- [ ] FUNCTIONAL_ARCH.md 已写入目标路径（主文档）
- [ ] TECH_ARCH.md 已写入目标路径（补充文档）
- [ ] 两份文档内容不交叉（功能架构无技术栈/分层图，技术架构无产品定位/场景）
```

**迭代：** 更新 overrides → 重映射层 → 仅重画受影响图、更新对应章节。
新增 CORE_FEATURES 项时：补充代码追踪 → 更新功能架构 §3 → 更新技术架构各层标注。

## Error Handling

| 错误 | 处理 |
|------|------|
| `ECONNREFUSED` | 检查 URL；跳过 Phase 1，直接从 Phase 1b 开始（仅源码路径） |
| `Repo not found` | 用脚本绝对路径加 `--list` 参数列出可用仓库名 |
| 索引过期 | 提示在索引所在环境执行 `npx gitnexus analyze --embeddings` 后重新导出 |
| 找不到脚本 `scripts/fetch-arch-data.js` | 使用技能目录的绝对路径：`node "<技能绝对路径>\scripts\fetch-arch-data.js" ...`（技能目录名为 `whalecloud-dev-tool-arch-create`） |
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
| CORE_FEATURES 某项无法追踪到源码 | 标记「[待源码确认]」，在功能架构文档 §6.3 中列出；不要因为一项未追踪到而卡住整个流程 |
| 用户未传入 PRODUCT_DESC / CORE_FEATURES | 从 README（若存在）或 **`CODE_PATH` 下文件头/模块注释** 提取产品简介作为 PRODUCT_DESC 替代；CORE_FEATURES 为空时，跳过核心功能骨架约束，按通用章节结构生成文档 |

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
- **图示技能（必须调用）**：`../whalecloud-dev-tool-excalidraw/SKILL.md` — 安装在系统 skills 目录，当前工作区不可见不代表不可用，Phase 3 必须读取并执行该技能
- 代码探索：[gitnexus-exploring](../gitnexus-exploring/SKILL.md)（在需要 MCP 深入某符号时）
