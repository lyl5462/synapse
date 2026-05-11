# 混合检索脚本 (Hybrid Query)

## 功能说明
调用接口的 `hybrid` 类型，基于自然语言或关键字进行向量与文本混合检索，用于初步在海量历史数据中发现与当前需求语义高度相似的工单节点。

## 脚本路径
`scripts/hybrid_query.py`

## 使用方式
```bash
python scripts/hybrid_query.py --server_url 'http://...' --prod 'xxx' --query 'yyy' --limit 10
```

## 参数说明
*   `--server_url` (必填)：图谱接口的服务器地址（由技能参数 `SERVER_URL` 透传）。
*   `--query` (必填)：用于检索的文本或关键字（建议从 `DEMAND_DESC` 中提取核心句式传入）。
*   `--prod` (可选)：产品标识（例如：'CRM'）。
*   `--limit` (可选参数)：返回的最大相似节点数量，默认为 10。

## 使用建议
*   当用户输入较长的一段需求描述（`DEMAND_DESC`）时，直接将总结后的需求文本作为 `--query` 参数传入，能够利用向量相似度迅速找回过去处理过的相似需求单。
*   主要用于获取候选工单池（UUID列表）。