# 产品知识文档 AI 编辑（Refine）改造方案 v2

**状态**：已定稿 
**日期**：2026-04-27  
**范围**：`apps/setup-center` 产品详情文档页 + Synapse `dev_iwhalecloud_knowledge` 的 `product_knowledge/refine` 及相关前端 API。**不考虑 Web-only**：以 Tauri 与 `local_draft` 链路为准。

---

## 1. 背景与目标

当前实现中，前端将**整篇 Markdown** 通过 `POST /api/dev/iwhalecloud/product_knowledge/refine` 传给 Synapse，后端用**完整默认 Agent** 执行改写，成功后整段覆盖编辑器。存在：请求体过大、与「生成任务」执行策略不一致、无可视化 diff、与权威落盘路径关系不清晰等问题。

本方案按产品侧补充意见，将 refine 调整为：

- **不在请求中传递文档正文**（由后端从 **`local_draft/write` 所落盘的** `_knowledge_docs_root` 按稳定文件名读取；磁盘空则**先** `local_draft/write`，见 §3.1）。
- **后端执行策略与生成任务对齐**：锁 system、路径白名单工具、**`preferred_endpoint` + `rd_skill_ids`** 与初次生成同源（见 §3.2）；预置 system 可版本化、可审计。
- **非流式**：一次请求阻塞到任务完成；完成后产物落在会话临时目录，前端再拉取全文做 **inline diff** 对照检查。
- **围栏与解析**维持现有严格约定（仅 `` ```markdown ``），不扩展兼容分支。
- **用户消息结构**：服务端拼装「产品信息（自动）+ 用户要求」；请求体只携带标识与用户原始要求。
- **修改对象**：一次 refine **仅当前 Tab 对应的一个**稳定文件（`targets` 单元素）；**未保存到本地草稿时禁止使用大模型**（见 §3.7 / §3.8）。**稳定文件名不变**（见 §3.6）。
- **禁止直接覆盖权威源文件**：模型/工具只写**会话临时目录**下的副本；用户确认后再走现有提交写回流程。
- **AI 串行门禁**：一次 refine 结束后须**审完、合入或放弃完毕**且**临时会话清理完毕**，才允许再次使用 AI；见 §3.8。
- **与生成任务分流**：refine **不使用** `task_id`，也不走 `product_knowledge/generate` / 状态轮询；会话仅用服务端 **`session_id`**（+ §3.8）。**无需**在编辑前向统一服务做「将要改文档」类通知；用户接受后再走既有 **`docs_submit` 等提交**即可。
- **异常处理与国际化**按工程惯例补齐。

---

## 2. 现状摘要（便于对照）

| 环节 | 现状 |
|------|------|
| 前端 | `ProductDocumentEditor`：AI 区为 **Sparkles** + 输入框 → `refineProductKnowledge` 传 `{ content, prompt }`；**无**模型/技能配置入口 |
| 后端 | `product_knowledge_refine`：`ProductKnowledgeRefineRequest` 仅 `content` + `prompt`；默认 Agent、`execute_task_from_message`、超时 **600s**；**未** `_org_context` / **未**工具白名单 / **无** `preferred_endpoint`；响应 `data.content` + `` ```markdown `` 解析 |
| 本地草稿（与 `_knowledge_docs_root` 同源） | 已实现 `POST .../local_draft/{exists,read,write,clear}`；`write` → `write_local_draft_doc_rows_atomic` 写入 `{synapse_home}/tmp/docs/<prod>/<doc_type>/`；`clear` **仅删除该目录下一层普通文件**，不递归删子目录 |
| 文档来源 | `ProductDetail`：Tauri 下「保存」走 `persistCategoryDocsToLocal` → **`productKnowledgeLocalDraftWrite`**；统一服务流程已 **D** 且无本地草稿时，hydration 用 **`getProdDoc`** 只进内存 **不自动** 写 `local_draft`，故磁盘可仍为空（§3.1） |
| 代码内 TODO | 路由旁「同步流式」等与 v2 **非流式**不一致；**refine 不使用 `task_id`**，删除过时 TODO 即可 |

**与方案差异（实现审核结论）**

| 方案条目 | 当前代码 | 备注 |
|----------|----------|------|
| 不传 `content` | 仍必填 | 改造后改请求体 |
| 锁 system / 路径工具 / `preferred_endpoint` / `rd_skill_ids` | 无 | 与 `_run_knowledge_generation_task`（含技能过滤与二次 `get_or_create`）对齐时需补 |
| `refine_sessions` 临时目录 | 无 | 新增 |
| 「先落盘再 refine」 | 无自动 | 应对齐 **`local_draft/write`**（与保存按钮同源），而非泛称「保存」 |
| 会话与幂等 | 无 `session_id` | v2 用 **`session_id` + §3.8** / `refine_session_pending`，**不**引入 `task_id` |

---

## 2.1 前端 AI 区与模型/工具配置（新增）

- **图标**：AI 输入区左侧（或入口）由 **Sparkles（智能化）** 改为 **工具类图标**（如 `Wrench` / `Settings2` 等，与产品视觉规范统一即可）。
- **交互**：点击工具图标打开**配置面板**，能力与「**初始化 / 生成文档**」类似：**选择 LLM 端点**（映射请求体 `preferred_endpoint`）、**多选研发工具技能**（映射 `rd_skill_ids`，与生成弹窗同源 catalog / 启用列表）。
- **与请求对齐**：用户在该面板中的选择写入每次 refine 的 HTTP 请求体，后端按 §3.2 与 `_run_knowledge_generation_task` 相同流程挂载到 `AgentProfile`（`ephemeral`、`preferred_endpoint`、`skills` + `SkillsMode.INCLUSIVE` 等）。

---

## 3. 需求要点（与方案映射）

### 3.1 不传递文档正文 + 文档加载路径（已定案）

**原则**：HTTP 请求只传**定位信息**与**用户意图**，正文由 Synapse 从**本地临时知识文档根目录**读取。

**与研发统一服务的关系**：refine **执行中**不在 Synapse 内每次调用 `get_doc`；正文以本机 `_knowledge_docs_root` 已落盘文件为准。磁盘空则先 **`local_draft/write`**（见「首次落盘」）。**不要求**改文档前向统一服务做任务/进程类**事前通知**；与 **`product_knowledge/generate` 的 `task_id`** 无关。

**与生成任务的关系（仅对齐执行策略，不复用任务模型）**：生成走异步 `task_id` + 状态轮询；refine **不分配 `task_id`**、不轮询 `product_knowledge/status`，仅用 **`session_id`** 与临时目录；防并发靠 §3.8 / `refine_session_pending`。

**知识文档根目录**（与生成任务 `_run_knowledge_generation_task` 中一致）：

```text
{knowledge_docs_root} = {synapse_home}/tmp/docs/{prod_name}/{doc_type}/
```

对应代码：`_knowledge_docs_root(doc_type, prod_name)`（`dev_iwhalecloud_knowledge.py` 内 `output_dir = _knowledge_docs_root(...); output_dir.mkdir(...)` 与生成任务相同语义）。

**读取规则（单文档 + 仅 targets）**：

- **一次只改一个文件**：`targets` **长度必须为 1**（例如 `["FUNCTIONAL_ARCH.md"]`）；后端**只**从 `{knowledge_docs_root}/<targets[0]>` 读取「修改前」基准，**不**读取同目录下其它文件。`len(targets) != 1` 时返回 `400` / 业务码如 `invalid_targets`。
- **前端如何确定 `targets[0]`**：由 **当前选中的文档 Tab**（`ProductDetail` 活动页签对应的 `doc_name` / 标题映射的稳定文件名）唯一确定，随 refine 请求提交；不提供「一次 refine 多 Tab」能力。
- **无兜底**：文件不存在 → `target_not_found`；**不**用请求体里的全文 `content` 作第二数据源。

**首次落盘（仅统一服务/内存有内容、`_knowledge_docs_root` 下尚无文件时）**：

典型情况：统一服务 **D** 后 `getProdDoc` hydration 只进 `openDocs`，**未**调用 `local_draft/write`，则根目录下无对应 `doc_name` 文件，refine 直读磁盘会 `target_not_found`。

- **具体接口（与代码一致）**：在 refine 前调用 **`POST /api/dev/iwhalecloud/product_knowledge/local_draft/write`**（前端已有 `productKnowledgeLocalDraftWrite`，与详情页「保存」、`ProductDocumentEditor` 的 `onSave` → `persistCategoryDocsToLocal` **同源**）。成功后 `_knowledge_docs_root` 下即有与 `get_doc` 同结构的 `doc_content` 文件。
- refine **仍不**在 Synapse 内调统一服务 `get_doc`；仅依赖上述已落盘副本。

**子目录与 `clear` 的兼容性**：当前 `clear_local_draft_doc_dir` 只 `unlink` 根目录下的**文件**；`refine_sessions/<session_id>/` 作为**子目录**不会被该 clear 删掉。实现 refine 临时目录时仍须在会话结束时**显式删除** `refine_sessions`（§3.8），勿依赖 `local_draft/clear` 顺带清理会话树。

**请求体（建议字段，命名可在实现时 snake_case 与现有 API 风格对齐）**：

| 字段 | 说明 |
|------|------|
| `prod` / `prod_name` | 产品标识（与生成任务、目录名一致） |
| `doc_type` | 文档类型（与生成任务 wire 一致） |
| `targets` | **长度固定为 1** 的稳定文件名数组，与**当前选中 Tab** 对应；例 `[ "FUNCTIONAL_ARCH.md" ]` |
| `user_prompt` | **仅用户手写要求**（不含产品信息块） |
| `preferred_endpoint` | 可选；与 `product_knowledge/generate` 一致，映射 `AgentProfile.preferred_endpoint` |
| `rd_skill_ids` | 可选；与生成任务一致，经 `_get_enabled_rd_skill_ids` / `_normalize_rd_skill_ids` 过滤后 **INCLUSIVE** 挂载（见 §3.2） |
| 产品摘要字段 | 见 §3.5；用于注入 user 消息，**不**承载文档正文 |

**服务端拼装「完整用户消息」**（不放在请求体里由前端拼，避免篡改与重复）：

- 将 **产品信息** 自动注入到发给模型的 user 消息**上部**（字段与模板见 §3.5），与 `user_prompt` 明确分段。
- 固定模板示意：

```text
## 产品上下文（系统自动注入，请勿删除）
<产品描述、代码路径、主要功能等>

## 用户修改要求
<user_prompt 原文>

## 待修改文件（仅允许修改下列路径对应的临时工作副本）
- {session_root}/proposed/<稳定文件名> ...
```

（具体清单在实现时列出逻辑路径，工具 `write_file` 仅允许落在会话目录下，见 §4、§3.7。）

### 3.2 后端仍走 refine，但与生成任务对齐

**路由**：可保留 `POST .../product_knowledge/refine`（或新增 v2 后废弃旧路径；若 breaking 则版本化 `/refine/v2`）。**不**扩展为生成式 `task_id` 协议，也**不**增加「改前通知统一服务」步骤。

**`preferred_endpoint` 与 `rd_skill_ids`（对齐生成任务 `dev_iwhalecloud_knowledge.py` 约 383–403 行）**：

- 与 `_run_knowledge_generation_task` 相同：**先** `replace(base_profile, id=prof_id, ephemeral=True, preferred_endpoint=ep)` 并 `get_or_create`（便于读 `skill_loader`）→ **`_get_enabled_rd_skill_ids` / `_normalize_rd_skill_ids(req.rd_skill_ids, ...)`** → **再** `replace(..., skills=rd_skills, skills_mode=SkillsMode.INCLUSIVE, ephemeral=True, preferred_endpoint=ep)` → **`pool.invalidate_profile(prof_id)`** → **再** `get_or_create` 得到最终 agent。
- **refine 专用** `prof_id` / `session_id` 前缀（勿与 `pkg_gen_*` 混用），避免与生成任务实例池冲突。

**与生成任务对齐的其余要点**（**不含** `task_id` 与 `_persist_task`）：

1. **锁 system**：`agent._org_context = True`；`_context.system = <REFINE_MINIMAL_BASE>` +（若 `rd_skill_ids` 非空）与生成任务同构的 **`skill_section`**（从 `skill_loader` 读 body 注入），再拼接 refine 角色与路径约束短说明（实现时可拆文件便于 diff）。
2. **工具列表**：**路径白名单**（§4：`read_file` / `write_file` / 可选 `list_directory`，前缀限制）与 **当前 Agent 已挂载工具** 取**交集**（或显式 frozenset 列表），使技能带来的工具仅保留 refine 允许子集；**默认仍禁止** `run_shell` 除非评审后放开。
3. **`default_cwd`**：建议设为 `_knowledge_docs_root`（或含 `refine_sessions` 的会话根），与生成任务 cwd 语义一致，便于模型理解相对路径。
4. **`execute_task_from_message`**：user 消息为 §3.1 / §3.5 拼装结果；**以 `proposed/` 落盘为准**；HTTP 返回 `session_id` + manifest；`` ```markdown `` 围栏仅作可选校验。

**预置 system 提示词（必须明确写出，实现时落文件）**应至少声明：

- 角色：产品知识文档编辑助手。
- 输入：产品上下文、用户要求、允许修改的文件清单（会话内逻辑路径）。
- 输出约束：对 Markdown 输出完整可替换正文；对 `.excalidraw` 输出合法 JSON；**推荐仅用工具写文件**，避免在 chat 中贴大段 JSON。
- 围栏：若自然语言回复中带文档片段，**必须**且仅能使用 `` ```markdown ... ``` `` 包裹（与现解析一致）。
- **禁止**：擅自**改名**（`targets[0]` 必须与磁盘已有文件名一致）、删除未要求删除的章节、调用非交集内工具、**直接写入 `{knowledge_docs_root}` 根下除会话子目录外的路径**（权威源只读，见 §3.7）。

### 3.3 非流式：阻塞完成 → 临时落盘 → 前端 diff

**原则**：**不需要流式**。前端阻塞至 JSON 返回；后端写好 `original`/`proposed` 后返回 `session_id`（+ manifest）；前端拉两侧全文做 **inline diff**（编辑器已依赖 `@monaco-editor/react`，DiffEditor 可复用同栈）。

**API**：单一 JSON（无 SSE）；含 `session_id`、`targets`、拉取原文的 URL 或内联字段；错误 `errorcode` + `message`。超时：可与现 refine **600s** 对齐或单独配置，前端 i18n 提示。

### 3.4 围栏与解析

维持：**仅**识别 `` ```markdown\s*(.*?)\s*``` ``（`re.DOTALL`），不做 `` ```md `` 等扩展。文档规范在 system 中写死。非流式场景下，**优先以 `proposed/` 落盘文件为准**；围栏解析可作为二次校验或兼容旧模型习惯。

### 3.5 上下文元数据与用户提示词

- **请求体**：`user_prompt` = 用户要求（短句/列表均可）。
- **服务端**：将 **产品信息** 自动注入到发给模型的 user 消息**上部**，与 `user_prompt` 明确分段。

**产品信息（与生成任务 user 提示块对齐，最小集）**  

与 `_run_knowledge_generation_task` 中注入格式一致，refine 侧至少包含：

- **产品描述**：`product_desc`
- **代码路径**：`code_path`（若有）
- **主要功能**：`core_features`

示例（实现时可略作格式化，但语义一致）：

```text
产品描述：[{product_desc}]
代码路径：[{code_path}]
主要功能：[{core_features}]
```

另可附带：`prod_name`、`doc_type`、知识分类中文名（便于模型理解）。**禁止**把敏感 token 写入 prompt。若部分字段仅前端有：在 refine 请求体中增加**非敏感**摘要字段，后端原样注入——与「不传文档正文」不冲突。

### 3.6 文档与图片（资源）统一命名

- `targets` 中每一项为**稳定文件名**（与 `{knowledge_docs_root}` 下已有文件名、`![...](foo.excalidraw)` 引用名一致）。
- **文档命名不得变更**：会话内副本、工具写入、diff 展示均使用**同一稳定文件名**（仅目录层级不同：根目录权威只读 vs `refine_sessions/<session>/proposed/` 等）。
- 用户「接受变更」后，再走既有 **`docs_submit` 等提交**写回业务侧（本方案不重新定义提交契约；refine **不要求**在此之前向统一服务做额外「改稿预告」）。

### 3.7 临时文件目录（会话子路径，在知识文档根下）

**禁止**在 refine 过程中直接覆盖 `{knowledge_docs_root}/<稳定文件名>`。所有模型产出与对比用副本放在**知识文档根目录下新建的会话子目录**中，例如：

```text
{knowledge_docs_root}/refine_sessions/{session_id}/
  original/   # 可选：发起 refine 时从根目录拷贝的快照，便于与磁盘漂移对齐
  proposed/   # 模型仅允许 write_file 到此目录下；文件名与 targets 一致
  manifest.json  # 可选：checksum、字节数、完成时间
```

- `session_id`：服务端生成（UUID），在 JSON 响应中返回。
- **工具路径校验**：`read_file` 可读 `{knowledge_docs_root}` 下权威文件（只读）及本会话目录；`write_file` **仅允许** `{knowledge_docs_root}/refine_sessions/{session_id}/proposed/` 前缀（及实现时明确列出的子路径）。
- **清理**：接受/拒绝/会话过期（如 24h）后删除 `refine_sessions/{session_id}`；可配合定时任务。**与 §3.8 配合**：用户完成「全部审核合入」或「全部放弃」的收尾时，**必须**删除本会话临时目录，不得长期残留；详见 §3.8。

**前端**：

0. **未保存则禁 AI**：当前分类/文档存在**未保存到本地草稿**的编辑（编辑器状态与已 `local_draft/write` 的磁盘不一致，或 `ProductDocumentEditor` 的 dirty 语义为真）时，**禁止**使用大模型：禁用 refine 输入区与发送、工具配置入口可灰显或仍可打开但发送前校验失败；文案走 i18n（见 §3.9）。**已定案**，不再作为开放问题讨论。
1. **模型/工具**：见 **§2.1**（工具图标 + 配置面板 → `preferred_endpoint`、`rd_skill_ids`）。
2. 发起 refine → 阻塞等待 → 拿到 `session_id` + `targets`（恒为单元素）。
3. 拉取 `original` 与 `proposed` 全文，**inline diff** 优先用 Monaco DiffEditor（与 `ProductDocumentEditor` 编辑栈一致）。
4. **接受 / 拒绝**：
   - **拒绝**：丢弃会话，不调写回。
   - **接受**：将 `proposed` 内容写回当前编辑器状态 / `openDocs`，并可触发保存；**是否写回磁盘权威路径**与产品现有「保存/提交」流程对齐。
   - **类 Cursor 的部分接受**：目标体验为**仅应用选中 hunk 或选中范围**（而非只能「整文件接受」）。实现上可先落地「整文件接受/拒绝」，再迭代 **hunk 级或选区合并**（Monaco / diff 库能力需验证）；**具体效果以首版实现联调为准**，在 P1/P2 分阶段验收。

### 3.8 AI 使用门禁（串行审核）与临时文件强制清理

**业务规则**：

0. **未保存禁大模型**：与 §3.7 前端第 0 条一致；可与「挂起 refine 会话」并列校验（先 dirty 禁发，再审完解锁）。
1. **一次一关**：每次 AI refine 跑完后，进入「待审核」状态。用户必须对**本次会话**完成审核与处置（单 `targets[0]` 下为**该文件**接受或放弃），**不存在**仍待处理的 refine 临时会话后，**才允许**再次触发任意同类 AI 能力。  
   - **前端**：存在挂起 `session_id` 时禁用「AI 编辑」等入口，并展示简短说明（i18n）。  
   - **后端（建议）**：对同一 `(prod_name, doc_type)`（或更细粒度）若已有未完成会话，拒绝新 refine 请求，返回业务码如 `refine_session_pending`，避免多会话堆积。

2. **收尾必清盘**：当用户完成**接受或拒绝**并关闭 diff 门禁后，**必须**删除对应的 `refine_sessions/{session_id}` 目录（或调用后端「关闭会话」接口由服务端删除），确保无残留临时文件。仅「过期定时清理」不能替代本条。

3. **「审核完毕」语义**（单文件）：对唯一的 `targets[0]` 已**接受**或已**拒绝**，无半接受悬案。

### 3.9 异常处理与国际化

**后端**：

- 统一 `errorcode` + `message`；细分：`invalid_targets`（`targets` 非单元素）、`target_not_found`、`read_authoritative_failed`、`agent_timeout`、`empty_proposed`、`parse_fence_failed`、`path_violation`（工具写出允许前缀外）、`refine_session_pending`（§3.8）等。
- 非流式：错误在唯一 JSON 响应中返回；HTTP 状态码与业务 `errorcode` 约定一致。

**前端**（`zh.json` / `en.json`）：

- 新增键：`workbench.products.detail.refine*` 下区分 loading、diff、accept、reject、partial_apply（若启用）、**未保存禁止 AI**（§3.7）、**挂起会话禁止再次 AI**（§3.8）、模型/工具配置面板标题与各类错误说明。
- Toast 与 diff 面板内文案全部走 `t()`。

---

## 4. Refine 专用工具白名单

与 §3.2 一致：**路径维度的**允许前缀——**`read_file`**：`{knowledge_docs_root}` 根下权威文件 + 本会话目录；**`write_file`**：仅 `.../refine_sessions/{session_id}/proposed/`；**`list_directory`** 可选。与技能工具的**交集**见 §3.2；**`run_shell`** 默认禁止（是否例外见 §7）。

---

## 5. 与生成任务的对照表

| 项 | 生成任务（现状） | Refine（目标） |
|----|------------------|----------------|
| 任务模型 | `task_id` + `status` 轮询 + `_persist_task` | **`session_id`** + 单次 HTTP；**无** `task_id` |
| 统一服务 | 按现有生成/处理链路 | **改前无**额外通知；接受后仍用既有 **`docs_submit`** |
| Profile | ephemeral + `preferred_endpoint` + `rd_skill_ids` → INCLUSIVE skills | **同源**；refine **ephemeral**，`prof_id`/`session` 前缀独立 |
| System | 极简 + `skill_section` 注入 | **同构** skill 块 + **refine 固定约束**（锁 `_org_context`） |
| Tools | 白名单（含技能带来工具） | **路径白名单** ∩ Agent 工具（§3.2）；默认禁 `run_shell`（见 §7 开放问题 2） |
| 文档根路径 | `_knowledge_docs_root` → `agent.default_cwd` | **读取**同一根目录；**写入**仅 `refine_sessions/<session>/proposed/` |
| 输入 | 大段任务描述 + 产品描述/代码路径/主要功能 | **同风格产品块** + `user_prompt` + **单文件** `targets` |
| 输出 | 工具写 `{knowledge_docs_root}` 下交付物 | **只写 proposed 临时副本**；文件名 = `targets[0]` |
| 流式 | 无（异步 task） | **无**；单次请求阻塞至完成 |
| 前端 | 轮询任务状态 | **工具图标** + 模型/技能配置（§2.1）→ **阻塞** → diff → 接受/拒绝；**未保存禁 AI** |

---

## 6. 实现阶段（建议排期）

| 阶段 | 内容 | 验收 |
|------|------|------|
| P0 | 新请求体；**`targets` 单元素** + 仅读该文件；**`preferred_endpoint` + `rd_skill_ids`** 按生成任务流程挂载；**refine 前按需 `local_draft/write`**；锁 system + 路径工具 ∩ 技能工具；`refine_sessions/{session_id}`；非流式 JSON；**无** `task_id` | 单 Tab 一次 refine；不覆盖根目录权威文件 |
| P1 | **§2.1** 工具图标与配置面板；**未保存禁 AI**；阻塞 + inline diff + 接受/拒绝；**§3.8** + 临时目录清理；i18n | 脏状态无法发 refine；审完可再开 |
| P2 | 类 Cursor **部分接受**（hunk/选区）；联调效果评估；路径审计 | 可按块应用且不破坏稳定文件名 |
| P3 | 指标日志、权限复核 | 运维可接受 |

---

## 7. 开放问题（实现前需确认）

1. **`.excalidraw` 等大 JSON**：是否强制「仅工具写 `proposed/`、assistant 文本尽量短」以避免模型在 chat 中贴超长 JSON？
2. **路径工具与技能工具的交集**：`run_shell` 是否在选中某些研发技能时**例外放行**（与生成任务一致），还是 refine 永远禁止 `run_shell`？

**已定案（不再列入开放问题）**：`targets` 仅单文件、当前 Tab 绑定；**未保存禁大模型**（§3.7 / §3.8）；**不考虑 Web-only**（§1 范围）。

---

## 8. 涉及文件（实现时参考）

| 区域 | 路径 |
|------|------|
| 后端 | `src/synapse/api/routes/dev_iwhalecloud_knowledge.py`：`product_knowledge_refine`、`_run_knowledge_generation_task`、`local_draft/*`、`_knowledge_docs_root` / `write_local_draft_doc_rows_atomic` / `clear_local_draft_doc_dir`（改 refine 时评估是否需排除 `refine_sessions` 或扩展 clear 语义） |
| 前端 API | `apps/setup-center/src/api/rdUnifiedService.ts`：`refineProductKnowledge`；已有 `productKnowledgeLocalDraft{Exists,Read,Write,Clear}` |
| 编辑器与详情 | `ProductDocumentEditor.tsx`、`ProductDetail.tsx`（生成选项弹窗 **`genOptsOpen` / `rdSkillCatalog` / `preferred_endpoint`** 等可复用或抽组件；`persistCategoryDocsToLocal`、dirty → 禁 refine） |
| 文案 | `apps/setup-center/src/i18n/zh.json`、`en.json` |

---

## 9. 小结

本方案将 **refine** 改为「**单 Tab / 单 `targets`** + **同一 `_knowledge_docs_root`** + **`refine_sessions`** + **非流式 diff** + **§3.8 门禁** + **未保存禁 AI**」；**`preferred_endpoint` + `rd_skill_ids`** 与初次生成同源挂载；前端 **工具图标** 打开模型/技能配置（§2.1）；**无 `task_id`**；**不考虑 Web-only**；接受后 **`docs_submit`**；部分接受 P2。

评审通过后，可按 §6 分阶段提交 PR，并在 `apps/setup-center/DIFF.md`（若触及该包）补充变更摘要。
