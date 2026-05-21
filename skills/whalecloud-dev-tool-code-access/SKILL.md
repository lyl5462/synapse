---
name: whalecloud-dev-tool-code-access
description: "代码分析能力：通过 GitNexus 拉取/缓存产品关联仓库源码，执行检索、阅读、图查询与依赖分析，产出可引用的证据索引。供需求澄清等研发任务在需核验存量代码、源码检索、materialize 时由 Agent 从已挂载技能中选用。Examples: materialize、overview、search、grep、read、cypher、多仓库缓存。"
label: 代码访问
---

# 代码访问

对存量代码进行**可核对、可引用、多仓库**的访问与检索。脚本实现位于 **`whalecloud-dev-tool-base-scripts`**（`gnx-tools.js`、`get_repo_info.py`）；本技能定义**何时用、怎么用、证据如何标注**。

调用方业务技能在需要查代码、建缓存、维护证据索引时，**须加载本技能并按本文执行**；命令细节以本文为准，不在调用方技能中重复展开。

---

## 何时加载

- 首次会话需建立源码访问基线（materialize + overview）
- 圈定影响范围：模块/入口、关键词检索
- 核验实现、查依赖、读具体文件
- 任何结论涉及模块路径、接口、符号、依赖关系

**不必加载**：任务已标注 `[无代码触点]`；仅读产品文档且不经由本技能访问源码。

---

## 路径与参数

| 符号 / 参数 | 说明 |
|-------------|------|
| `<BASE_SCRIPTS_DIR>` | `whalecloud-dev-tool-base-scripts` 技能根目录 |
| `{PYTHON}` | `python3` → `py` → `python` |
| `GITNEXUS_URL` | GitNexus 服务地址（必填） |
| `SYNAPSE_URL` | Synapse 地址；与 `PROD` 配合解析仓库列表 |
| `PROD` | 产品名（自动拉仓时必填） |
| `GNX_REPO` | 可选；指定则仅访问该仓，跳过 `get_repo_info` |
| `TMP_DIR` | 缓存根目录；每仓 `{TMP_DIR}/{REPO_NAME}/` |
| `GNX_REPO_LIST` | 运行时维护的仓库名列表 |

---

## 能力一览

| 能力 | 子命令 | 在线/本地 | 典型场景 |
|------|--------|-----------|----------|
| 解析仓库列表 | `get_repo_info.py` | Synapse | 多产品仓 bootstrap |
| 同步源码 | `materialize` | 在线→写缓存 | 首次建库 |
| 项目概览 | `overview` | 在线→写文件 | 模块结构、`overview.json` |
| 混合检索 | `search` | 在线 | 关键词找符号/文件 |
| 图查询 | `cypher` | 在线 | 依赖、调用关系 |
| 缓存内搜索 | `grep` | 仅本地缓存 | 路径下二次确认 |
| 读文件 | `read` | 仅本地缓存 | 核对实现片段 |

进阶（按需）：`explore`、`impact` — 见 `<BASE_SCRIPTS_DIR>/references/README-GNX-TOOLS.md`。

---

## 核心契约

### C1. 多仓库

- 每个 `REPO_NAME` 独立目录：`{TMP_DIR}/{REPO_NAME}/`
- 跨仓结论**分别**检索，标注 `仓库名 + 路径/符号`
- 某仓 materialize 失败：标 **`[待补充-{REPO_NAME}]`**，继续其他仓；**全部失败则中止**

### C2. 证据

- 技术结论须有 `search` / `cypher` / `read` / `grep` 至少一条可核对结果
- 无法验证：**`[待代码确认]`**，不得虚构
- 维护 **证据索引**：`仓库 → 路径/符号 → 结论`（供调用方写入其交付物）

### C3. 调用方职责

- 调用方负责 `TMP_DIR` 及子目录创建（`mkdir -p {TMP_DIR}/{REPO}`）
- 会话结束是否删除缓存由调用方决定

---

## 操作指引

### Bootstrap（建立代码访问基线）

在 `TMP_DIR` 已创建前提下：

```bash
# 1）仓库列表（未传 GNX_REPO 时）
{PYTHON} <BASE_SCRIPTS_DIR>/scripts/get_repo_info.py --server-url={SYNAPSE_URL} --prod={PROD}
# 解析输出得 GNX_REPO_LIST；含「未找到仓库信息」→ 中止

# 2）逐仓同步 + 概览
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js materialize --url {GITNEXUS_URL} --repo {REPO_NAME} --cache {TMP_DIR}/{REPO_NAME}
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js overview --url {GITNEXUS_URL} --repo {REPO_NAME} --out {TMP_DIR}/{REPO_NAME}/overview.json
```

单仓模式：`GNX_REPO_LIST = [GNX_REPO]`，跳过步骤 1。

### 检索与阅读

```bash
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js search --url {GITNEXUS_URL} --repo {REPO_NAME} --query "关键词"
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js grep --cache {TMP_DIR}/{REPO_NAME} --pattern "关键词"
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js cypher --url {GITNEXUS_URL} --repo {REPO_NAME} --cypher "MATCH ..."
node <BASE_SCRIPTS_DIR>/scripts/gnx-tools.js read --cache {TMP_DIR}/{REPO_NAME} --path "相对路径"
```

可结合调用方提供的架构说明与 `overview.json` 做模块→仓库映射后，再选仓执行上述命令。

---

## Error Handling

| 情况 | 处理 |
|------|------|
| `get_repo_info` 无仓库 | **中止** |
| `GITNEXUS_URL` 不可达 | **中止**（若调用方要求必须有代码证据） |
| 全部 `materialize` 失败 | **中止** |
| 部分 `materialize` 失败 | 跳过该仓，标 `[待补充-{REPO_NAME}]` |
| `search`/`cypher`/`grep` 无结果 | 记录无匹配；若仍下结论则标 `[待代码确认]` |
| `read` 路径不在缓存 | 标 `[待代码确认]` |

---

## 与 base-scripts 的关系

- **实现**：`gnx-tools.js`、`get_repo_info.py` 仅在 `<BASE_SCRIPTS_DIR>/scripts/` 调用
- **本技能**：定义代码访问的语义、契约与操作组合；不复制脚本源码

加载本技能时，应同时确保 **`whalecloud-dev-tool-base-scripts`** 已在环境中可用。
