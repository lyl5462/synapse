# Synapse 内置插件（来自上游 openakita/plugins）

本目录为 **可选一等公民插件源码**，已从上游同步并完成 Synapse 品牌化（`synapse.plugins.api`、`requires.synapse` 等）。

## 安装到运行时

主程序只从 **`{项目根}/data/plugins/`** 加载插件，不会直接读取仓库里的 `plugins/`。

**开发模式（推荐）**：在 Setup Center → 插件管理，用「从本地路径安装」指向本目录下的子文件夹，例如：

```text
D:\github\openakita_jyhk\plugins\tongyi-image
```

或复制 / symlink 到 `data/plugins/<plugin-id>/` 后重启后端。

## 插件列表

| ID | 说明 |
|----|------|
| tongyi-image | 通义生图 |
| seedance-video | Seedance 视频 |
| ppt-maker | PPT 制作 |
| manga-studio | 漫画工作室 |
| media-strategy | 媒体策略 |
| media-post | 媒体发布 |
| omni-post | 全渠道发帖 |
| fin-pulse | 财经脉冲 |
| happyhorse-video | HappyHorse 视频 |
| avatar-studio | 数字人 |
| clip-sense | 剪辑感知 |
| footage-gate | 素材门 |
| subtitle-craft | 字幕工坊 |
| word-maker / excel-maker | 文档生成 |
| ecommerce-image | 电商图 |
| idea-research | 选题研究 |

## 依赖

各插件可能有独立 `requirements.txt`；安装时由插件管理器或插件设置页拉取 pip 依赖。使用 DashScope / 中转站等能力的插件需在 LLM 配置中配置 `relay_endpoints`（见 `synapse.relay`）。

## UI 协议

预构建的 `ui/dist/` 仍使用 **`window.OpenAkita`** 与 `openakita:*` 事件名，与 Setup Center 内建 Plugin Bridge 协议一致，请勿在 dist 资源中改名。

## 再同步上游

```powershell
# 插件
robocopy D:\github\openakita\plugins D:\github\openakita_jyhk\plugins /E
python D:\github\openakita_jyhk\scripts\brand_plugins_tree.py

# Python SDK + 前端 UI SDK（目录 synapse-plugin-sdk、packages/synapse-plugin-ui-sdk）
python D:\github\openakita_jyhk\scripts\sync_upstream_sdk.py
```

同步后检查 `DIFF.md` 中是否有针对单个插件的本地化改造，避免覆盖。
