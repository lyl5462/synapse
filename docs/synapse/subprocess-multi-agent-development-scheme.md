# 多智能体研发方案（subprocess 模式）12

## 概述

本文档描述基于 **subprocess** 的多智能体协同研发方案。本方案复用现有研发会议室的智能体管理机制，主智能体负责任务分解与分发，子智能体通过 subprocess 调用 Cursor CLI 执行代码开发任务。

## 核心设计约束

| 约束项 | 说明 |
|--------|------|
| 子智能体 | 单实例，不考虑并发 |
| 进度跟踪 | 使用 Cursor CLI 流式输出（`--output-format stream-json`） |
| 人类确认 | 非交互模式下默认拒绝危险操作 |
| 产物管理 | 结构化产物清单 + 代码文件 + 执行日志 |

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│  研发会议室（复用现有 MeetingRoomOrchestrator）              │
│  ├── 主智能体（小鲸 Host）                                 │
│  │   ├── 任务分解 + 分发                                  │
│  │   └── 进度协调 + 结果汇总                               │
│  └── 子智能体（Worker，单实例）                           │
│      ├── 通过 subprocess 调用 Cursor CLI                 │
│      ├── 顺序执行任务列表                                  │
│      └── 回调进度 / 提交产物                               │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Cursor CLI（流式输出模式）                                │
│  ├── subprocess 调用：cursor agent -p "..."               │
│  ├── --output-format stream-json：实时进度跟踪             │
│  ├── 工作目录隔离：独立 worktree                          │
│  └── stdin: 人类确认响应（y/n）                          │
└─────────────────────────────────────────────────────────────┘
```

## 复用研发会议室的智能体管理机制

### 1.1 主智能体委派子智能体（单实例）

复用现有 `MeetingRoomOrchestrator` 的委派机制，单子智能体顺序执行：

```python
# 主智能体委派任务给单个子智能体
await delegate_to_agent(
    agent_id="dev-worker-01",
    message=f"""请执行以下代码开发任务：

任务：实现用户认证模块

步骤：
1. 阅读函数级方案文档：{doc_path}
2. 使用 subprocess 调用 Cursor CLI 生成代码（流式输出）
3. 监控执行进度，处理人类确认请求
4. 产出代码到 {output_dir}
5. 更新产物清单 {output_dir}/artifacts/manifest.json
""",
    reason="任务计划 ID: xxx"
)
```

### 1.2 执行计划提交

```python
# 提交结构化执行计划（复用现有 work_plan）
await submit_meeting_work_plan([
    {
        "agent_id": "dev-worker-01",
        "task": "实现用户认证模块",
        "reason": "需要 Python 开发技能",
        "plan_item_id": "item-001"
    }
])
```

### 1.3 子智能体配置（复用 agent_runtime）

```python
from synapse.rd_meeting.agent_runtime import (
    apply_meeting_slim_tools,
    apply_meeting_agent_runtime,
)
from synapse.rd_meeting.agent_session import (
    bind_meeting_agent_session,
    ensure_host_session,
)

async def configure_dev_sub_agent(agent: Agent, config: DevAgentConfig):
    # 1. 绑定会话（使 delegate_* 可用）
    session = ensure_host_session(room_id="xxx", host_profile_id="dev-worker")
    bind_meeting_agent_session(agent, session)

    # 2. 设置工作目录（沙箱）
    agent.default_cwd = config.worktree_path

    # 3. 裁剪工具（只保留必要工具）
    apply_meeting_slim_tools(agent, role="worker")

    # 4. 注入 Cursor CLI 技能
    skill_ids = config.skills + ["cursor-cli"]
    summaries = collect_skill_summary_blocks(agent, skill_ids)
    agent._context.system = apply_meeting_agent_runtime(
        agent,
        role="worker",
        profile=config.profile,
        base_system_prompt=summaries
    )
```

### 1.4 活动追踪（复用 agent_activity）

```python
from synapse.rd_meeting.agent_activity import (
    record_input,
    record_output,
    try_record_tool_from_agent,
)

# 记录子智能体输入
record_input(agent, source="host", content=task_description)

# 记录 Cursor CLI 调用（包含流式输出事件）
try_record_tool_from_agent(agent, tool_name="cursor_cli_stream", ...)

# 记录输出
record_output(agent, content=code_output)
```

## Cursor CLI 操作接口

### 2.1 Cursor CLI 流式输出模式

根据 Cursor 官方文档，推荐使用流式输出跟踪进度：

```bash
cursor agent -p "任务描述" --output-format stream-json --stream-partial-output
```

**流式输出事件类型**：

| type | subtype | 说明 |
|------|---------|------|
| `system` | `init` | 初始化，显示使用的模型 |
| `assistant` | - | AI 生成的文本内容 |
| `tool_call` | `started` | 开始执行工具（如 writeFile、readFile、Bash） |
| `tool_call` | `completed` | 工具执行完成 |
| `user` | - | 用户输入提示（需人类确认） |
| `result` | - | 最终结果，包含耗时统计 |

### 2.2 CursorCLI 客户端封装

```python
import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

@dataclass
class CursorToolEvent:
    """Cursor 工具调用事件"""
    tool_type: str  # writeFile, readFile, Bash, etc.
    action: str     # started, completed
    path: str | None = None
    command: str | None = None
    result: dict | None = None
    duration_ms: int = 0

@dataclass
class CursorProgress:
    """Cursor 执行进度"""
    tool_events: list[CursorToolEvent] = field(default_factory=list)
    total_chars: int = 0
    duration_ms: int = 0
    status: str = "running"  # running, waiting_confirm, completed, error

class CursorCLI:
    """Cursor CLI 操作客户端（供子智能体调用）"""

    def __init__(
        self,
        cursor_exe: str | None = None,
        worktree: str | None = None,
        timeout: int = 300,
        auto_confirm: bool = False,
    ):
        self.cursor_exe = cursor_exe or self._find_cursor_exe()
        self.worktree = Path(worktree) if worktree else None
        self.timeout = timeout
        self.auto_confirm = auto_confirm  # True = 自动确认，False = 默认拒绝

    def _find_cursor_exe(self) -> str:
        """查找 cursor.exe 路径"""
        import shutil
        path = shutil.which("cursor")
        if path:
            return path
        local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
        default_path = local_appdata / "Cursor" / "cursor.exe"
        if default_path.exists():
            return str(default_path)
        raise RuntimeError("cursor.exe not found in PATH or default location")

    async def agent_stream(
        self,
        prompt: str,
        progress_callback: AsyncIterator[CursorProgress] | None = None,
    ) -> CursorResult:
        """
        调用 cursor agent 执行任务（流式输出模式）

        Args:
            prompt: 任务描述
            progress_callback: 进度回调，用于实时报告执行状态

        Returns:
            CursorResult: 包含 stdout、stderr、returncode
        """
        cmd = [
            self.cursor_exe,
            "agent",
            "-p", prompt,
            "--output-format", "stream-json",
            "--stream-partial-output",
        ]

        if self.worktree:
            cmd.extend(["--worktree", str(self.worktree)])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.worktree) if self.worktree else None,
        )

        progress = CursorProgress()
        stdout_lines = []
        full_stdout = []

        try:
            # 异步读取 stdout 和处理进度
            async def read_stdout():
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if line_str:
                        stdout_lines.append(line_str)
                        full_stdout.append(line_str)
                        # 解析流式输出
                        event = self._parse_stream_line(line_str)
                        if event and progress_callback:
                            await progress_callback(event)

            # 处理 stdin（人类确认）
            async def write_stdin():
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    # 检测确认提示
                    if self._is_confirm_prompt(line_str):
                        # 等待一小段时间看是否有更多输出
                        await asyncio.sleep(0.5)
                        # 根据策略决定确认还是拒绝
                        if self.auto_confirm:
                            process.stdin.write(b"y\n")
                        else:
                            process.stdin.write(b"n\n")
                        await process.stdin.drain()
                        progress.status = "waiting_confirm"

            # 并发执行读写任务
            await asyncio.gather(read_stdout(), write_stdin())

            # 等待进程结束
            await asyncio.wait_for(process.wait(), timeout=self.timeout)

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            progress.status = "error"
            raise CursorTimeoutError(f"Cursor CLI timed out after {self.timeout}s")

        progress.status = "completed"
        return CursorResult(
            stdout="\n".join(stdout_lines),
            stderr="",
            returncode=process.returncode,
            progress=progress,
        )

    def _parse_stream_line(self, line: str) -> CursorProgress | None:
        """解析流式输出行"""
        try:
            data = json.loads(line)
            msg_type = data.get("type")
            subtype = data.get("subtype")

            if msg_type == "tool_call":
                tool_call = data.get("tool_call", {})
                # 提取工具信息
                tool_type = None
                path = None
                command = None
                result = None

                if "writeToolCall" in tool_call:
                    tool_type = "writeFile"
                    path = tool_call["writeToolCall"].get("args", {}).get("path")
                    result = tool_call["writeToolCall"].get("result")
                elif "readToolCall" in tool_call:
                    tool_type = "readFile"
                    path = tool_call["readToolCall"].get("args", {}).get("path")
                    result = tool_call["readToolCall"].get("result")
                elif "Bash" in tool_call:
                    tool_type = "Bash"
                    command = tool_call["Bash"].get("args", {}).get("command")
                    result = tool_call["Bash"].get("result")

                return CursorToolEvent(
                    tool_type=tool_type or "unknown",
                    action=subtype or "unknown",
                    path=path,
                    command=command,
                    result=result,
                )

            elif msg_type == "result":
                return data.get("duration_ms", 0)

        except json.JSONDecodeError:
            pass
        return None

    def _is_confirm_prompt(self, line: str) -> bool:
        """检测是否需要人类确认"""
        confirm_keywords = [
            "Run command?",
            "(y/n)",
            "[y/N]",
            "Authorize",
            "confirm",
            " approve ",
        ]
        return any(kw in line for kw in confirm_keywords)


@dataclass
class CursorResult:
    stdout: str
    stderr: str
    returncode: int
    progress: CursorProgress | None = None

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def get_code(self) -> str:
        """从输出中提取生成的代码"""
        return self.stdout
```

## 子智能体开发流程

### 3.1 子智能体开发主循环（单实例顺序执行）

```python
async def dev_sub_agent_loop(agent: Agent, config: DevAgentConfig):
    """单子智能体开发主循环"""

    cursor = CursorCLI(
        worktree=config.worktree_path,
        timeout=config.timeout or 300,
        auto_confirm=config.auto_confirm or False,
    )

    # 1. 初始化产物目录
    await init_artifacts_dir(config.output_dir)

    # 2. 接收任务列表（从主智能体委派消息中解析）
    tasks = await receive_task_list()
    if not tasks:
        return

    for task in tasks:
        # 3. 阅读函数级方案文档
        doc_content = await read_file(task.doc_path)

        # 4. 解析方案文档中的函数列表
        functions = parse_functions_from_doc(doc_content)

        # 5. 逐个实现函数
        for func in functions:
            await implement_function(
                cursor=cursor,
                func=func,
                context=doc_content,
                output_dir=config.output_dir,
                agent=agent,
            )

    # 6. 生成产物清单
    await generate_artifacts_manifest(config.output_dir)


async def implement_function(
    cursor: CursorCLI,
    func: dict,
    context: str,
    output_dir: Path,
    agent: Agent,
):
    """实现单个函数"""

    # 1. 构造 Cursor CLI 任务描述
    prompt = f"""请实现以下函数：

函数名：{func['name']}
描述：{func['description']}

实现要求：
- 使用 Python
- 遵循现有代码风格
- 添加必要的类型注解
- 添加 docstring
- 只生成函数代码，不要包含测试代码

上下文信息：
{context}
"""

    # 2. 定义进度回调
    async def on_progress(progress: CursorProgress):
        # 回调进度到主智能体
        await report_progress(
            agent=agent,
            func_name=func['name'],
            status="running",
            tool_type=progress.tool_events[-1].tool_type if progress.tool_events else None,
            total_chars=progress.total_chars,
        )

    # 3. 调用 Cursor CLI（流式输出）
    try:
        result = await cursor.agent_stream(prompt, on_progress)
    except CursorTimeoutError as e:
        await report_error(agent, func['name'], str(e))
        return

    # 4. 处理结果
    if not result.success:
        await report_error(agent, func['name'], result.stderr)
        await update_manifest_item(output_dir, func['name'], "failed", error=result.stderr)
        return

    # 5. 提取代码并写入文件
    code = result.get_code()
    output_file = output_dir / "generated" / f"{func['name']}.py"
    await write_file(output_file, code)

    # 6. 回调完成进度
    await report_progress(
        agent=agent,
        func_name=func['name'],
        status="completed",
        output_file=str(output_file),
    )

    # 7. 更新产物清单
    await update_manifest_item(output_dir, func['name'], "completed", output_file=str(output_file))
```

### 3.2 产物管理

```
work/<task_id>/
├── artifacts/
│   ├── manifest.json      # 产物清单（必须）
│   └── diff/              # 代码差异（可选）
├── generated/              # 生成的代码
│   ├── auth.py
│   ├── user.py
│   └── order.py
├── logs/                  # 执行日志
│   └── cursor_20260101_120000.log
└── context/               # 上下文文档
    └── scheme_doc.md
```

#### manifest.json 结构

```json
{
  "task_id": "task-001",
  "created_at": "2026-01-01T12:00:00Z",
  "status": "in_progress",
  "functions": [
    {
      "name": "authenticate_user",
      "status": "completed",
      "output_file": "generated/authenticate_user.py",
      "completed_at": "2026-01-01T12:05:00Z",
      "error": null
    },
    {
      "name": "create_session",
      "status": "failed",
      "output_file": null,
      "completed_at": null,
      "error": "Cursor API quota exceeded"
    }
  ],
  "summary": {
    "total": 10,
    "completed": 5,
    "failed": 1,
    "pending": 4
  }
}
```

#### 产物清单操作

```python
import json
from pathlib import Path
from datetime import datetime

async def init_artifacts_dir(output_dir: Path) -> None:
    """初始化产物目录"""
    artifacts_dir = output_dir / "artifacts"
    generated_dir = output_dir / "generated"
    logs_dir = output_dir / "logs"
    context_dir = output_dir / "context"

    for d in [artifacts_dir, generated_dir, logs_dir, context_dir]:
        d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "task_id": output_dir.name,
        "created_at": datetime.now().isoformat(),
        "status": "in_progress",
        "functions": [],
        "summary": {"total": 0, "completed": 0, "failed": 0, "pending": 0}
    }

    manifest_file = artifacts_dir / "manifest.json"
    await write_file(manifest_file, json.dumps(manifest, indent=2, ensure_ascii=False))


async def update_manifest_item(
    output_dir: Path,
    func_name: str,
    status: str,
    output_file: str | None = None,
    error: str | None = None,
) -> None:
    """更新产物清单中的函数项"""
    manifest_file = output_dir / "artifacts" / "manifest.json"
    manifest = json.loads(await read_file(manifest_file))

    # 查找或创建函数项
    func_item = None
    for item in manifest["functions"]:
        if item["name"] == func_name:
            func_item = item
            break

    if func_item is None:
        func_item = {"name": func_name}
        manifest["functions"].append(func_item)

    # 更新状态
    func_item["status"] = status
    if status == "completed":
        func_item["output_file"] = output_file
        func_item["completed_at"] = datetime.now().isoformat()
    elif status == "failed":
        func_item["error"] = error
        func_item["completed_at"] = datetime.now().isoformat()

    # 更新汇总
    manifest["summary"]["total"] = len(manifest["functions"])
    manifest["summary"]["completed"] = sum(
        1 for f in manifest["functions"] if f["status"] == "completed"
    )
    manifest["summary"]["failed"] = sum(
        1 for f in manifest["functions"] if f["status"] == "failed"
    )
    manifest["summary"]["pending"] = sum(
        1 for f in manifest["functions"] if f["status"] == "pending"
    )

    # 如果全部完成，更新整体状态
    if manifest["summary"]["pending"] == 0:
        manifest["status"] = "completed" if manifest["summary"]["failed"] == 0 else "completed_with_errors"

    await write_file(manifest_file, json.dumps(manifest, indent=2, ensure_ascii=False))


async def generate_artifacts_manifest(output_dir: Path) -> None:
    """生成最终产物清单摘要"""
    manifest_file = output_dir / "artifacts" / "manifest.json"
    manifest = json.loads(await read_file(manifest_file))

    # 添加完成时间
    manifest["finished_at"] = datetime.now().isoformat()

    await write_file(manifest_file, json.dumps(manifest, indent=2, ensure_ascii=False))
```

### 3.3 错误处理

```python
class CursorTimeoutError(Exception):
    """Cursor CLI 执行超时"""
    pass

class CursorQuotaError(Exception):
    """Cursor API 配额不足"""
    pass

class CursorWorktreeConflict(Exception):
    """工作树冲突"""
    pass

async def handle_cursor_error(error: Exception, func: dict, output_dir: Path) -> None:
    """处理 Cursor CLI 执行错误"""
    if isinstance(error, CursorTimeoutError):
        await update_manifest_item(output_dir, func['name'], "failed", error="执行超时")
    elif isinstance(error, CursorQuotaError):
        await update_manifest_item(output_dir, func['name'], "failed", error="API配额不足")
    elif isinstance(error, CursorWorktreeConflict):
        await update_manifest_item(output_dir, func['name'], "failed", error="工作树冲突")
    else:
        await update_manifest_item(output_dir, func['name'], "failed", error=str(error))
```

## Cursor CLI SKILL 定义

### 4.1 Cursor-CLI SKILL

```markdown
# skills/cursor-cli/SKILL.md

---
name: cursor-cli
description: 使用 Cursor CLI 进行代码开发
---

# Cursor CLI 技能

## 概述

Cursor CLI 是 Cursor 的命令行接口，支持流式输出和进度跟踪。本技能用于子智能体通过 subprocess 调用 Cursor CLI 执行代码生成任务。

## 核心能力

### 流式输出（推荐）

```bash
cursor agent -p "任务描述" --output-format stream-json --stream-partial-output
```

流式输出包含以下事件类型：

| 事件 | 说明 |
|------|------|
| `system/init` | 初始化信息（使用的模型等） |
| `assistant` | AI 生成的文本内容 |
| `tool_call/started` | 开始执行工具（writeFile、readFile、Bash 等） |
| `tool_call/completed` | 工具执行完成 |
| `result` | 最终结果，包含耗时统计 |

### 非交互模式

```bash
cursor agent -p "任务描述" --output-format text
```

一次性返回结果，不支持进度跟踪。

## 人类确认处理

Cursor CLI 在执行危险操作前会请求确认：

| 确认类型 | 提示示例 | 推荐处理 |
|----------|----------|----------|
| 命令执行 | "Run command? (y/n)" | 非交互模式默认 **拒绝** |
| 授权操作 | "Authorize git push?" | 非交互模式默认 **拒绝** |
| 计划审批 | `cursor/create_plan` | 非交互模式默认 **拒绝** |

### 处理策略

```python
auto_confirm = False  # 默认拒绝危险操作

# 允许的操作（白名单）
ALLOWED_COMMANDS = [
    "pip install",
    "python -m pytest",
    "python -m",
]

# 拒绝的操作（黑名单）
DENIED_COMMANDS = [
    "git push",
    "rm -rf",
    "sudo",
    "docker rm",
]
```

## 工作树隔离

每个子智能体使用独立的工作树目录：
- 路径格式：`~/.synapse/worktrees/{task_id}/`
- Cursor 自动在工作树内操作，不影响主代码库
- 任务完成后，代码需要手动审查并合并

## 产物结构

```
work/<task_id>/
├── artifacts/
│   └── manifest.json      # 产物清单（必须）
├── generated/              # 生成的代码
│   └── *.py
├── logs/                   # 执行日志
│   └── cursor_*.log
└── context/                # 上下文文档
    └── scheme_doc.md
```

### manifest.json 示例

```json
{
  "task_id": "task-001",
  "status": "completed",
  "functions": [
    {"name": "func1", "status": "completed", "output_file": "generated/func1.py"}
  ],
  "summary": {"total": 1, "completed": 1, "failed": 0}
}
```

## 注意事项

1. **进度跟踪**：使用 `--output-format stream-json` 实时跟踪执行进度
2. **超时设置**：建议 300 秒，避免长时间无响应
3. **危险操作**：非交互模式下默认拒绝 git push、rm -rf 等
4. **产物管理**：每次函数完成后更新 `manifest.json`
5. **错误恢复**：遇到 API 配额错误可等待后重试
```

## 任务执行流程

### 主智能体任务分发（单实例）

```python
async def orchestrate_development_task(
    task: str,
    dev_profile: str,  # 单个子智能体
):
    """主智能体任务编排（单子智能体顺序执行）"""

    # 1. 分析任务，拆分为函数级
    sub_tasks = await analyze_and_split_task(task)
    # sub_tasks = [{"doc": "函数方案.md", "output_dir": "...", "functions": [...]}]

    # 2. 提交执行计划
    work_plan_id = await submit_meeting_work_plan([
        {
            "agent_id": dev_profile,
            "task": f"实现 {len(sub_tasks)} 个模块的代码",
            "reason": "代码开发",
            "plan_item_id": "item-001"
        }
    ])

    # 3. 创建工作树目录
    worktree_path = f"~/.synapse/worktrees/{work_plan_id}"
    output_dir = f"~/.synapse/work/{work_plan_id}"
    os.makedirs(worktree_path, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 4. 分发任务给单个子智能体
    await delegate_to_agent(
        agent_id=dev_profile,
        message=f"""请执行以下代码开发任务：

1. 阅读方案文档：{sub_tasks[0]['doc']}
2. 使用 Cursor CLI（流式输出）生成代码
3. 产出代码到：{output_dir}
4. 更新产物清单：{output_dir}/artifacts/manifest.json

工作树目录：{worktree_path}

任务列表：
{chr(10).join(f"- {t['name']}: {t['doc']}" for t in sub_tasks)}
""",
        reason=f"任务计划 ID: {work_plan_id}"
    )

    # 5. 等待子任务完成
    result = await wait_for_subtask_result(work_plan_id)
    return aggregate_artifacts(result)
```

## 方案对比

| 项目 | subprocess 模式 | PSMUX 模式 |
|------|-----------------|------------|
| 依赖 | 仅需 cursor.exe | 需 psmux.exe + cursor.exe |
| 子智能体 | 单实例 | 多实例并发 |
| 进度跟踪 | 流式输出（stream-json） | 实时观察终端 |
| 交互能力 | 非交互，默认拒绝确认 | 真正交互式 |
| 实现复杂度 | 中等 | 复杂 |
| 适用场景 | 函数级代码生成 | 复杂多轮交互 |

## 相关文档

- [PSMUX 多智能体研发方案](./psmux-multi-agent-development-scheme.md)
- [研发会议室实现方案](./synapse/多智能体研发会议室实现方案.md)
- [Cursor CLI 官方文档](https://cursor.com/docs/cli/overview)
