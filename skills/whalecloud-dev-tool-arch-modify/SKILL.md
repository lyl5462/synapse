---
name: whalecloud-dev-tool-arch-modify
description: "产品知识文档修改技能（源码优先 + 历史文档参考 + GitNexus 辅助）。以用户需求为驱动，以实际代码为依据，以历史文档为参照，精准修改产品架构文档（FUNCTIONAL_ARCH.md / TECH_ARCH.md / *.excalidraw）。Examples: 修改文档章节、补充功能说明、更新架构图、修正错误描述。"
---

# 产品知识文档修改（源码优先 · 历史文档参考 · 用户需求驱动）

修改目标文件（`targets[0]`）的内容，只改用户要求修改的部分，**绝不臆造**，**绝不删除**未被要求修改的章节。

> **三项核心原则（贯穿全程，不得违反）**
> 1. **以实际代码为基础不臆断**：所有新增/修改内容必须有源码依据；源码缓存未命中时须补充读取，不得凭空描述功能或实现细节。
> 2. **以历史文档为参考不造谣**：必须先读原始文档，保留未被要求修改的章节与措辞；不得凭借"记忆"或"推断"替换已有准确描述。
> 3. **以用户需求为根本不发散**：修改范围严格限定在用户指定的修改要求内，不得主动扩展修改其他章节。

---

## Parameters（从上下文自动解析）

| 参数 | 来源 | 说明 |
|------|------|------|
| `TARGET_FILE` | `targets[0]` | 待修改的文档文件名（如 `FUNCTIONAL_ARCH.md`） |
| `PROPOSED_PATH` | user 消息注入 | proposed/ 工作副本的完整路径（agent 只写此路径） |
| `PROD_NAME` | user 消息注入 | 产品标识 |
| `DOC_TYPE` | user 消息注入 | 文档类型 |
| `PRODUCT_DESC` | user 消息注入 | 产品描述（可为空） |
| `CODE_PATH` | user 消息注入 | 代码路径（可为空；用于定位源码） |
| `CORE_FEATURES` | user 消息注入 | 主要功能（可为空） |
| `USER_REQUEST` | user 消息 `## 用户修改要求` 段 | 用户本次的修改要求 |
| `GNX_CACHE_DIR` | `synapse_home/tmp/gitnexus/<repo>/` | GitNexus 本地缓存路径（见 Phase 1） |

---

## Workflow

```
Phase 0 — 解析用户修改意图（必选，首先执行）
  0a. 读取 user 消息，提取：
      - USER_REQUEST：用户要求修改的具体内容
      - TARGET_FILE：待修改文件名（即 targets[0]）
      - PROPOSED_PATH：proposed/ 下的工作副本完整路径
      - PRODUCT_DESC / CODE_PATH / CORE_FEATURES（系统注入上下文）
  0b. 将修改要求拆解为修改点列表：
      | 修改点 | 涉及章节（预判） | 需要源码验证？ | 状态 |
      |--------|----------------|--------------|------|
      | 修改点1 | §X.X           | 是/否        | 待处理 |
      ...
  0c. 判断修改类型：
      - 纯文字描述修改（描述纠错、措辞调整）→ 可能无需读源码
      - 功能新增/补充 → 必须读源码验证
      - 架构层级/关系调整 → 必须读源码验证
      - .excalidraw 图示修改 → 必须结合源码与历史图 JSON

Phase 1 — 历史文档读取（必选，源码读取前必须先执行）
  1a. 使用 read_file 读取 PROPOSED_PATH（会话 proposed/ 目录下的工作副本）。
      ⚠ 必须读完整文档，不得跳过任何章节。
  1b. 标注与修改要求相关的章节（记录行号范围或 ## 标题）。
  1c. 记录"不应被修改的章节"列表，后续写文件前做完整性校验。
  1d. 若 TARGET_FILE 为 .excalidraw，额外记录：
      - 现有节点数量与层级数量
      - 需要新增/修改/删除的节点或边

Phase 2 — 源码查阅（按修改点决定是否执行）
  ⚠ 以下情况必须执行 Phase 2，跳过须明确说明理由：
    - 修改点涉及功能描述、组件说明、模块划分、接口关系
    - 修改点要求新增代码影响范围或文件列表
    - 修改点要求修正或补充架构图节点/层级
  
  2a. 源码缓存检测（优先使用本地缓存，避免重复拉取）：
      从 user 消息中读取「源码缓存根目录」和「gnx-tools.js 脚本路径」两个参数，
      以及「GitNexus 服务地址」和代码路径中的 repo_name。

      检查缓存可用性（执行 list_directory）：
      ```
      list_directory(<源码缓存根目录>/files/)
      ```
      - 若返回文件列表 → 缓存命中，记录「使用本地缓存：<路径>」，跳到步骤 2b
      - 若目录不存在或为空 → 缓存未命中，进入步骤 2a-拉取

  2a-拉取（仅缓存未命中时执行）：
      使用 run_shell 执行 gnx-tools.js materialize 拉取源码到本地：
      ```
      node "<gnx-tools.js 脚本路径>" materialize \
        --url <GitNexus 服务地址> \
        --repo <repo_name> \
        --cache <源码缓存根目录> \
        --concurrency 8
      ```
      ⚠ Windows PowerShell 不支持 `&&` 链式，须使用绝对路径直接调用（参数均来自 user 消息注入，无需猜测）。
      ⚠ 不要加 `--max-files` 限制，默认全量拉取。
      ⚠ gnx-tools.js 来自 whalecloud-dev-tool-arch-create 技能的 scripts/ 目录，
         路径由系统注入到 user 消息「gnx-tools.js 脚本路径」字段，无需手动查找。

      拉取完成后，源码位于 `<源码缓存根目录>/files/` 下，继续步骤 2b。

      若 GitNexus 不可达（ECONNREFUSED 等）：
      - 记录「GitNexus 不可达，跳过源码拉取」
      - 将本次所有需要源码验证的修改点标注「[待源码确认：GitNexus 不可达]」
      - 继续后续步骤（不因此中断整个修改流程）

  2b. 源码定位（针对每个需要验证的修改点）：
      - 用 list_directory 浏览 `<缓存根目录>/files/` 目录结构，找到相关模块目录
      - 使用 CODE_PATH（若提供）缩小搜索范围：`<缓存根目录>/files/<CODE_PATH 对应子目录>`
      - 优先阅读：入口文件、与修改点功能名最匹配的模块/类文件
      - 记录：文件路径 → 找到的功能/接口/实现证据

  2c. 源码读取原则：
      - 每个修改点只读必要的源文件，不要全量读取
      - 读文件后立即记录「修改依据：<文件路径> → <具体证据>」
      - 若源码中找不到对应实现，须在文档中标注「[待源码确认：xxx]」，不得臆造

  2d. 对每个修改点更新依据表：
      | 修改点 | 涉及章节 | 源码依据文件 | 具体证据 | 状态 |
      |--------|---------|-------------|---------|------|
      | 修改点1 | §X.X   | path/to/file | 函数名/类名 | 已验证 |

Phase 3 — 文档修改（核心步骤）
  3a. 按 Phase 0b 的修改点列表，逐一修改文档内容：
      - 每处修改都要有 Phase 2 的源码依据（或在修改点标记「无需源码验证」的理由）
      - 修改范围严格限定在用户要求的章节/内容，不扩散到其他章节
      
  3b. 修改规则（每条均为强制约束）：
      - ✅ 保留所有用户未要求修改的章节，内容不变
      - ✅ 保留原文的 Markdown 标题层级与格式风格
      - ✅ 新增内容必须附有源码路径作为论据（至少文件级别）
      - ✅ 修改功能描述须与源码实现一致
      - ❌ 禁止删除用户未要求删除的章节
      - ❌ 禁止改变文件名（必须写回 PROPOSED_PATH 同名文件）
      - ❌ 禁止直接写入权威源文件目录（只允许写 proposed/ 子目录）
      - ❌ 禁止凭印象或推断描述功能，未找到源码证据前必须标注「[待源码确认]」
      
  3c. 对 .excalidraw 文件的额外规则：
      - 必须输出合法 JSON（可直接 JSON.parse 无报错）
      - 节点名称来自源码中真实的类名/函数名/目录名
      - 只修改用户要求变更的节点/边/布局，其余元素保留 id 不变
      - 优先用 write_file 写文件，避免在聊天中输出大段 JSON

Phase 4 — 完整性校验（写文件前必做）
  4a. 对照 Phase 1c 记录的「不应被修改的章节」列表，逐一检查是否被误改。
  4b. 确认修改后的文档包含原文所有 ## 一级标题（.excalidraw 跳过此步）。
  4c. 确认每处新增/修改内容都有对应的源码依据（或已标注「[待源码确认]」）。
  4d. 确认文件名与 targets[0] 完全一致。

Phase 5 — 写回文件
  5a. 使用 write_file 将完整修改后的文档写回 PROPOSED_PATH（proposed/ 目录下的工作副本）。
      ⚠ 必须写入**完整文档**，不得只写修改的部分片段。
  5b. 写文件后，在回复中简要说明：
      - 修改了哪些章节（对应 Phase 0b 的修改点列表）
      - 每处修改的源码依据（文件路径级别）
      - 若有「[待源码确认]」标注，说明原因
```

---

## 源码缓存路径说明

所有源码相关路径**由系统直接注入到 user 消息中**，无需自行推断：

| user 消息字段 | 含义 |
|-------------|------|
| `源码缓存根目录：[...]` | GitNexus materialize 产物根目录，源码位于其下 `files/` 子目录 |
| `gnx-tools.js 脚本路径：[...]` | 来自 `whalecloud-dev-tool-arch-create` 技能的 scripts/gnx-tools.js 绝对路径 |
| `GitNexus 服务地址：[...]` | 拉取时使用的 `--url` 参数 |
| `代码路径：[...]` | 仓库内相对路径或 URL，用于确定 `--repo <repo_name>` |

**三步判断逻辑（Phase 2a）**：
```
1. list_directory(<源码缓存根目录>/files/)
   → 有文件：直接读缓存，跳过拉取
   → 无文件或目录不存在：继续步骤 2

2. run_shell: node "<gnx-tools.js路径>" materialize
              --url <GitNexus服务地址> --repo <repo_name>
              --cache <源码缓存根目录> --concurrency 8
   → 拉取成功：继续步骤 3
   → ECONNREFUSED / 超时：标注「[待源码确认：GitNexus不可达]」，跳过源码验证

3. 拉取后再次 list_directory 确认，然后 read_file 读取目标文件
```

**`<repo_name>` 提取规则**：从 `代码路径` 字段取路径最后一段（去掉 `.git` 后缀），与 `源码缓存根目录` 路径的最后一段应一致。

---

## 工具白名单

本技能允许使用以下工具（与后端 `_REFINE_TOOL_NAMES` 白名单一致）：

| 工具 | 用途 |
|------|------|
| `read_file` | 读取 proposed/ 工作副本、源码缓存文件、架构文档 |
| `write_file` | 将修改后的完整文档写回 proposed/ 工作副本 |
| `list_directory` | 列举 proposed/、源码缓存目录结构 |
| `run_shell` | **仅用于**源码缓存未命中时执行 `gnx-tools.js materialize` 拉取 |

> ⚠ `run_shell` 只允许运行 `node <gnx-tools.js路径> materialize ...`，禁止用于其他用途。
> ⚠ **禁止**调用 `search_web` 或其他未列出的工具。

---

## Checklist

```
解析阶段：
- [ ] USER_REQUEST 已提取并拆解为修改点列表
- [ ] TARGET_FILE / PROPOSED_PATH 已确认
- [ ] PRODUCT_DESC / CODE_PATH / CORE_FEATURES 已读取

历史文档阅读：
- [ ] 已用 read_file 读取 PROPOSED_PATH 完整内容
- [ ] 已标注与修改要求相关的章节
- [ ] 已记录「不应被修改的章节」列表

源码查阅（若需要）：
- [ ] 已从 user 消息提取：源码缓存根目录、gnx-tools.js 脚本路径、GitNexus 服务地址
- [ ] 已用 list_directory 检查 <源码缓存根目录>/files/ 是否存在
- [ ] 缓存命中：已用 read_file 读取相关源文件
- [ ] 缓存未命中：已用 run_shell 执行 gnx-tools.js materialize 拉取（或记录不可达原因）
- [ ] 每个修改点都有「源码依据文件 → 具体证据」记录（或标注「[待源码确认]」及原因）

修改与校验：
- [ ] 已按修改点列表逐一修改，范围未扩散
- [ ] 未被要求修改的章节内容已保留
- [ ] 新增内容有源码路径级别的论据
- [ ] .excalidraw（若修改）节点名称来自真实源码符号

写回：
- [ ] 已用 write_file 写回 PROPOSED_PATH（完整文档，非片段）
- [ ] 文件名与 targets[0] 完全一致
- [ ] 回复中已列出修改摘要（章节 + 源码依据）
```

---

## 常见场景示例

### 场景 A：补充功能说明（需要读源码）

1. Phase 0：识别修改点「补充 §3.2 批量导入功能的代码影响范围」
2. Phase 1：读 proposed/ 下的 FUNCTIONAL_ARCH.md，记录 §3.2 现有内容
3. Phase 2a：检查 `GNX_CACHE_DIR/files/` 缓存是否存在
   - 存在 → 在缓存中定位与批量导入相关的文件（Grep 类名/函数名）
   - 不存在 → 在 CODE_PATH 指定目录中查找
4. Phase 2b-c：读取相关源文件，记录涉及文件列表
5. Phase 3：在 §3.2 补充「代码影响范围：`path/to/ImportService.java` 等」
6. Phase 4-5：校验完整性后写回

### 场景 B：纠正错误的架构描述（不需要读源码）

1. Phase 0：识别修改点「将 §4.2 中的「消息队列」改为「事件总线」」
2. Phase 1：读文档，确认 §4.2 当前内容
3. Phase 2：用户仅要求措辞修改且提供明确名称，无需源码验证（记录理由）
4. Phase 3：替换 §4.2 中对应措辞
5. Phase 4-5：校验后写回

### 场景 C：修改 .excalidraw 架构图（需要读源码）

1. Phase 0：识别修改点「在系统分层图中新增「数据同步层」」
2. Phase 1：读 proposed/ 下的 .excalidraw，记录现有层级结构（矩形节点列表）
3. Phase 2：在源码缓存中查找数据同步相关模块，确认真实目录/类名
4. Phase 3：在 JSON 中新增对应矩形节点和连接线，节点 text 使用源码目录名
5. Phase 4-5：确认 JSON 合法后用 write_file 写回

---

## Error Handling

| 情形 | 处理方式 |
|------|---------|
| read_file 读 proposed/ 失败 | 立即停止，返回错误（不得继续修改） |
| 缓存不存在且 gnx-tools.js 路径为空 | 不执行拉取；将涉及源码的修改点全部标注「[待源码确认：脚本路径未注入]」后继续 |
| gnx-tools.js materialize 执行失败（ECONNREFUSED / 超时） | 记录「GitNexus 不可达」；涉及源码的修改点标注「[待源码确认：GitNexus不可达]」后继续 |
| 找到缓存但找不到对应源文件 | 用 list_directory 扩大搜索范围；仍找不到则标注「[待源码确认：文件不在缓存中]」 |
| materialize 后 `read: not in cache` | 检查是否误加了 `--max-files`；去掉后重新执行 materialize |
| 修改后文档章节缺失（Phase 4 校验不通过） | 重新生成完整文档，不得只输出修改片段 |
| .excalidraw JSON 格式错误 | 不得写回；检查 JSON 语法后重新生成 |
| 用户要求与三项核心原则冲突 | 优先遵守三项核心原则，在回复中说明冲突并请求用户澄清 |
