# 拓扑关联检索脚本 (Relation Query)

## 功能说明
调用接口的 `relation` 类型，基于指定的中心节点（如混合检索得到的历史工单 UUID）进行图谱拓扑层级展开，用于挖掘历史工单关联的具体功能模块和代码文件。

## 脚本路径
`scripts/relation_query.py`

## 使用方式
```bash
python scripts/relation_query.py --server_url 'http://...' --prod 'xxx' --query 'yyy' --depth 1
```

## 参数说明
*   `--server_url` (必填)：图谱接口的服务器地址（由技能参数 `SERVER_URL` 透传）。
*   `--query` (必填)：作为查询起点的目标节点 ID 或 UUID。
*   `--prod` (可选)：产品标识。
*   `--depth` (可选参数)：拓扑图谱展开的深度，默认为 1。

## 使用建议
*   在拿到混合检索返回的工单UUID后，调用本脚本可以将该工单的关联对象（包括对应的研发单、影响的底层模块、对应的代码文件）在图谱中进行拓扑展开。
*   将展开得到的 `impact` 信息与当前输入的 `IMPACT` 对比，可以过滤掉表面相似但底层改动毫无关联的“伪相似工单”。