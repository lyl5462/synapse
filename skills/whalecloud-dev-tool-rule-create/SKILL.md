---
name: whalecloud-dev-tool-rule-create
description: "基于 FUNCTIONAL_ARCH + TECH_ARCH，结合 GitNexus 源码缓存核验，生成经代码证据支撑的单一 AGENT.md（四维结构控熵 + 研发约束规则合一）；GITNEXUS_URL/REPO_NAME/GNX_CACHE_DIR 必选。OUT_DIR 默认 docs/；主产出 AGENT.md，元数据（WRITE_META≠false）固定为 agent-doc-meta.json。"
---

# 仓库结构控熵 + 研发约束规则生成（双架构输入 · GitNexus 必选 · 可重复）

**权威输入**由参数 **`PATH_FUNCTIONAL_ARCH`**、**`PATH_TECH_ARCH`** 指定（两份 Markdown 的路径与文件名由项目自定）。

- **功能架构**（`PATH_FUNCTIONAL_ARCH`）— 产品定位、核心功能、场景、边界  
- **技术架构**（`PATH_TECH_ARCH`）— 技术栈、分层、运行态、依赖风险  

在 **`OUT_DIR`** 下生成（未指定时默认为**工程主目录**下的 **`docs/`**）。

---

## 命名规则

| 产出 | 文件名 |
|------|--------|
| 研发规范（结构 + 约束合一） | `AGENT.md` |
| 元数据（若写） | `agent-doc-meta.json` |

---

## Parameters

| Parameter | 必填 | 说明 / 示例 |
|-----------|------|----------------|
| `PATH_FUNCTIONAL_ARCH` | 是 | 如 `./docs/ACME_FUNCTIONAL_ARCH.md`（路径、前缀须与本仓库一致） |
| `PATH_TECH_ARCH` | 是 | 如 `./docs/ACME_TECH_ARCH.md`（同上） |
| `REPO_NAME` | 是 | 与 `gitnexus serve` / 图谱一致，如 `ACME` 或 `ACME@@develop` |
| `GITNEXUS_URL` | 是 | 必须外部传入使用 |
| `GNX_CACHE_DIR` | 是 | `materialize` 缓存根目录，其下须有 `files/`（若尚无则 Phase 2 先执行 `materialize`） |
| `OUT_DIR` | 否 | 默认 `./docs` |
| `USER_SECTION_MAP` | 否 | 章节标题漂移时显式映射 |
| `WRITE_META` | 否 | 默认 `false`；显式 `true` 时写 meta 文件 |

**信息优先级**：双架构文档为叙事骨架 → **`GNX_CACHE_DIR` 内 `read`/`grep` 与索引导出为代码层事实**；二者冲突时以**可复现的缓存读段 / grep 命中**为准，在 `AGENT.md` 正文**仅**标「[与架构文档待对齐]」，**不要**写参考文档章节号/节名作脚注；**GitNexus 执行记录、embeddings、重跑对账、输入章节匹配留痕**等不写入 `AGENT.md`，见 **`agent-doc-meta.json`**（`WRITE_META≠false` 时）。

---

## 核心约束（违反视为未完成本技能）

### A. GitNexus / 源码缓存**必选**

- 未提供 **`GITNEXUS_URL`、`REPO_NAME`、`GNX_CACHE_DIR`**，或无法在缓存内完成核验：**中止**，不得输出声称已完成代码核验的 `AGENT.md`。  
- **`AGENT.md`** 中：凡**分层路径、模块边界、关键符号、风格模式**等结论，须在 `GNX_CACHE_DIR/files` 上通过 **`gnx-tools.js read` 或 `grep`** 至少各给出一条可核对证据；无法验证的条目必须标 **`[待代码确认]`**，不得装作已验证。  
- **§2 各层「职责」**若仅有一句泛化描述、缺少「输入/主责/下推/不负责」中任一维度，**视为**分层结构**未完成**。  
- 推荐顺序：`materialize`（若缓存不全）→ `overview --out`（UTF-8）→ 按需 `fetch-arch-data.js` → 针对 AGENT 提纲逐项 `grep`/`read`。  
- `embeddings=0` 时：索引聚类**不可**单独作为分层事实；仍可用 `grep`/`read` 与 REST 路径事实。

### B. 产出文件名

- 主产出固定命名为 **`AGENT.md`**，元数据固定命名为 **`agent-doc-meta.json`**，均置于 `OUT_DIR` 下。

### C. `AGENT.md` 正文**禁止**收录的内容

- **禁止**整段或整表：「与输入文档的映射」「来自双架构 §x / 第 x 节」「功能架构 §3.1 对应…」等**对参考文档位置的追溯**；此类内容若需留痕，写入 **`agent-doc-meta.json`**。  
- 与参考架构冲突时，正文**仅**允许出现标记 **`[与架构文档待对齐]`**（不附带对方章节号）。

---

## 参考架构解析（仅执行侧，不写入 AGENT.md）

生成时须读入 `PATH_FUNCTIONAL_ARCH` 与 `PATH_TECH_ARCH`（路径与内容由项目自定，**不必**与某固定模板逐节一致）。当标题漂移、或无法与内部「期望块」一一对应时，在**执行过程**中按下述**优先级**取语义块（**不**把该过程以「章节对照表」写进 `AGENT.md`）：

1. **`USER_SECTION_MAP`**：用户显式指定「实际标题 / 行块 → 语义块」。  
2. **锚点与编号**：`##` 加数字标题时，按编号作弱匹配（节数**仅**作常见习惯参考，以**实际文件**为准）。  
3. **关键词模糊匹配**：如产品简介、核心能力、分层、运行态、依赖等中文/英文标题。

---

## Workflow

```
Phase 0 — 输入与命名
  0a. 校验 PATH_FUNCTIONAL_ARCH、PATH_TECH_ARCH、REPO_NAME、GITNEXUS_URL、GNX_CACHE_DIR；缺一则中止。
  0a1. OUT_DIR：未指定则用 <工程根>/docs；目录不存在则创建。
  0b. 解析双文档标题树；章节漂移绑定；建提纲（功能↔路径↔术语）。不在 AGENT.md 中输出章节/位置对照（见核心约束 C）。
  0c. 若 WRITE_META≠false：准备 agent-doc-meta.json 字段。

Phase 1 — 双文档精读（必选）
  抽取 AGENT.md 初稿所需事实（仍以双 MD 为骨架，为 Phase 2 核验准备提纲）；对 §2 分层逐层整理职责四维初稿：输入边界、本层主责、下推给下层的内容、与相邻层排除项，便于 Phase 2 在缓存中用类名/路径核对。

Phase 2 — GitNexus / 源码缓存核验（必选）
  2a. 若 GNX_CACHE_DIR 无 manifest 或 files 明显不全：node <SKILL_DIR>/scripts/gnx-tools.js materialize --url … --repo … --cache …
  2b. overview --out <UTF-8 路径>；按需 fetch-arch-data.js（参数以脚本 --help 与本 Phase 说明为准）。
  2c. 对 AGENT 提纲中每条「路径、层、模块、命名模式」执行 read/grep，记录证据（路径+摘录或模式）。
  2d. 【基础能力专项枚举——用于 §4.2】
      基础设施目录以本仓库 overview clusters 与 §2.1 分层表为准（如 lib/、common/、internal/base/ 等，不要假定为某一固定名字）。
      下述 grep 为示例模式；须按主语言替换关键词（C/C++/Java：class；Go：type；Python：class；TS：interface/class 等）：
        - 网络通信：class.*Socket、HttpClient、或 Go net.Dial 周边封装类型等
        - 线程与并发：class.*Thread、Mutex、或语言自带的并发原语包装类型
        - 进程间通信 / 共享内存：class.*Shm、或本仓库 IPC 包名
        - 配置加载：*Config、loadConfig、Viper/Env 封装等
        - 日志输出：*Log、Logger、zap/zerolog/slog 封装等
        - 异常 / 错误：Error、Exception 或本仓库 errcode 包
        - 序列化：*Codec、json/protobuf 封装
        - 数据访问：*Repository、*DAO、*Store 等
        - 缓存：*Cache 及 Get/Put/Invalidate
        - 时间 / 定时器：*Timer、*Schedule
        - 内存池 / 分配器：*Pool、*Alloc
        - 工具：*util*、*Helper 包或类
      每个命中类须 read 至实现或接口定义，摘录公开方法/函数名与参数，填入 §4.2；仅适用于本仓库的模式若与示例不符，以 agent-template §4.2 模板 + 实仓 grep 为准。
  2e. embeddings=0 时不得在 AGENT.md 中另起「索引与核验」章节；须在 agent-doc-meta.json 中写明聚类不可用于分层事实。
  2f. 与双文档冲突处：以缓存证据为准并标 [与架构文档待对齐]。

Phase 3 — AGENT.md（必选）
  按 agent-template 一体生成，§1～§5 顺序填写；推荐顺序：先填 §2.1→§3.1→§4.1→§4.2→§5.1～5.5（描述侧），再从已填内容推导约束（§2.2/§3.2/§4.2 禁止论断/§5.6/§1 速查）。

  - §1 速查约束：最后回填；从 §2.2/§3.2/§4.2/§5.6 中各抽取 2～4 条最关键的必须/禁止，保持简短，便于 Agent 快速扫读。

  - §2 分层结构
    · §2.1 分层概览：每个逻辑层的「职责」须按四维写全（输入边界 / 本层核心主责+代表类 / 下推输出 / 不负责项），禁止只写一句泛化描述；类名须来自本仓 grep 或标 [待代码确认]。
    · §2.2 改造边界规则：从 §2.1 依赖方向 + 扇入分析派生，分「可安全改动 / 禁止或谨慎 / 须走 RFC/ADR」三块，用「必须/禁止」约束动词写成指令格式。

  - §3 语义结构
    · §3.1 核心术语：术语 | 含义（一句话）| 代码落点；来自 GNX grep 或标 [待代码确认]。
    · §3.2 语义一致性规则：命名后缀约定、禁止双名、API 与功能架构用词一致性等，指令格式。

  - §4 功能结构
    · §4.1 功能与代码落点：功能项 | 用户结果 | 主要代码落点（已 grep 验证）| 关联层；不写参考架构章节号。
    · §4.2 基础能力组件清单：从 Phase 2 专项枚举结果填写，含能力分类 + 类型/包名 + 关键公开 API + 定义处 + 复用方式；每类能力末尾写「禁止」论断（指令格式）；无该能力则标 [不适用]。

  - §5 风格结构
    · §5.1～5.5（描述侧）：命名约定（按语言+标识符类型逐行）、目录布局、错误处理、日志/注释风格、条件编译宏；来自 read/grep 的真实代码风格，不得仅叙述模板。
    · §5.6 风格强制规则：从 §5.1～5.5 提炼，用「必须/禁止」约束动词写成指令格式（命名/日志/错误/宏）。

Phase 4 — 元数据与自检
  4a. 若 WRITE_META≠false：写 agent-doc-meta.json，至少包含：GITNEXUS_URL、REPO_NAME、GNX_CACHE_DIR；是否执行 materialize / overview / fetch-arch-data（及时间）；embeddings 与聚类可信度；采纳或否定的索引导出结论；[与架构文档待对齐] 与证据摘要；PATH_FUNCTIONAL_ARCH / PATH_TECH_ARCH 版本或生成时间、建议重跑触发条件、与本次产出对账。
  4a1. 若 WRITE_META=false：不得在 AGENT.md 中补写核验/元数据章节；可在技能执行说明或团队 Wiki 中保留摘要（可选）。
  4b. 执行 Checklist；未满足核心约束 A/B/C 则视为失败并说明缺口。
```

Windows PowerShell **不要使用 `&&`** 链式命令。

---

## Additional Resources

- [agent-template.md](agent-template.md)

---

## Checklist

**生成前**

- [ ] `PATH_FUNCTIONAL_ARCH`、`PATH_TECH_ARCH`、`REPO_NAME`、`GITNEXUS_URL`、`GNX_CACHE_DIR` 已确认  
- [ ] `OUT_DIR` 已解析  

**GitNexus 与核验**

- [ ] `materialize` 已满足后续 `read`/`grep` 需要（或缓存已完整）  
- [ ] `overview --out` 已写 UTF-8 JSON（未用 `>` 重定向致乱码）  
- [ ] `AGENT.md` §2～§5 关键结论均有缓存内证据或标 `[待代码确认]`  

**产出**

- [ ] `AGENT.md` 已生成于 `OUT_DIR`，含五节：§1 速查约束 / §2 分层结构 / §3 语义结构 / §4 功能结构 / §5 风格结构  
- [ ] `AGENT.md` 正文中**无**「与输入文档的映射」、**无**「来自双文档 §x」等参考位置追溯（若需留痕在 `agent-doc-meta.json`）  
- [ ] §2.1 分层概览中**每个逻辑层**的「职责」已按四维（输入边界 / 本层主责+代表类 / 下推输出 / 不负责项）写全，非单句口号  
- [ ] §2.2 改造边界规则已填（可改/禁改/RFC 三块）  
- [ ] §3.2 语义一致性规则已填（指令格式）  
- [ ] §4.2 基础能力清单：各能力分类含类型名 + 公开 API + 定义处 + 禁止论断；无该能力标 `[不适用]`  
- [ ] §5.1～5.5 已填真实代码风格（非空模板）  
- [ ] §5.6 风格强制规则已填（指令格式）  
- [ ] §1 速查约束已从 §2～§5 中提炼回填  
- [ ] 若 `WRITE_META≠false`：`agent-doc-meta.json` 已写，含 GitNexus/索引/重跑对账等元信息；若 `WRITE_META=false`：确认未在 `AGENT.md` 中补写元数据章节  

---

## Error Handling

| 情况 | 处理 |
|------|------|
| 缺 `GITNEXUS_URL` / `REPO_NAME` / `GNX_CACHE_DIR` | **中止**，列出缺失参数 |
| `materialize` / `overview` / 服务不可达 | **中止**；不得输出声称已完成代码层核验的 `AGENT.md` |
| 缓存中无某路径 | 标 `[待代码确认]`，不得虚构 |
| 双文档互链断裂 | 用手动相对路径修复链接；核验仍以缓存为准 |
| `OUT_DIR` 不可写 | 中止并说明 |
| 章节无法匹配 | 关键词次选 + `USER_SECTION_MAP` |

---

## 冲突与优先级

**代码层可验证事实**（`GNX_CACHE_DIR` + 工具输出）优于双文档中的路径/分层叙述；双文档优于未验证的索引聚类。`AGENT.md` 中已核验事实与双文档冲突时，须在 AGENT.md 内**仅**标注「[与架构文档待对齐]」（**不**写对方文档章节号），**禁止**在未获授权时修改作为输入的 `PATH_FUNCTIONAL_ARCH` / `PATH_TECH_ARCH` 所指向的源文件。
