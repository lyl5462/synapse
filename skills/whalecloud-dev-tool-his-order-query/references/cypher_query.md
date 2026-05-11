# 图谱Cypher检索脚本 (Cypher Query)

## 功能说明
调用接口的 `cypher` 类型，执行原生 Cypher 图数据库查询语句，用于复杂多条件的交叉过滤（例如：直接检索“既包含特性A，又在拓扑链路上影响模块B的工单”）。

## 脚本路径
`scripts/cypher_query.py`

## 使用方式
```bash
python scripts/cypher_query.py --server_url 'http://...' --prod 'xxx' --query 'yyy' --parameters '{"key":"value"}'
```

## 参数说明
*   `--server_url` (必填)：图谱接口的服务器地址（由技能参数 `SERVER_URL` 透传）。
*   `--query` (必填)：需要执行的完整 Cypher 查询语句。
*   `--prod` (可选)：产品标识。
*   `--parameters` (可选参数)：传递给 Cypher 语句的参数变量，需为合法的 JSON 字符串格式。

## 图谱数据结构指南（大模型编写 Cypher 必读）
根据底层录入逻辑，历史工单的数据在图数据库中的组织方式如下：

### 1. 核心节点 (Nodes)
*   `Demand` (需求单)：具有属性 `需求单号` (demand_no), `需求单名称`, `需求描述`, `需求状态`, `需求影响`, `需求类型`, `需求优先级`, `需求关联应用模块` 等。
*   `Task` (研发单)：具有属性 `研发单号` (task_no), `研发单名称`, `任务描述`, `任务状态`, `仓库分支`, `模块版本` 等。
*   `Feature` (功能特性)：具有属性 `name` (功能名称)。
*   `DemandImpact` (需求影响)：具有属性 `name` (影响类型)。
*   `Designer` / `Developer` (人员)：具有属性 `姓名`, `员工编号`。

### 2. 核心关系 (Edges)
*   `(:Demand)-[:INVOLVES_FUNCTION]->(:Feature)`：需求涉及某功能特性。
*   `(:Feature)-[:APPLIED_IN_REQ]->(:Demand)`：功能特性被需求应用。
*   `(:Demand)-[:CAUSES_IMPACT]->(:DemandImpact)`：需求导致某种影响。
*   `(:Demand)-[:SPLIT_INTO]->(:Task)`：需求被拆分为研发单。
*   `(:Demand)-[:DESIGNED_BY]->(:Designer)`：需求由某设计人员设计。
*   `(:Task)-[:DEVELOPED_BY]->(:Developer)`：研发单由某开发人员开发。

### 3. Cypher 编写建议
当执行 Cypher 查询时，请务必利用上述节点标签 (Labels) 和关系类型 (Types) 来构建匹配模式 (MATCH)。
例如，要查询影响了特定功能且由某个开发者开发的工单，可以通过如下方式进行图谱遍历：
```cypher
MATCH (:Feature)<-[:INVOLVES_FUNCTION]-(d:Demand)-[:SPLIT_INTO]->(t:Task)-[:DEVELOPED_BY]->(dev:Developer)
RETURN d.demand_no
```