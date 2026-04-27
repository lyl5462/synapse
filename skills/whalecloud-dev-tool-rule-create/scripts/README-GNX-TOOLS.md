# gnx-tools.js — 与 GitNexus REST 接口对齐的取数封装

> 本目录为本技能附带的 **GitNexus 辅助脚本**（`materialize` / `overview` / `read` / `grep` 等），用于在本地缓存上完成源码核验与可选索引抽检。

## 设计目标

- **在线**：`cypher` / `search` / `overview` / `explore` / `impact` 仅通过 GitNexus 服务端公开的 **REST**（如 `/api/query`、`/api/search` 等），与当前部署的 GitNexus 版本契约一致。
- **read / grep**：默认只读 **`materialize` 写入的本地缓存**（`--cache/files/`），避免反复 `GET /api/file`。

## 路径占位符

下文与示例中的 **`<SKILL_DIR>`** 表示本技能目录的**绝对路径**，例如：

- Windows：`D:\code\GitNexus\gitnexus\skills\whalecloud-dev-tool-rule-create`
- 在终端中可先设：`$SKILL = "D:\code\GitNexus\gitnexus\skills\whalecloud-dev-tool-rule-create"`，再用 `"$SKILL\scripts\gnx-tools.js"`。

## 工程类型检测

在 `materialize` 完成后，可在同一 `$CACHE` 上运行：

```powershell
node "<SKILL_DIR>\scripts\gnx-tools.js" overview --url $GNX --repo $REPO --out "$CACHE\overview.json"
node "<SKILL_DIR>\scripts\detect-project-kind.js" --cache $CACHE --overview "$CACHE\overview.json"
```

**勿用** `overview ... > file.json`（PowerShell 默认 UTF-16，`detect-project-kind` 虽已尽量兼容，仍建议 `--out` 写 UTF-8）。

## 依赖

- Node.js **18+**
- 本机可访问 `gitnexus serve`（例如 `http://127.0.0.1:11011`）
- 已索引的 `REPO` 名称与图谱嵌入页一致（如 `MyProj@@branch`）

## 常用命令

在 `scripts` 目录下执行时可直接写 `gnx-tools.js`；否则使用绝对路径调用。

```bash
# 1）一次性拉取文件正文到缓存（会打 /api/graph 与若干 /api/file）
#    大仓库建议：不要加 --max-files，除非磁盘/网络受限（避免缓存截断）
node gnx-tools.js materialize --url http://127.0.0.1:11011 --repo YOUR_REPO --cache ./gnx-cache --concurrency 8 --verbose --progress-every 50

# 2）结构化查询（POST /api/query）
node gnx-tools.js cypher --url http://127.0.0.1:11011 --repo YOUR_REPO --cypher "MATCH (f:File) RETURN f.filePath AS p LIMIT 5"

# 3）混合检索（POST /api/search）
node gnx-tools.js search --url http://127.0.0.1:11011 --repo YOUR_REPO --query "cluster manager" --limit 10

# 4）仅读缓存（不打服务器）
node gnx-tools.js read --cache ./gnx-cache --path path/inside/repo/File.cpp

# 5）仅在缓存内正则（不打服务器）
node gnx-tools.js grep --cache ./gnx-cache --pattern "#include.*Foo" --glob ".cpp" --max 50

# 6）概览（推荐 --out 写 UTF-8 JSON）
node gnx-tools.js overview --url http://127.0.0.1:11011 --repo YOUR_REPO --out ./overview.json

# 7）探索 / 影响
node gnx-tools.js explore --url http://127.0.0.1:11011 --repo YOUR_REPO --target <SymbolName>
node gnx-tools.js impact --url http://127.0.0.1:11011 --repo YOUR_REPO --target SomeSymbol --direction upstream --depth 1
```

环境变量（可替代 `--url` / `--repo` / `--cache`）：

- `GITNEXUS_URL`
- `GNX_REPO`
- `GNX_CACHE`

---

## 在本地终端做「真实验证」的步骤

### A. 准备变量

```powershell
$SKILL = "<SKILL_DIR>"   # 替换为 whalecloud-dev-tool-rule-create 绝对路径
$GNX = "http://127.0.0.1:11011"
$REPO = "你的仓库键"
$CACHE = "$PWD\gnx-cache-test"
```

### B. 拉缓存

```powershell
node "$SKILL\scripts\gnx-tools.js" materialize --url $GNX --repo $REPO --cache $CACHE --concurrency 6
```

### C. 验证 read / grep（停服后仍应可读缓存）

```powershell
node "$SKILL\scripts\gnx-tools.js" read --cache $CACHE --path <manifest 中某相对路径>
node "$SKILL\scripts\gnx-tools.js" grep --cache $CACHE --pattern "include" --max 20
```

### D. 在线子命令

```powershell
node "$SKILL\scripts\gnx-tools.js" search --url $GNX --repo $REPO --query "test" --limit 5
node "$SKILL\scripts\gnx-tools.js" overview --url $GNX --repo $REPO --out "$CACHE\overview.json"
```

### E. fetch-arch-data.js（可选）

```powershell
node "$SKILL\scripts\fetch-arch-data.js" --url $GNX --repo $REPO --out arch-data.json --debug-dump "$PWD\debug-fetch-dump"
```

当 `GET /api/clusters` / `processes` 为空时，可先 `overview --out` 生成 `overview.json`，再运行 `fetch-arch-data.js`（脚本会尝试合并同目录下的 `overview.json`）。完整参数与行为见：`node "<SKILL_DIR>/scripts/fetch-arch-data.js" --help`。

---

## 限制说明

- `explore` / `impact` 为简化 Cypher；复杂场景请用 `cypher` 子命令。
- `materialize` 慎用 `--max-files`，以免缓存截断导致后续 `read: not in cache`。
