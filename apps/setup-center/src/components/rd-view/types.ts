export type TimeRange = 'day' | 'week' | 'month' | 'quarter' | 'year';

/** 核心KPI指标项 */
export interface KpiItem {
  key: string;
  title: string;
  value: string;
  trend: number;
  trendLabel: string;
  isPositive: boolean;
  isWarning?: boolean;
}

/** 工单提效明细（同一工单：AI耗时 vs 人工耗时二选一对比） */
export interface OrderEfficiencyDetailItem {
  id: string;
  title: string;
  /** 走 AI 路径的实际耗时 */
  aiHours: number;
  /** 同一条工单改人工做的参考耗时 */
  manualHours: number;
}

export interface OrderEfficiencyDetailView extends OrderEfficiencyDetailItem {
  efficiencyGain: number;
}

/** 人员智能助手覆盖率明细 */
export interface PersonAiCoverageItem {
  name: string;
  totalOrders: number;
  aiOrders: number;
}

export interface PersonAiCoverageView extends PersonAiCoverageItem {
  manualOrders: number;
  coverageRate: number;
}

/** 需求工单覆盖明细 */
export interface OrderCoverageDetailItem {
  id: string;
  title: string;
  priority: '高' | '中' | '低';
  /** 是否被智能助手覆盖 */
  covered: boolean;
  model?: string;
  tokens?: number;
  hours?: number;
}

/** 工单处理满意度明细 */
export interface OrderSatisfactionDetailItem {
  id: string;
  title: string;
  priority: '高' | '中' | '低';
  /** true=点赞，false=点踩 */
  liked: boolean;
}

/** 模型 Token 消耗明细 */
export interface ModelTokenUsageItem {
  model: string;
  /** 定价：元/千Token */
  unitPrice: number;
  /** 使用量（Token 数） */
  tokens: number;
}

export interface ModelTokenUsageView extends ModelTokenUsageItem {
  cost: number;
}

/** 研发助手产出 - 按产品 */
export interface ProductAssistantOutputItem {
  productName: string;
  docCount: number;
  codeCount: number;
}

/** 人员工作量 - 水平堆叠柱状图 */
export interface PersonDemandItem {
  name: string;
  completed: number;
  inProgress: number;
  pending: number;
}

/** 需求状态分布 - 环形图 */
export interface DemandStatusItem {
  name: string;
  value: number;
  color: string;
}

/** 人员 Token 消耗与耗时 */
export interface PersonCostUsageItem {
  name: string;
  avgHours: number;
  avgUsage: number;
}

/** 需求状态 */
export type RequirementStatus = 'pending' | 'inProgress' | 'completed';

/** SOP 节点明细 */
export interface SopNodeDetail {
  key: string;
  name: string;
  status: RequirementStatus;
  hours: number;
  description: string;
}

/** 人员被分配的需求 */
export interface PersonRequirement {
  id: string;
  title: string;
  status: RequirementStatus;
  assignee: string;
  startDay: number;
  duration: number;
  priority: '高' | '中' | '低';
  description: string;
  createdAt: string;
  plannedEnd: string;
  sopNodes: SopNodeDetail[];
}

/** SOP 节点运行状态 */
export type SopNodeRunStatus = 'running' | 'abnormal' | 'manual' | 'completed' | 'pending';

/** 智能体对话 */
export interface SopDialogueMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  time: string;
}

/** SOP 节点产出物 */
export interface SopNodeOutput {
  type: 'document' | 'code' | 'artifact';
  label: string;
}

/** 工单 SOP 节点（含对话与消耗） */
export interface WorkOrderSopNode {
  key: string;
  name: string;
  status: RequirementStatus;
  runStatus: SopNodeRunStatus;
  hours: number;
  tokens: number;
  model: string;
  description: string;
  dialogues: SopDialogueMessage[];
  outputs: SopNodeOutput[];
}

/** 工单评论 */
export interface WorkOrderComment {
  author: string;
  time: string;
  content: string;
}

/** 工作内容 - 工单 */
export interface WorkOrderTicket {
  id: string;
  title: string;
  status: RequirementStatus;
  assignee: string;
  priority: '高' | '中' | '低';
  summary: string;
  content: string;
  createdAt: string;
  updatedAt: string;
  plannedEnd: string;
  comments: WorkOrderComment[];
  sopNodes: WorkOrderSopNode[];
}

/** 人员维度明细（mock 内部使用） */
export interface PersonDetail {
  name: string;
  totalOrders: number;
  completed: number;
  inProgress: number;
  avgHoursPerOrder: number;
  aiEfficiencyRate: number;
  tokenConsumed: number;
  personalCost: number;
  satisfaction: number;
}

/** 当前登录用户（mock） */
export const CURRENT_USER_NAME = '李四';

/** 团队成员颜色映射 */
export const PERSON_COLORS: Record<string, string> = {
  '张三': '#165DFF',
  '李四': '#00B42A',
  '王五': '#FF7D00',
  '赵六': '#722ED1',
  '钱七': '#13C2C2',
};