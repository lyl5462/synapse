"""会议室运行时 system 上下文装配。

设计目标（对齐《多智能体研发会议室实现方案》§9）：

- 会议室通用规范是一段内嵌字符串（`_MEETING_ROOM_RULES`），与 SKILL 加载机制无关，
  仅作为本会议室的 system 上下文片段。小鲸（host）与所有协作智能体（worker）进入会议室后，
  都会拿到这份规范，并按角色裁剪可见段落。
- 同时渲染「参会能力卡片」（host 视角）/「你的能力档案」（worker 视角），让小鲸按能力
  边界派单、让 worker 清楚自己的身份与边界。
- `ask-user` 仍以独立 SKILL.md 形式存在（人机问卷格式与示例较多，单独维护）。

本模块只负责**装配 prompt 片段**，不直接调用 LLM；由 `orchestrator.run_current_node`
在执行节点时把渲染结果拼接到节点提示词中。
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from synapse.agents.profile import AgentProfile, get_profile_store
from synapse.rd_sop.nodes import node_display_name, stage_name_for_id

logger = logging.getLogger(__name__)

Role = Literal["host", "worker"]

DEFAULT_ASK_USER_SKILL_ID = "whalecloud-dev-tool-ask-user"
DEFAULT_LLM_ENDPOINT_KEY = "default"

# 默认会议室规则文件名（与本模块同级 prompts/ 目录）
_DEFAULT_RULES_FILENAME = "meeting_room_rules.md"


# ─── SKILL.md 定位（仅供 ask-user 等真正的外部 SKILL 使用） ────────────


def _candidate_skill_dirs() -> list[Path]:
    """按优先级返回外部 SKILL 可能的根目录。

    顺序：
    1. settings.skills_path（生产模式：~/.synapse/workspaces/<ws>/skills）
    2. settings.project_root / skills（开发模式或开源仓库内）
    3. 仓库内 fallback：`<repo_root>/skills`，从本文件路径反推
    """
    candidates: list[Path] = []
    try:
        from synapse.config import settings

        candidates.append(Path(settings.skills_path))
        candidates.append(Path(settings.project_root) / "skills")
    except Exception as exc:
        logger.debug("settings unavailable in room_skill: %s", exc)

    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "skills")
    except Exception:
        pass

    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def _find_external_skill_file(skill_id: str) -> Path | None:
    """在标准技能目录中查找外部 SKILL.md 文件（ask-user 等）。"""
    sid = (skill_id or "").strip()
    if not sid:
        return None
    for root in _candidate_skill_dirs():
        if not root.is_dir():
            continue
        path = root / sid / "SKILL.md"
        if path.is_file():
            return path
    return None


def load_ask_user_skill_body(skill_id: str = DEFAULT_ASK_USER_SKILL_ID) -> str:
    """读取人机问卷技能正文（host 专用片段，仍为外部 SKILL）。"""
    path = _find_external_skill_file(skill_id)
    if path is None:
        return ""
    try:
        return _strip_frontmatter(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("read ask-user skill %s failed: %s", path, exc)
        return ""


def get_meeting_room_rules() -> str:
    """返回会议室通用规范正文。

    优先级：
    1. ``settings.rd_meeting_rules_path``（私有化 / 多租户场景可指向自定义规则文件）
    2. 本模块同级 ``prompts/meeting_room_rules.md``（随仓库发布的默认版本）
    3. 兜底常量 ``_MEETING_ROOM_RULES_FALLBACK``（极端情况下仍保证 host prompt 不空）

    读取结果带 LRU 缓存。如需在运行时强制重载，调用
    :func:`reload_meeting_room_rules`。
    """
    text, _ = _load_meeting_room_rules()
    return text


def get_meeting_room_rules_meta() -> dict[str, str]:
    """返回当前生效规则的元数据：``source`` / ``sha256[:12]`` / ``length``。

    供调试 / 审计使用——例如把 hash 一并写进 ``hitl_submission.schema_snapshot``，
    便于复盘"那次会议跑成那样时用的是哪一版规则"。
    """
    text, source = _load_meeting_room_rules()
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return {"source": source, "sha256": digest, "length": str(len(text))}


def reload_meeting_room_rules() -> dict[str, str]:
    """清除规则缓存，下次取用时重新读盘。返回新的元数据。"""
    _load_meeting_room_rules.cache_clear()  # type: ignore[attr-defined]
    return get_meeting_room_rules_meta()


def _resolve_rules_path() -> Path | None:
    """按优先级解析规则文件路径。"""
    try:
        from synapse.config import settings

        override = getattr(settings, "rd_meeting_rules_path", "") or ""
        if isinstance(override, str) and override.strip():
            p = Path(override).expanduser()
            if p.is_file():
                return p
            logger.warning(
                "settings.rd_meeting_rules_path=%r not found, falling back to bundled rules",
                override,
            )
    except Exception as exc:
        logger.debug("settings.rd_meeting_rules_path lookup skipped: %s", exc)

    bundled = Path(__file__).resolve().parent / "prompts" / _DEFAULT_RULES_FILENAME
    if bundled.is_file():
        return bundled
    return None


def _load_meeting_room_rules_uncached() -> tuple[str, str]:
    """实际读盘逻辑，返回 (text, source_label)。"""
    path = _resolve_rules_path()
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
            return text, str(path)
        except OSError as exc:
            logger.warning("read meeting room rules %s failed: %s", path, exc)
    return _MEETING_ROOM_RULES_FALLBACK, "<fallback:embedded>"


try:
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _load_meeting_room_rules() -> tuple[str, str]:  # type: ignore[no-redef]
        return _load_meeting_room_rules_uncached()
except Exception:  # pragma: no cover - lru_cache 总是可用，仅作防御
    def _load_meeting_room_rules() -> tuple[str, str]:  # type: ignore[no-redef]
        return _load_meeting_room_rules_uncached()


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    try:
        head, body = text.split("\n---", 1)
        if head.startswith("---"):
            body = body.lstrip("\n")
            return body
    except ValueError:
        return text
    return text


# ─── 内置主持人流程规则（兜底正文） ────────────────────────────────────
#
# 仅 Host（小鲸）会在 system prompt 中加载这段「会议室流程与规则」。
# Worker 的边界与协作要点已经在 `build_meeting_runtime_header` 的「协作专家职责」
# 与「你的能力档案」中说清楚，不再追加任何长文规范。
#
# 与运行时头、与「系统信息」（工单/产品/系统）之间**不允许重复**：
# 身份/工单/产品/会议目标/人工确认开关/能力卡片都已展示，本文只讲流程与判定规则。
#
# 真正生效的规则文本由 :func:`get_meeting_room_rules` 从外部 Markdown 加载
# （``prompts/meeting_room_rules.md`` 或 ``settings.rd_meeting_rules_path``）。
# 下面这份内嵌字符串只在外部文件读取失败时作兜底，**修改时请同步外部 .md**，
# 避免两份漂移。
_MEETING_ROOM_RULES_FALLBACK = """## 会议室流程与规则（主持人专属）

### 1. 节点成功标准

- 交付物归档到 system 信息「四、系统信息 · 本节点归档目录」指定路径，且通过你自己的契合度 / 真实性 / 准确性检查。
- 关闭节点（`enabled: false`）由编排器跳过并自动推进；你只需对当前节点负责。

### 2. 人工确认（`human_confirm`）语义

「人工确认」开关取值见运行时头的「人工确认」字段。SOP 节点类型 `human` / `human_start` 等，表示**人工参与度高**，**不等于**「仅人工处理、不跑智能体」。

| 场景 | `human_confirm: true` | `human_confirm: false` | 例外 |
|------|----------------------|------------------------|------|
| **会议期间** | **每次收到 Worker 响应、每次需要做下一步决策前**，都必须先生成 HITL 问卷（`submit_hitl_questionnaire(kind="interactive")`）交人工裁决，**不得**自行替用户做选择 | 自主决策，不必为常规中间产物逐条请示 | — |
| **会议结果** | 输出「待确认总结」→ 用户表单确认 → **才**写入归档并推进下一节点 | 自主收敛后直接归档并自动推进下一节点 | — |
| **异常** | 同左 | 同左 | **无论开关**：超时、质量/真实度不达标、风险不可控等，**必须**主动请求人工介入 |

**`human_confirm: true` 时的硬约束**：

- **每条决策点 = 一次 HITL**：你**不能**根据 Worker 返回结果直接「拍板」「自动通过」「自动重派」「自动收敛」。在每一个决策分叉（要不要重派、改派给谁、要不要追加 Worker、是否进入收敛、是否归档等），都必须先调 `submit_hitl_questionnaire(kind="interactive")` 拿到用户答复后再继续。
- **调用即停**：提交后立刻停止本轮所有正文 / 工具调用；待用户答复回到下一轮再继续推进。
- 仅当**当前节点**开启结果确认且用户尚未确认时，节点流转才被阻塞；推进下一节点不挂额外门控。

### 3. 工作循环：拆分 → 派单 → 校验 → 收敛

1. **拆分**：复读运行时头的「会议目标」与「工单」中的硬约束，按「参会能力卡片」的技能列表把目标拆分成可由具体 Worker 完成的子任务。
2. **派单**：**必须先**调用 `submit_meeting_work_plan` 提交结构化计划（每项含 `agent_id` / `task` / `reason`），再 `delegate_to_agent` 或 `delegate_parallel`；可并行的只读 / 调研任务优先 `delegate_parallel`（建议带 `plan_item_id` 关联计划条目）。
3. **校验**：Worker 返回结果后，按三项逐条核对：
   - **契合度**：是否针对你下发的子任务，是否回答了关键问题。
   - **真实性**：引用的代码 / 文档 / 工单是否真实存在，能否复核。
   - **准确性**：结论是否经得起源码 / 数据验证，是否存在臆造。
   不通过则**明确**指出缺项；**`human_confirm: true` 时**按 §2 硬约束先发 HITL 与用户共同决定「重派 / 换人 / 收敛」，**严禁**私下直接重 delegate；`human_confirm: false` 时可重新 delegate 给同一个 Worker（保留上下文，附纠偏指令）。
4. **收敛**：必要时换人重派或要求 Worker 互助；`human_confirm: true` 时进入收敛前也必须先发 HITL 取得用户同意；目标达成后把多个产出综合为节点的最终交付物。

#### 3.1 多轮迭代：基于上一轮结果继续推演（强约束）

会议室通常需要多轮迭代才能收敛。**两种场景下都禁止**「推倒重来、丢弃已确认内容、循环重复追问已通过项」；区别只在"由谁来确认"。

**A) `human_confirm: true` —— 由用户通过 HITL 表单确认（人工裁决）**

- **继承已确认项**：上一轮用户勾选为正确 / 明确肯定的结论，下一轮**直接视为既成事实**，不再复核、不再追问。
- **吸收纠正与补充**：用户指正的内容按其最新口径覆盖原结论；用户新增的想法作为本轮新输入纳入推演。
- **只推进未决项**：本轮 Worker 派单与 HITL `questions[]` **仅针对**「尚未确认 / 新增 / 被指正后需重做」的部分，**禁止**把上一轮已通过项再次入题。
- **终止条件**：当用户既无新想法、也无新指正（仅追问、确认或表示满意）时，视为本轮收敛，按 §6 归档；不要为「再确认一次」无限循环。

**B) `human_confirm: false` —— 由你自评，自主决定是否再迭代一轮（无 HITL 表单）**

此场景下你**不会**发表单给用户，因此**收敛质量完全由你负责**。不能 Worker 一轮交付就直接归档，也不能为了"显得严谨"无限自我对话。判断要不要再迭代一轮，按以下规则：

- **何时必须再迭代**（满足任一即继续）：
  - Worker 产出未通过 §3 第 3 步「契合度 / 真实性 / 准确性」三项中任意一项；
  - 关键结论缺乏可核验证据（源码 / 文档 / 工单引用缺失或对不上）；
  - 多个 Worker 产出之间相互矛盾，或与系统信息段中工单 / 产品事实冲突；
  - 节点目标涉及高影响 / 不可逆决策（如方案评审、风险评估、自动拆单），需更高置信度。
- **何时允许收敛归档**（全部满足才可）：
  - 三项校验全部通过且证据可回溯；
  - 产出覆盖了「会议产出」清单中的全部文件，无遗漏；
  - 再迭代一轮的新增收益预期较低（边际产出趋零）。
- **每一轮继承上一轮的"自评通过"结论**：已经被你校验通过的部分作为既成事实，**只把发现的缺项**作为下一轮派单 / 自查的输入，**禁止**对已通过项重复审问。
- **迭代上限保护**：原则上不超过 **3** 轮自主迭代；仍未收敛说明已超出 `human_confirm: false` 的自主决策边界，**必须**升级为异常 HITL：`submit_hitl_questionnaire(kind="exception", summary="自主迭代 N 轮仍未收敛，原因…")` 请求人工介入。

### 4. 自主加载产品上下文（按需）

当且仅当现有 Worker 不具备相关能力时，你可以直接调用：

- `whalecloud-dev-tool-base-scripts` → `gnx-tools.js` 检索源码 / 仓库
- `get_doc.py` 获取产品架构 / 需求 / 方案文档
- 工单只读 API（`owner_order_snapshot`、`meeting-summary`）查看历史
- `search_memory` / `add_memory` 同步个人记忆与团队记忆

服务地址与目录约定**只能**取自上方「四、系统信息」；**不得臆造**未出现的 URL 或路径。

### 5. 对用户汇报与 HITL 三场景（强约束）

不暴露内部多轮扯皮；进展（启动了谁）与结论（最终方案）分层呈现。需要人工填写表单的三种场景：

| 场景 | `kind` | 推荐方式 |
|------|--------|----------|
| 会议期间澄清 / 选项收集 | `interactive` | **首选** `submit_hitl_questionnaire` 工具；兼容 ask-user 标记块 |
| 节点终稿确认（`human_confirm: true`） | `result_confirm` | **必须** `submit_hitl_questionnaire(kind="result_confirm")`，`summary` 仅写本节点待确认简表（见下） |
| 异常 / 风险不可控 / 质量不达标 | `exception` | **必须** `submit_hitl_questionnaire(kind="exception")`，在 `summary` 字段写明异常原因 |

- **调用 `submit_hitl_questionnaire` 后立即停止**：不要继续写正文、不要重复总结、不要再调任何工具。系统在工具返回后会自动锁定 `human_intervention`，模型继续产出的内容会被忽略。
- **`human_confirm: false` 时**：自主收敛并输出最终结论，由系统自动归档推进；除非进入异常，否则**不要**调用 HITL 工具。

#### 5.1 问卷题目颗粒度与题型（强约束）

**(a) 颗粒度 · 一个决策点 = 一道独立题**

| 违规做法 | 正确做法 |
|----------|---------|
| ❌ 把 N 个待确认点合并成一道「整体确认 / 部分修改 / 拒绝」单选 | ✅ **每个独立可决策点都要一道独立题**（N 个问题 = N 道独立题） |
| ❌ 只挑「自己拿不定主意」的题目让人选 | ✅ 即使你已经给出推荐默认值，**仍要把每个决策点列为一道题**，把默认值放进选项里（标 ✅ 推荐） |
| ❌ 在 `summary` 里列 14 个决策点，但 `questions` 只放 2 题 | ✅ `questions.length` 必须 **≥** 待确认决策点数量，与 `summary` / 交付文档中的清单一一对应 |

**判定原则**：交付文档 / `result.md` / Worker 产出中每条「带可选项的决策点」「带『可默认结论 X / 是否同意』的问题」，都必须落到 `questions[]` 里成为一道独立题，**不允许打包**。题量较多（>10）时可使用 `render.layout="stepped"` 让前端分步引导，但 `questions` 数组本身必须把每个决策点拆开。

**(b) 题型选择 · 必须支持多选**

| 决策点形态 | 推荐 `type` |
|------------|-------------|
| 二元判断（是 / 否、通过 / 不通过） | `boolean` |
| 互斥结论（只能选一个） | `single` |
| **可同时成立的多项（任选若干、可全选）**，如「该问题涉及哪些产品 / 模块 / 风险类别」 | **必须** `multiple` |
| 短输入（编号、名称） | `text` |
| 长输入（描述、原因、备注） | `textarea` |

只要决策语义允许「同时选中多个」，就**必须**用 `multiple`，**禁止**强行拆成多个 `boolean` 或 `single` 互相覆盖。

**(c) 每题必须支持人工输入（`inputEnabled: true`）**

除「补充题（系统自动追加）」与纯文本输入题（`text` / `textarea`，本身就是输入框）外，**所有** `boolean` / `single` / `multiple` 题都必须显式设置：

```json
{ "id": "...", "type": "single", "title": "...", "options": [...],
  "inputEnabled": true,
  "inputPlaceholder": "或者你的答案：" }
```

这是为了保证用户在「给定选项都不满意」时仍可手动填写答复，避免 HITL 流程被有限选项卡死。**禁止**为了「答复更标准化」而把 `inputEnabled` 关掉。

#### 5.2 `summary` 字段约束

`submit_hitl_questionnaire` 的 `summary` 渲染为桌面端表单上方的「待确认总结」卡片。它**只**用于让用户快速扫一眼「本节点要确认什么」，**不是**交付结论全文、**不是**项目路线图、**不是** SOP 流程预告。

| 禁止写入 `summary` | 说明 |
|--------------------|------|
| ❌ `### 下一步`、`确认后 → …`、`进入某某阶段` | 用户提交问卷后由系统归档并推进；**无需**写「确认后去哪」 |
| ❌ Worker 归档里的 **Phase 1～N**、改造路线图、排期表、可行性计划 | 属于交付文档正文，不要抄进 summary |
| ❌ 把 SOP **下一节点**名写进 summary 当流程预告 | 下一节点由编排器决定 |
| ❌ 整段复制交付结论的「下一步行动」章节 | 只保留与 `questions[]` **题号一一对应**的待确认简表 |

**建议结构（宜短，约一屏内）**：

1. 本节点名 + 工单/产品一行概要（可选）
2. 本节点已产出文件列表（可选，文件名即可）
3. **待确认简表**：列与 `questions` 相同的编号（如 Q1～Q14），每行「维度 / 要点 / 推荐默认（✅）」

### 6. 输出物与归档

| 项 | 要求 |
|----|------|
| 归档位置 | 上方「四、系统信息 · 本节点归档目录（阶段名 · 节点名）」展示的完整路径下；按友好名识别即可，无需手算路径 |
| **命名（强约束）** | **必须**与运行时头「会议产出」（= 系统信息段同名清单）**逐字一致**（如 `需求澄清.md`、`模块功能.md`）；**禁止**改名、加前后缀，**禁止**用 `result.md` 替代清单中的语义化文件名 |
| **生成方式（强约束）** | **必须**调用 `whalecloud-dev-tool-doc-generate`：①`get_skill_info` 读 SKILL.md → ②确认 `templates/` 下有与预期产出物**同名**的模板 → ③`run_skill_script` 传入 `OUTPUT_DIR`（归档目录）/`OUTPUT`（产出物文件名）/`CONTEXT_JSON`（已核验上下文）落盘 |
| **模板缺失** | 若 `templates/` 下找不到与预期产出物同名的模板，或模板字段无法满足本节点需求，**立即** `submit_hitl_questionnaire(kind="exception", summary="doc-generate 缺少 <文件名> 模板…")` 请求人工补齐模板 / 调整清单；**禁止**自行手写 Markdown 绕过模板 |
| 一级标题 | 由模板提供并描述节点产物（如 `# 需求澄清`） |
| 验收字样 | 产物末尾包含「结论」「完成」或「交付」之一，便于 `validation.py` 校验（模板已内置） |
| 用户可见性 | 仅最终结论与必要进展对用户可见；Worker 之间的扯皮、调试日志归档不外发 |

**异常介入**（与 `human_confirm` 无关）：协作超时、产物质量/真实度无法达标、风险不可控时，**必须**调用 `submit_hitl_questionnaire(kind="exception", summary="异常原因…")`；**严禁**只口头宣称问卷已提交而不实际调用工具。

### 7. 不变量

1. **会议室 = SOP 节点**：当前节点以外的产物不要写入本次归档。
2. **能力边界先行**：分派前必须先读「参会能力卡片」；Worker 超界时**应**申请改派。
3. **真实可核验**：任何结论必须能从源码、文档、工单中找到证据；不得臆造。
4. **小鲸主持**：所有 Worker 的产出最终由你综合、校验后才算节点完成。
5. **结果确认先于归档**：`human_confirm: true` 时，用户表单确认是写入归档与推进节点的前置条件。
6. **异常必介入**：异常场景下必须请求人工，不受 `human_confirm` 开关限制。
7. **不暗箱**：不得跳过 SOP 节点依赖、不得把 Worker 的结果未经检查直接当作最终结论、不得在结果确认 / 异常门控应触发时只口头宣称「问卷已提交」而不调用工具、不得在结果确认门控开启时自行写入归档或推进节点。
8. **产出物模板化**：归档文件名必须与运行时头「会议产出」清单逐字一致，且必须经 `whalecloud-dev-tool-doc-generate` 模板生成；模板缺失或不匹配时只能走异常 HITL，不得手写绕过。

> 违反任一不变量视为节点未完成，归档校验会拒绝该产物。
"""

# 向后兼容：旧代码 / 测试用例可能 import 这个名字。
# 新代码请改用 :func:`get_meeting_room_rules`。
_MEETING_ROOM_RULES = _MEETING_ROOM_RULES_FALLBACK


# ─── 数据结构 ───────────────────────────────────────────────────────────


@dataclass
class MeetingRoomContext:
    """会议室运行时上下文（用于装配 system prompt）。"""

    role: Role
    scope_type: str
    scope_id: str
    ticket_title: str
    node_id: str
    node_name: str
    node_intent: str
    stage_id: int
    stage_name: str
    host_profile_id: str
    host_profile_name: str
    host_llm_endpoint: str
    worker_llm_endpoint: str
    worker_profile_ids: list[str]
    archive_dir: str
    prompt_supplement: str = ""
    self_profile_id: str = ""

    def template_vars(self) -> dict[str, str]:
        """流程 / 路径类占位符。

        新版规则段已不依赖这些变量（运行时头与「系统信息」段直接展示具体值），
        但保留映射以便测试 / 自定义 `skill_body` 时仍能渲染。
        """
        return {
            "ROLE": self.role,
            "HOST_PROFILE_ID": self.host_profile_id,
            "HOST_PROFILE_NAME": self.host_profile_name,
            "HOST_LLM_ENDPOINT": self.host_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY,
            "WORKER_LLM_ENDPOINT": self.worker_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY,
            "ARCHIVE_DIR": self.archive_dir,
            "STAGE_ID": str(self.stage_id),
            "NODE_ID": self.node_id,
        }


# ─── 能力卡片 ───────────────────────────────────────────────────────────


def resolve_agent_profile(profile_id: str) -> AgentProfile | None:
    """解析参会智能体 Profile（供 dynamic_prompt 等模块使用）。"""
    return _resolve_profile(profile_id)


def _resolve_profile(profile_id: str) -> AgentProfile | None:
    pid = (profile_id or "").strip()
    if not pid:
        return None
    try:
        store = get_profile_store()
        p = store.get(pid)
        if p is not None:
            return p
    except Exception as exc:
        logger.debug("get_profile_store failed for %s: %s", pid, exc)
    try:
        from synapse.agents.presets import SYSTEM_PRESETS

        for sp in SYSTEM_PRESETS:
            if sp.id == pid:
                return sp
    except Exception:
        return None
    return None


_SKILL_LABEL_CACHE: dict[str, str | None] = {}


def _normalize_skill_id(skill_ref: str) -> str:
    norm = str(skill_ref).strip()
    if not norm:
        return ""
    return norm.split("@", 1)[-1] if "@" in norm else norm


def resolve_skill_label(skill_id: str) -> str | None:
    """从 SKILL.md frontmatter 读取 ``label``（与 Setup Center 展示一致）。"""
    sid = _normalize_skill_id(skill_id)
    if not sid:
        return None
    if sid in _SKILL_LABEL_CACHE:
        return _SKILL_LABEL_CACHE[sid]
    label: str | None = None
    path = _find_external_skill_file(sid)
    if path is not None:
        try:
            from synapse.skills.parser import skill_parser

            parsed = skill_parser.parse_file(path)
            raw = parsed.metadata.label
            if raw and str(raw).strip():
                label = str(raw).strip()
        except Exception as exc:
            logger.debug("resolve skill label %s failed: %s", sid, exc)
    _SKILL_LABEL_CACHE[sid] = label
    return label


def format_skill_entry(skill_ref: str) -> str:
    """展示用：``skill_id（label）``；无 label 时仅 id。"""
    sid = _normalize_skill_id(skill_ref)
    if not sid:
        return ""
    label = resolve_skill_label(sid)
    if label:
        return f"{sid}（{label}）"
    return sid


def format_skill_entries(skills: Iterable[str], *, limit: int = 0) -> list[str]:
    out: list[str] = []
    for s in skills:
        entry = format_skill_entry(str(s))
        if not entry:
            continue
        out.append(entry)
        if limit and len(out) >= limit:
            break
    return out


def _short_skill_names(skills: Iterable[str], limit: int = 6) -> list[str]:
    """兼容旧调用：仅返回 skill id（不含 label）。"""
    out: list[str] = []
    for s in skills:
        sid = _normalize_skill_id(str(s))
        if not sid:
            continue
        out.append(sid)
        if len(out) >= limit:
            break
    return out


def _format_capability_card(
    profile: AgentProfile,
    *,
    role: str,
    llm_endpoint: str,
) -> str:
    name = profile.get_display_name() or profile.name or profile.id
    skills = format_skill_entries(profile.skills or [], limit=6)
    desc = (profile.description or "").strip()
    custom = (profile.custom_prompt or "").strip()

    lines: list[str] = []
    lines.append(f"## {name} (`{profile.id}`)")
    lines.append(f"- 角色：{role} · 端点：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`")
    if desc:
        lines.append(f"- 简介：{desc}")
    if skills:
        lines.append(f"- 核心技能：{', '.join(skills)}")
    if custom:
        short = re.sub(r"\s+", " ", custom).strip()
        if len(short) > 160:
            short = short[:160] + "…"
        lines.append(f"- 主张：{short}")
    return "\n".join(lines)


def _format_self_capability_block(
    profile: AgentProfile | None,
    *,
    fallback_id: str,
    llm_endpoint: str,
) -> str:
    """渲染 Worker 视角下「你的能力档案」段：用第一人称语气强化身份与边界。

    与 `_format_capability_card` 的区别：
    - 不显示"角色：worker"（已在顶部"当前角色"中说明）
    - 主张不截断，完整展示其 custom_prompt
    - 若 profile 找不到则给出兜底身份说明
    """
    if profile is None:
        return (
            f"- **智能体 ID**：`{fallback_id or '(unknown)'}`\n"
            f"- **使用端点**：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`\n"
            "- **简介**：未在 Profile 库中找到你的档案，请按通用研发协作者身份执行；遇到不确定时主动反问小鲸。"
        )

    name = profile.get_display_name() or profile.name or profile.id
    skills = format_skill_entries(profile.skills or [], limit=12)
    desc = (profile.description or "").strip()
    custom = (profile.custom_prompt or "").strip()

    lines: list[str] = []
    lines.append(f"- **身份**：{name}（`{profile.id}`）")
    lines.append(f"- **使用端点**：`{llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`")
    if desc:
        lines.append(f"- **简介**：{desc}")
    if skills:
        lines.append(f"- **你具备的技能**（仅在这些范围内执行任务）：")
        for s in skills:
            lines.append(f"  - {s}")
    if custom:
        lines.append("- **角色主张 / 工作风格**：")
        for line in custom.splitlines():
            t = line.rstrip()
            if t:
                lines.append(f"  > {t}")
    return "\n".join(lines)


def build_capability_cards(
    *,
    host_profile_id: str,
    worker_profile_ids: list[str],
    host_llm_endpoint: str,
    worker_llm_endpoint: str,
    exclude_self_id: str | None = None,
    include_host: bool = True,
) -> str:
    """渲染参会智能体能力卡片清单。

    - `exclude_self_id`: 排除「自己」的 worker 卡片，避免自我介绍冗余。
    - `include_host`: 是否渲染 host 卡片。host 视角下应传 ``False``（自己就是小鲸，
      无需再看自己的卡片）；worker 视角下保留 host 卡片，便于明确主持人身份。
    """
    cards: list[str] = []

    if include_host and (not exclude_self_id or exclude_self_id != host_profile_id):
        host_profile = _resolve_profile(host_profile_id)
        if host_profile is not None:
            cards.append(_format_capability_card(host_profile, role="host", llm_endpoint=host_llm_endpoint))

    for wid in worker_profile_ids or []:
        wid = str(wid).strip()
        if not wid or wid == host_profile_id:
            continue
        if exclude_self_id and wid == exclude_self_id:
            continue
        wp = _resolve_profile(wid)
        if wp is None:
            cards.append(
                f"## {wid}\n- 角色：worker · 端点：`{worker_llm_endpoint or DEFAULT_LLM_ENDPOINT_KEY}`\n"
                "- 简介：未在 Profile 库中找到，使用兜底身份。"
            )
            continue
        cards.append(
            _format_capability_card(
                wp,
                role="worker",
                llm_endpoint=worker_llm_endpoint,
            )
        )

    if not cards:
        return "（除你之外暂无其他参会智能体；如需协作请在『系统智能体管理』中配置。）"

    return "\n\n".join(cards)


# ─── 角色裁剪 + 渲染 ────────────────────────────────────────────────────


def trim_skill_for_role(skill_body: str, role: Role) -> str:
    """按角色返回流程规则正文。

    - ``host``：原样返回（规则段仅给 host 看）。
    - ``worker``：返回空字符串——worker 的边界与协作要点已在运行时头的
      「协作专家职责」+「你的能力档案」中说清楚，不再追加任何长文规范。
    """
    if role == "worker":
        return ""
    return skill_body


def render_skill(skill_body: str, variables: dict[str, str]) -> str:
    """填充规范正文中的占位符。

    新版规则段已不含 ``{ROLE}`` / ``{ARCHIVE_DIR}`` / ``{DYNAMIC_MEETING_CONTEXT}`` 等占位
    （这些信息全部在运行时头与「系统信息」段直接展示），本函数仅作为兼容入口保留。
    """
    rendered = skill_body
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _extract_product_label(init_context: dict[str, Any] | None) -> str:
    """从 init_context 中提取『涉及产品』展示值。"""
    if not isinstance(init_context, dict):
        return "（未识别产品）"
    product = init_context.get("product")
    if not isinstance(product, dict):
        return "（未识别产品）"
    prod = str(product.get("prod") or "").strip()
    version = str(product.get("version") or "").strip()
    name = str(product.get("name") or product.get("product_name") or "").strip()
    suffix = f"@{version}" if version else ""
    if name and prod:
        return f"{name}（prod=`{prod}`{suffix}）"
    if prod:
        return f"`{prod}`{suffix}"
    if name:
        return name
    return "（未识别产品）"


def _human_confirm_label(binding: dict[str, Any] | None) -> str:
    if not isinstance(binding, dict):
        return "未配置"
    if binding.get("human_confirm"):
        return "**开启**（结果需用户表单确认后才能归档/推进）"
    return "关闭（自主收敛后自动归档推进）"


def _extract_ticket_description(init_context: dict[str, Any] | None) -> str:
    """从 init_context.order 中提取工单描述（含影响范围，若存在）。"""
    if not isinstance(init_context, dict):
        return "（未提供工单描述）"
    order = init_context.get("order")
    if not isinstance(order, dict):
        return "（未提供工单描述）"
    desc = str(order.get("description") or "").strip()
    impact = str(order.get("impact") or "").strip()
    parts: list[str] = []
    if desc:
        parts.append(desc)
    if impact:
        parts.append(f"影响范围：{impact}")
    if not parts:
        return "（未提供工单描述）"
    return " ｜ ".join(parts)


def _format_meeting_outputs(binding: dict[str, Any] | None) -> str:
    """从 binding.node_outputs 渲染「会议产出」展示串（与归档强约束一一对应）。"""
    if not isinstance(binding, dict):
        return "（未配置会议产出，可能为系统节点或配置缺失）"
    outs = [
        str(n).strip()
        for n in (binding.get("node_outputs") or [])
        if str(n).strip() and not str(n).strip().startswith("（")
    ]
    if not outs:
        return "（未配置会议产出，可能为系统节点或配置缺失）"
    return "、".join(f"`{n}`" for n in outs)

def build_meeting_runtime_header(
    context: MeetingRoomContext,
    *,
    now_iso: str | None = None,
    binding: dict[str, Any] | None = None,
    init_context: dict[str, Any] | None = None,
) -> str:
    """生成"运行时头"——替代原 Identity / Catalogs / Multi-Agent 段。

    Host 与 Worker 各加一段角色专属说明；末尾附参会能力卡片。
    无论 host 还是 worker，能力卡片都会**排除自己**，避免自我介绍冗余。
    """
    from datetime import datetime as _dt

    role = context.role
    self_pid = (context.self_profile_id or "").strip()
    if not self_pid:
        if role == "host":
            self_pid = context.host_profile_id
        elif context.worker_profile_ids:
            self_pid = context.worker_profile_ids[0]

    role_label = "小鲸主持人" if role == "host" else "协作专家"
    now = (now_iso or _dt.now().isoformat(timespec="seconds")).strip()
    product_label = _extract_product_label(init_context)
    confirm_label = _human_confirm_label(binding)
    ticket_desc = _extract_ticket_description(init_context)
    meeting_outputs_label = _format_meeting_outputs(binding)
    supplement = ""
    if isinstance(binding, dict):
        supplement = str(binding.get("prompt_supplement") or "").strip()
    if not supplement:
        supplement = (context.prompt_supplement or "").strip()

    lines: list[str] = []
    lines.append("# 你是 Synapse 研发会议室参会智能体")
    lines.append("")
    lines.append(f"- **当前角色**：{role_label}（`role={role}`）")
    lines.append(f"- **会议工单**:[`{context.scope_id}`]-{context.ticket_title}")
    lines.append(f"- **工单描述**：{ticket_desc}")
    lines.append(f"- **涉及产品**：{product_label}")
    lines.append(f"- **会议任务**：{context.stage_name}阶段的{context.node_name}任务")
    lines.append(f"- **会议产出**：{meeting_outputs_label}（最终归档文件名必须**完全等于**这里列出的名字；详见下方归档约束）")
    lines.append(f"- **会议目标**：{context.node_intent}")
    lines.append(f"- **人工确认**：{confirm_label}")
    lines.append(f"- **当前时间**：{now}")
    lines.append("- **回复语言**：中文")
    if supplement:
        lines.append(f"- **运营补充**：{supplement}")
    lines.append("")

    if role == "host":
        lines.append("## 主持人职责")
        lines.append("- 必须熟悉本工单对应的产品信息（产品文档 / 仓库代码 / 历史工单），所有决策都要基于产品事实；缺少产品事实时可以拒绝或报错，**不得臆造**。")
        lines.append("- 获取产品信息事实的工作**优先委派**给协作智能体；当且仅当现有 worker 不具备某项能力时，才自行调用工具/技能收集。")
        lines.append("- 基于产品事实，**专注于上方「会议目标」中要做的具体事情**，不进行超出本节点目标的决策。")
        lines.append("- 通过 `submit_meeting_work_plan` 提交结构化计划后，再调用 `delegate_to_agent` 或 `delegate_parallel` 派单；委派后等待 worker 返回再继续。")
        lines.append("- 收到 worker 产出后，按「契合度 / 真实性 / 准确性」三项逐条校验；不通过则**重新派单**给同一 worker 并指出缺项。")
        lines.append("- **多轮迭代继承上一轮结果**（共性原则）：上一轮已被认可 / 校验通过的结论**直接视为既成事实**，已被指正的按最新口径覆盖、新增想法纳入推演；下一轮**只**推进未决 / 新增 / 需重做的部分，**禁止**推倒重来或重复审问已通过项；详见下方规范 §3.1。")
        lines.append("- **`human_confirm: true` 时**：每轮决策都通过 HITL 表单交由用户裁决；当用户无新想法亦无新指正时即视为本轮收敛。")
        lines.append("- **`human_confirm: false` 时**：不发表单，由你自评收敛质量——若三项校验（契合度 / 真实性 / 准确性）有任一不通过、证据缺失、Worker 产出相互矛盾、或决策高影响，则**必须再迭代一轮**；三项全过且产出已覆盖「会议产出」清单时才能归档；自主迭代原则上**不超过 3 轮**，仍未收敛时升级为 `submit_hitl_questionnaire(kind=\"exception\", ...)` 请求人工介入。")
        lines.append("- 节点目标完成且通过自检后，按下方规范第 6 节归档到「本节点归档目录」（系统信息段已展示完整路径，并带阶段名 · 节点名便于识别）并报告结论。")
        lines.append("- **会议产出 = 归档文件名（硬约束）**：上方「会议产出」列出的就是本节点必须落盘的文件，归档文件名必须与之**逐字一致**（如 `需求澄清.md`、`模块功能.md`），**禁止**改名 / 加前后缀 / 用 `result.md` 替代；多文件时每一项都要落盘，且不能多出清单之外的文件。")
        lines.append('- **必须走 `whalecloud-dev-tool-doc-generate` 生成产出物**：先 `get_skill_info(whalecloud-dev-tool-doc-generate)` 读 SKILL.md、确认 `templates/` 下存在与预期产出物**同名**的模板，再 `run_skill_script` 填模板落盘；若模板缺失或与本节点产出物不匹配，**立即** `submit_hitl_questionnaire(kind="exception", summary="doc-generate 缺少 <文件名> 模板，需人工补齐模板或调整产出物清单")` 请求人工介入，**禁止**自行手写 Markdown 兜底。')
        lines.append("- `human_confirm` 开启或出现异常 / 风险不可控时，必须调用 `submit_hitl_questionnaire`，**禁止伪造用户答复**，**禁止只口头宣称问卷已提交**。")
        lines.append("- 可用 worker 名单与能力边界见下方「参会能力卡片」（已排除你自己）；派单时 task 描述应指向卡片上的具体 skill / 能力，便于 Worker 加载对应 SKILL。")
        lines.append("- 若你（Host）自身 Profile 也配置了技能且必须自行执行（Worker 不具备时），同样须先 `get_skill_info(skill_id)` 读取 SKILL.md，再 `run_skill_script` 或按 SKILL 指引用 shell / 读写工具执行，**禁止**跳过 SKILL 硬猜流程。")
    else:
        lines.append("## 协作专家职责")
        lines.append("- 必须熟悉本工单对应的产品信息（产品文档 / 仓库代码 / 历史工单），所有决策都要基于产品事实；缺少产品事实时可以拒绝或报错，**不得臆造**。")
        lines.append("- 你是子 Agent，**禁止再发起委派**（不要调用 delegate_to_agent / delegate_parallel），也无法直接联系其他 Worker；任何「需要别人配合」的诉求都改为在产出里向小鲸说明。")
        lines.append("- 仅在「你的能力档案」描述的能力边界内执行任务；超出边界时**坦诚向小鲸说明**并建议改派，不要勉强执行、不要伪造结果。")
        lines.append("- **接到子任务后，必须先**对「你的能力档案」里与任务相关的 skill 调用 `get_skill_info(skill_id)` 加载 SKILL.md，再按 SKILL 指引执行（`run_skill_script` 或 shell / 读写工具）；**禁止**不看 SKILL 直接用通用工具硬做。")
        lines.append("- 输出必须自给自足：含结论、证据、产物路径；Markdown 一级标题，结尾含「结论」「完成」或「交付」。")
        lines.append("- 你看不到主会话历史，也看不到其他 Worker 的能力卡片；小鲸已在 prompt 中给了你执行所需的全部上下文，信息不足时主动反问。")

    lines.append("")
    lines.append("## 工具与技能使用")
    lines.append("- **基础工具**（函数调用，禁止伪造输出）：shell / read_file / write_file / list_directory / web_search 等。")
    lines.append("- **外部技能（SKILL）执行路径（强约束）**：")
    lines.append("  1. 从「参会能力卡片」或「你的能力档案」确认本任务对应的 `skill_id`；不确定时用 `list_skills` 查找。")
    lines.append("  2. **必须先** `get_skill_info(skill_id)` 读取 SKILL.md 全文与脚本列表（会议室不会预加载 Skill Catalog）。")
    lines.append("  3. 有脚本的用 `run_skill_script`；instruction-only 技能按 SKILL 指引写代码并 `run_shell` / 读写文件。")
    lines.append("  4. 许多研发技能（需求澄清、代码检索、文档生成等）**只有走完上述路径才算正确使用**；仅 grep / read_file 不算替代 SKILL。")
    lines.append("- 涉及破坏性操作（rm / 大批量写入 / 网络副作用）需在产物中显式标注理由。")
    lines.append("- 任何结论必须可由源码、文档或工单证据回溯；严禁虚构。")
    lines.append("")

    if role == "host":
        cards = build_capability_cards(
            host_profile_id=context.host_profile_id,
            worker_profile_ids=context.worker_profile_ids,
            host_llm_endpoint=context.host_llm_endpoint,
            worker_llm_endpoint=context.worker_llm_endpoint,
            exclude_self_id=self_pid or None,
            include_host=False,
        )
        lines.append("## 参会能力卡片")
        lines.append("")
        lines.append("以下是本场会议可用的协作智能体（不含你自己），分派任务时必须先比对其能力边界：")
        lines.append("")
        lines.append(cards)
    else:
        self_profile = _resolve_profile(self_pid) if self_pid else None
        self_block = _format_self_capability_block(
            self_profile,
            fallback_id=self_pid,
            llm_endpoint=context.worker_llm_endpoint,
        )
        lines.append("## 你的能力档案")
        lines.append("")
        lines.append("这是小鲸在本节点为你配置的角色档案——所有任务都必须在此边界内执行；超界即向小鲸申请改派，不要勉强或臆造。")
        lines.append("")
        lines.append(self_block)
    lines.append("")
    return "\n".join(lines)


def build_room_skill_prompt(
    context: MeetingRoomContext,
    *,
    skill_body: str | None = None,
    init_context: dict[str, Any] | None = None,
    binding: dict[str, Any] | None = None,
    sop_node_display: str = "",
) -> str:
    """生成会议室完整 system prompt。

    结构（精简后，参见 docs `多智能体研发会议室实现方案.md` §9）：

    1. **运行时头**（`build_meeting_runtime_header`）—— Host / Worker 都看：
       身份、工单、会议任务/目标、人工确认、时间、角色职责、工具通则、能力卡片或能力档案。
    2. **系统信息**（`build_dynamic_meeting_context(include_overview=False)`）—— 都看：
       仅工单 / 产品 / 系统三段；运行时头已展示的「会议节点/会议目标/人工确认/协作智能体」
       不再重复。
    3. **会议室流程与规则**（`_MEETING_ROOM_RULES`）—— **仅 Host** 追加：
       节点成功标准、HITL 语义、工作循环、产品上下文加载、HITL 三场景与 summary 约束、
       归档要求、不变量。

    `skill_body` 仅供测试 / 缓存等场景覆盖。
    """
    from synapse.rd_meeting.dynamic_prompt import build_dynamic_meeting_context

    bind = dict(binding) if binding else {
        "node_id": context.node_id,
        "node_name": context.node_name,
        "stage_id": context.stage_id,
        "stage_name": context.stage_name,
        "node_intent": context.node_intent,
        "host_profile_id": context.host_profile_id,
        "worker_profile_ids": context.worker_profile_ids,
        "host_llm_endpoint_key": context.host_llm_endpoint,
        "worker_llm_endpoint_key": context.worker_llm_endpoint,
        "prompt_supplement": context.prompt_supplement,
        "human_confirm": False,
    }

    header = build_meeting_runtime_header(
        context,
        binding=bind,
        init_context=init_context,
    )

    system_info = build_dynamic_meeting_context(
        binding=bind,
        init_data=init_context,
        scope_type=context.scope_type,  # type: ignore[arg-type]
        scope_id=context.scope_id,
        sop_node_display=sop_node_display or context.node_name,
        include_overview=False,
    )

    body = skill_body if skill_body is not None else get_meeting_room_rules()
    body = trim_skill_for_role(body, context.role)
    rules_block = render_skill(body, context.template_vars()).strip() if body else ""

    parts = [header.rstrip(), "", system_info.strip()]
    if rules_block:
        parts.extend(["", "---", "", rules_block])
    return "\n".join(parts)


def _self_profile_id_for_context(context: MeetingRoomContext) -> str | None:
    """Worker 视角时，从 worker_profile_ids 推断当前 Worker 的 profile id。

    Phase 当前默认把 worker_profile_ids[0] 作为自己；后续 host 通过 delegate
    工具进入时会有独立 instance_key，再由调用方覆盖。
    """
    if context.role == "worker" and context.worker_profile_ids:
        first = str(context.worker_profile_ids[0]).strip()
        return first or None
    return None


def make_context(
    *,
    role: Role,
    binding: dict[str, Any],
    scope_type: str,
    scope_id: str,
    ticket_title: str,
    archive_dir: str,
    self_profile_id: str = "",
) -> MeetingRoomContext:
    """从 binding（resolve_node_binding 输出）+ scope 信息组装上下文。"""
    host_id = str(binding.get("host_profile_id") or "default").strip() or "default"
    host_profile = _resolve_profile(host_id)
    host_name = (
        host_profile.get_display_name() if host_profile else host_id
    )

    worker_ids = list(binding.get("worker_profile_ids") or [])

    return MeetingRoomContext(
        role=role,
        scope_type=str(scope_type or "demand"),
        scope_id=str(scope_id or ""),
        ticket_title=str(ticket_title or ""),
        node_id=str(binding.get("node_id") or "pending"),
        node_name=str(binding.get("node_name") or node_display_name(str(binding.get("node_id") or ""))),
        node_intent=str(binding.get("node_intent") or binding.get("intent") or ""),
        stage_id=int(binding.get("stage_id") or 0),
        stage_name=str(binding.get("stage_name") or stage_name_for_id(int(binding.get("stage_id") or 0))),
        host_profile_id=host_id,
        host_profile_name=str(host_name),
        host_llm_endpoint=str(binding.get("host_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY),
        worker_llm_endpoint=str(binding.get("worker_llm_endpoint_key") or DEFAULT_LLM_ENDPOINT_KEY),
        worker_profile_ids=[str(w) for w in worker_ids if str(w).strip()],
        archive_dir=str(archive_dir or ""),
        prompt_supplement=str(binding.get("prompt_supplement") or ""),
        self_profile_id=str(self_profile_id or "").strip(),
    )


