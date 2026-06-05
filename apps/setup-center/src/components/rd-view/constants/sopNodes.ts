import type { RequirementStatus, SopNodeDetail } from '@rd-view/types';

/** SOP 节点定义（顺序固定：分析 → 设计 → 环境 → 开发 → 走查） */
export const SOP_NODES = [
  {
    key: 'analysis',
    label: '分析',
    color: '#165DFF',
    hoursField: 'analysisHours',
    tokensField: 'analysisTokens',
    defaultHours: 4,
    description: '需求分析、范围确认与方案梳理',
  },
  {
    key: 'design',
    label: '设计',
    color: '#4080FF',
    hoursField: 'designHours',
    tokensField: 'designTokens',
    defaultHours: 6,
    description: '技术设计与接口方案输出',
  },
  {
    key: 'environment',
    label: '环境',
    color: '#13C2C2',
    hoursField: 'environmentHours',
    tokensField: 'environmentTokens',
    defaultHours: 3,
    description: '开发测试环境搭建与配置',
  },
  {
    key: 'development',
    label: '开发',
    color: '#FF7D00',
    hoursField: 'developmentHours',
    tokensField: 'developmentTokens',
    defaultHours: 12,
    description: '核心功能开发、自测与代码提交',
  },
  {
    key: 'review',
    label: '走查',
    color: '#722ED1',
    hoursField: 'reviewHours',
    tokensField: 'reviewTokens',
    defaultHours: 4,
    description: '代码走查、联调验证与缺陷修复',
  },
] as const;

export function buildSopNodeStatuses(status: RequirementStatus): RequirementStatus[] {
  if (status === 'completed') {
    return ['completed', 'completed', 'completed', 'completed', 'completed'];
  }
  if (status === 'inProgress') {
    return ['completed', 'completed', 'completed', 'inProgress', 'pending'];
  }
  return ['pending', 'pending', 'pending', 'pending', 'pending'];
}

export function buildRequirementSopNodes(status: RequirementStatus): SopNodeDetail[] {
  const nodeStatuses = buildSopNodeStatuses(status);
  return SOP_NODES.map((node, index) => ({
    key: node.key,
    name: node.label,
    status: nodeStatuses[index],
    hours: node.defaultHours,
    description: node.description,
  }));
}
