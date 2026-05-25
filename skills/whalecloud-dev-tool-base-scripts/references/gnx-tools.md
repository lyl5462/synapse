# gnx-tools.js — 与 Nexus（gitnexus-web Backend）对齐的取数封装

## 设计目标

- **在线**：`cypher` / `search` / `overview` / `explore` / `impact` 仅通过 GitNexus **REST**（`/api/query`、`/api/search`），与 `gitnexus-web` `createHttpExecuteQuery` / `createHttpHybridSearch` 同源。
- **read / grep**：默认只读 **`materialize` 写入的本地缓存**（`--cache/files/`），避免 Phase 1b 反复 `GET /api/file`。

## 产品关联仓库名（勿手填 `REPO_NAME`）

用本技能（`whalecloud-dev-tool-base-scripts`）根目录下 `scripts/get_repo_info.py`（`--server-url` + `--prod`）从 SynapseService 拉取产品对应的 Git 仓库名列表，再作为 `gnx-tools.js --repo` 与 `--cache` 目录名。详见 [get_repo_info.md](get_repo_info.md)。

## 工程类型检测（与 SKILL Phase 0.1 对齐）

在 `materialize` 完成后，可在同一 `$CACHE` 上运行：

```text
run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="gnx-tools.js", args=["overview", "--url", "<GITNEXUS_URL>", "--repo", "<REPO>", "--out", "<CACHE>/overview.json"])
run_skill_script(skill_name="whalecloud-dev-tool-base-scripts", script_name="detect-project-kind.js", args=["--cache", "<CACHE>", "--overview", "<CACHE>/overview.json"])
```

**勿用** `overview ... > file.json`（PowerShell 默认 UTF-16，`detect-project-kind` 虽已尽量兼容，仍建议 `--out` 写 UTF-8）。

## 依赖

- Node.js **18+**
- 本机可访问 `gitnexus serve`（例如 `http://127.0.0.1:11011`）
- 已索引的 `REPO` 名称与图谱嵌入页一致（如 `MyProj@@branch`）

## 常用命令

```bash
# 0）健康检查（可选）：浏览器或 curl 打开
#   GET http://127.0.0.1:11011/api/repo?repo=YOUR_REPO

# 1）一次性拉取文件正文到缓存（会打 /api/graph 与若干 /api/file）
node gnx-tools.js materialize --url http://127.0.0.1:11011 --repo YOUR_REPO --cache ./gnx-cache --max-files 800 --concurrency 8 --verbose --progress-every 50

# 2）结构化查询（POST /api/query）
node gnx-tools.js cypher --url http://127.0.0.1:11011 --repo YOUR_REPO --cypher "MATCH (f:File) RETURN f.filePath AS p LIMIT 5"

# 3）混合检索（POST /api/search）
node gnx-tools.js search --url http://127.0.0.1:11011 --repo YOUR_REPO --query "cluster manager" --limit 10

# 4）仅读缓存（不打服务器）
node gnx-tools.js read --cache ./gnx-cache --path path/inside/repo/File.cpp

# 5）仅在缓存内正则（不打服务器）
node gnx-tools.js grep --cache ./gnx-cache --pattern "#include.*Foo" --glob ".cpp" --max 50

# 6）概览（4 条固定 Cypher，与 Nexus overview 工具一致；推荐写文件避免 PowerShell 编码问题）
node gnx-tools.js overview --url http://127.0.0.1:11011 --repo YOUR_REPO --out ./overview.json

# 7）探索 / 影响（简化版 Cypher，输出 JSON）
node gnx-tools.js explore --url http://127.0.0.1:11011 --repo YOUR_REPO --target ZmdbClusterMgr
node gnx-tools.js impact --url http://127.0.0.1:11011 --repo YOUR_REPO --target SomeSymbol --direction upstream --depth 1
```

环境变量（可替代 `--url` / `--repo` / `--cache`）：

- `GITNEXUS_URL`
- `GNX_REPO`
- `GNX_CACHE`

---

## 在 Cursor 中做「真实验证」的步骤

以下假设仓库根为 **GitNexus 技能目录的上一级工程**（或任意终端 `cwd`），且你已本地启动 **`gitnexus serve`** 并完成某仓库索引。

### A. 准备变量

在 Cursor 终端（PowerShell）中：

```powershell
$GNX = "http://127.0.0.1:11011"
$REPO = "你的仓库键"   # 与 11001 图谱页 repo= 一致
$CACHE = "$PWD\gnx-cache-test"
```

### B. 拉缓存（唯一应大量访问 /api/file 的步骤）

```text
run_skill_script(
  skill_name="whalecloud-dev-tool-base-scripts",
  script_name="gnx-tools.js",
  args=["materialize", "--url", "<GITNEXUS_URL>", "--repo", "<REPO>", "--cache", "<CACHE>", "--max-files", "300", "--concurrency", "6"]
)
```

预期：

- 终端 stderr 出现 `materialize: wrote N files under ...\files`
- `$CACHE\manifest.json` 存在，`fileCount` > 0
- `$CACHE\files\` 下出现若干相对路径子目录与源文件

### C. 验证「read / grep 不打服务器」

1. **停掉 `gitnexus serve`**（或断网到该 IP）。
2. 从 `$CACHE\files` 里任选一个真实相对路径 `$REL`（与 manifest 中文件一致）。
3. 执行：

```powershell
node "$BASE\scripts\gnx-tools.js" read --cache $CACHE --path $REL
node "$BASE\scripts\gnx-tools.js" grep --cache $CACHE --pattern "include" --max 20
```

预期：仍能输出内容；**此时无 GitNexus 进程**，证明 read/grep 走本地缓存。

### D. 验证「在线五能力」与 Nexus 同源

重新启动 `gitnexus serve`，执行：

```powershell
node "$BASE\scripts\gnx-tools.js" search --url $GNX --repo $REPO --query "test" --limit 5
node "$BASE\scripts\gnx-tools.js" overview --url $GNX --repo $REPO
```

预期：stdout 为合法 JSON；无 `HTTP 4xx/5xx`。

将 `search` 输出与 **gitnexus-web** 同一 `repo` 下 Nexus 对话里 `search` 的结果对比（条目与 `filePath` 应高度一致；若 embeddings=0，服务端可能仅 FTS，仍属预期）。

### E. 与 `fetch-arch-data.js` 的对比验证（可选）

对同一 `$GNX`、`$REPO` 仍运行一次：

```powershell
node "$BASE\scripts\fetch-arch-data.js" --url $GNX --repo $REPO --out arch-data.json --debug-dump "$PWD\debug-fetch-dump"
```

比对：`gnx-tools.js overview` 中的 clusters/processes 数量级与 `arch-data.json` 中摘要是否矛盾；若有明显差异，先检查 **`REPO` 字符串是否完全一致**（含 `@@` 分支后缀）。**`--debug-dump`** 会在该目录写入原始 `GET /api/*` 与 MCP SSE 正文，便于与浏览器或 Nexus 抓包对照。

当 `GET /api/clusters` / `processes` 返回空数组时，`fetch-arch-data.js` **1.5.0+** 会自动读取 **`--out` 同目录下的 `overview.json`**（须先运行本节上面的 `overview --out`），把 Cypher 得到的聚类/流程写入 `arch-data.json` 的 `rawClusters`/`rawProcesses`；也可用 `--merge-overview <path>` 显式指定文件。

---

## 限制说明

- `explore` / `impact` 为 **简化 Cypher**，用于技能内自动化与人工验证；与 gitnexus-web 内 **100% 行级对齐** 的 `explore`/`impact` 工具相比，复杂场景可能需改回直接调用 `cypher` 子命令自定义查询。
- `materialize` 的 `--max-files` 默认保护上限；大仓可调大，但会显著增加 `/api/file` 次数与时间。
