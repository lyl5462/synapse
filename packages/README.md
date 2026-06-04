# packages/

| 目录 | 上游 | 说明 |
|------|------|------|
| `synapse-plugin-ui-sdk/` | `openakita/packages/plugin-ui-sdk` | Plugin 2.0 前端 Bridge（`@synapse/plugin-ui-sdk`） |

构建：

```bash
cd packages/synapse-plugin-ui-sdk
npm install
npm run build
```

协议字段 `__akita_bridge` 与宿主 `PluginBridgeHost` 一致；预构建插件 UI 仍可使用内嵌 `bootstrap.js` 与 `window.OpenAkita`，不必依赖本 npm 包。

再同步：`python scripts/sync_upstream_sdk.py`（会同时更新仓库根的 `synapse-plugin-sdk/`）。
