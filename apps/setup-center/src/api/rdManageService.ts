import { fetchSynapseJson } from "./rdUnifiedService";

export interface DemandInfo {
  "需求单号": string;
  "需求单名称": string;
  "需求描述": string;
  "需求开始时间": string;
  "需求结束时间": string;
  "需求工作量": number;
  "需求状态": string;
  "需求影响": string;
  "需求类型": string;
  "需求优先级": string;
  "需求关联应用模块": string;
  "设计人员": string;
  "当前sop节点": string;
}

export interface DemandsResponse {
  "预备工单": DemandInfo[];
  "可处理工单": DemandInfo[];
  "在途工单": DemandInfo[];
  "近三月完成工单": DemandInfo[];
}

export interface DemandNodeInfo {
  node_name: string;
  node_status: string;
  time_cost: string;
  token_cost: number;
  role: string;
  model: string;
  tools: string[];
  agent: string;
  session_info: string;
  output_artifacts: any;
}

export interface DemandNodesResponse {
  nodes: DemandNodeInfo[];
}

export async function fetchRdManageDemands(synapseApiBase: string): Promise<DemandsResponse> {
  return fetchSynapseJson<DemandsResponse>(synapseApiBase, "/api/dev/iwhalecloud/rd-manage/demands");
}

export async function fetchRdManageDemandNodes(synapseApiBase: string, demandNo: string): Promise<DemandNodesResponse> {
  return fetchSynapseJson<DemandNodesResponse>(synapseApiBase, `/api/dev/iwhalecloud/rd-manage/demands/${demandNo}/nodes`);
}
