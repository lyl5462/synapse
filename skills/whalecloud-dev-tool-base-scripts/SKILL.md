---
name: whalecloud-dev-tool-base-scripts
description: "研发工具共享脚本包：SynapseService / GitNexus / 图谱工单检索等系统交互的可执行脚本与说明，供 whalecloud-dev-tool-* 业务技能引用。Examples: gnx-tools materialize、get_repo_info、get_doc、历史工单 hybrid/relation/cypher 查询。"
label: 研发工具共享脚本
---

> **系统约束**：本技能由 Synapse / Setup Center **强制启用**（不可从 `data/skills.json` 的 `external_allowlist` 中移除），且**不可卸载**。

# whalecloud-dev-tool-base-scripts（共享脚本）

本技能**仅提供**与外部系统交互的脚本与参考说明；业务流程由其它 `whalecloud-dev-tool-*` 技能定义。

## 调用方式（业务技能必读）

**禁止**在业务技能 Parameters 中要求用户传入脚本根路径。一律通过 Synapse 工具执行：

```text
run_skill_script(
  skill_name="whalecloud-dev-tool-base-scripts",
  script_name="<脚本文件名>",
  args=["参数1", "参数2", ...]
)
```

- `.py` 脚本：平台自动选用 Python 解释器
- `.js` 脚本（如 `gnx-tools.js`）：平台自动用 `node` 执行；子命令写在 `args` 最前面（如 `["materialize", "--url", ...]`）

需要脚本列表或参数说明时：`get_skill_info("whalecloud-dev-tool-base-scripts")`。

## `scripts/` 清单

| 脚本 | 用途 |
|------|------|
| `gnx-tools.js` | GitNexus：materialize / read / grep / cypher / search / overview / explore / impact |
| `fetch-arch-data.js` | 架构 JSON（REST + MCP） |
| `detect-project-kind.js` | 工程类型判定 |
| `get_repo_info.py` | 产品关联仓库列表 |
| `get_doc.py` | 产品文档下载（会议室场景优先读工单 `doc/`，少用本脚本） |
| `hybrid_query.py` | 历史工单混合检索 |
| `relation_query.py` | 历史工单拓扑关联 |
| `cypher_query.py` | 历史工单 Cypher 查询 |

## `references/` 说明文档

| 文件 | 对应脚本 |
|------|----------|
| [references/gnx-tools.md](references/gnx-tools.md) | `gnx-tools.js` / `detect-project-kind.js` |
| [references/get_repo_info.md](references/get_repo_info.md) | `get_repo_info.py` |
| [references/get_doc.md](references/get_doc.md) | `get_doc.py` |
| [references/hybrid_query.md](references/hybrid_query.md) | `hybrid_query.py` |
| [references/relation_query.md](references/relation_query.md) | `relation_query.py` |
| [references/cypher_query.md](references/cypher_query.md) | `cypher_query.py` |

> 业务技能目录下**没有**上述脚本的副本；勿写 `skills/...` 相对路径或让用户手填绝对路径。
