# 业务技能接入说明

供**调用方**业务技能编写依赖章节时参考；本技能正文不列举具体调用方名称。

## 推荐写法

调用方 `SKILL.md` 中增加 **「代码访问（依赖技能）」** 节，写明：

1. 触发条件（对齐 `whalecloud-dev-tool-code-access` 的「何时加载」）
2. 执行 gnx 相关命令前，**必须先阅读** 该技能 `SKILL.md` 全文
3. 参数映射：将工作区临时目录映射为 `CACHE_ROOT`（例如 `{WORK_TMP}/.gnx-cache`）

## 参数透传

| 调用方常见参数 | 代码访问技能 |
|----------------|--------------|
| `GITNEXUS_URL` | `GITNEXUS_URL` |
| `SYNAPSE_URL` | `SYNAPSE_URL` |
| `PROD` | `PROD` |
| `GNX_REPO` | `GNX_REPO` |
| 工作临时目录 | `CACHE_ROOT`（调用方自定路径，指向 `.gnx-cache` 根） |

## 职责切分

| 职责 | 调用方业务技能 | 代码访问技能 |
|------|----------------|--------------|
| 产品文档等非代码资料 | ✓（若需要） | — |
| 仓库列表 / materialize / 检索 / 读文件 | 触发加载 | ✓ |
| 证据索引写入交付物 | ✓ | 定义格式与规则（C2） |
| 清理 `CACHE_ROOT` | 可选，由调用方在会话结束时执行 | — |

## 命令细节

`gnx-tools.js`、`get_repo_info.py` 的完整命令与错误处理以 **`whalecloud-dev-tool-code-access/SKILL.md`** 为准，调用方文档中仅保留触发条件与参数映射，避免重复维护两套命令表。
