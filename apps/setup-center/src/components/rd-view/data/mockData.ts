import type {
  KpiItem,
  DemandStatusItem,
  PersonDetail,
  PersonRequirement,
  PersonDemandItem,
  RequirementStatus,
  PersonCostUsageItem,
  OrderEfficiencyDetailItem,
  PersonAiCoverageItem,
  OrderCoverageDetailItem,
  OrderSatisfactionDetailItem,
  ModelTokenUsageItem,
  TimeRange,
  ProductAssistantOutputItem,
} from '@rd-view/types';
import { buildRequirementSopNodes } from '@rd-view/constants/sopNodes';
import { PERSON_WORKLOAD_DISPLAY_LIMIT } from '@rd-view/constants/chartLayout';
import { calcAverageOrderEfficiencyGain } from '@rd-view/utils/orderEfficiency';
import { calcAverageAiCoverageRate } from '@rd-view/utils/aiCoverage';
import { calcAverageOrderCoverageRate } from '@rd-view/utils/orderCoverage';
import { calcOrderSatisfactionScore, formatOrderSatisfactionScore } from '@rd-view/utils/orderSatisfaction';
import { calcTotalTokens, formatTotalTokens } from '@rd-view/utils/tokenConsumption';
import { buildWorkOrderTickets } from '@rd-view/data/buildWorkOrderTickets';

export const orderEfficiencyDetailData: OrderEfficiencyDetailItem[] = [
  { id: 'REQ-1001', title: '需求分析模块优化', aiHours: 1.2, manualHours: 2.5 },
  { id: 'REQ-1002', title: '代码审查工具接入', aiHours: 1.8, manualHours: 3.0 },
  { id: 'REQ-1003', title: '单元测试补充', aiHours: 1.8, manualHours: 2.4 },
  { id: 'REQ-1004', title: '接口联调测试', aiHours: 1.5, manualHours: 2.2 },
  { id: 'REQ-1005', title: '性能优化专项', aiHours: 2.0, manualHours: 4.0 },
  { id: 'REQ-1006', title: 'API接口开发', aiHours: 2.8, manualHours: 3.5 },
  { id: 'REQ-1007', title: '前端页面重构', aiHours: 2.8, manualHours: 3.8 },
  { id: 'REQ-1008', title: '数据库索引优化', aiHours: 1.0, manualHours: 1.5 },
  { id: 'REQ-1009', title: '缓存策略升级', aiHours: 1.6, manualHours: 2.4 },
  { id: 'REQ-1010', title: '日志监控接入', aiHours: 2.2, manualHours: 3.2 },
  { id: 'REQ-1011', title: '权限模块重构', aiHours: 1.4, manualHours: 2.6 },
  { id: 'REQ-1012', title: '消息队列改造', aiHours: 0.8, manualHours: 1.2 },
  { id: 'REQ-1013', title: '文档编写整理', aiHours: 1.0, manualHours: 1.8 },
  { id: 'REQ-1014', title: '集成测试验证', aiHours: 2.0, manualHours: 2.8 },
  { id: 'REQ-1015', title: '样式调整适配', aiHours: 0.8, manualHours: 1.2 },
];

const orderEfficiencyGainAvg = calcAverageOrderEfficiencyGain(orderEfficiencyDetailData);

export const orderCoverageDetailData: OrderCoverageDetailItem[] = [
  { id: 'REQ-2001', title: '需求分析模块优化', priority: '高', covered: true, model: 'GPT-4o', tokens: 12500, hours: 1.2 },
  { id: 'REQ-2002', title: '代码审查工具接入', priority: '高', covered: true, model: 'Claude-3.5', tokens: 9800, hours: 1.8 },
  { id: 'REQ-2003', title: '单元测试补充', priority: '中', covered: false },
  { id: 'REQ-2004', title: '接口联调测试', priority: '中', covered: true, model: 'GPT-4o', tokens: 6200, hours: 1.5 },
  { id: 'REQ-2005', title: '性能优化专项', priority: '高', covered: true, model: 'DeepSeek-V3', tokens: 18600, hours: 2.0 },
  { id: 'REQ-2006', title: 'API接口开发', priority: '中', covered: false },
  { id: 'REQ-2007', title: '前端页面重构', priority: '低', covered: true, model: 'GPT-4o-mini', tokens: 8400, hours: 2.8 },
  { id: 'REQ-2008', title: '数据库索引优化', priority: '低', covered: false },
  { id: 'REQ-2009', title: '缓存策略升级', priority: '中', covered: true, model: 'Claude-3.5', tokens: 5100, hours: 1.6 },
  { id: 'REQ-2010', title: '日志监控接入', priority: '低', covered: false },
  { id: 'REQ-2011', title: '权限模块重构', priority: '高', covered: true, model: 'GPT-4o', tokens: 11200, hours: 1.4 },
  { id: 'REQ-2012', title: '消息队列改造', priority: '中', covered: false },
  { id: 'REQ-2013', title: '文档编写整理', priority: '低', covered: true, model: 'GPT-4o-mini', tokens: 3200, hours: 1.0 },
  { id: 'REQ-2014', title: '集成测试验证', priority: '中', covered: true, model: 'DeepSeek-V3', tokens: 7600, hours: 2.0 },
  { id: 'REQ-2015', title: '样式调整适配', priority: '低', covered: false },
];

const orderCoverageAvg = calcAverageOrderCoverageRate(orderCoverageDetailData);

export const orderSatisfactionDetailData: OrderSatisfactionDetailItem[] = [
  { id: 'REQ-3001', title: '需求分析模块优化', priority: '高', liked: true },
  { id: 'REQ-3002', title: '代码审查工具接入', priority: '高', liked: true },
  { id: 'REQ-3003', title: '单元测试补充', priority: '中', liked: false },
  { id: 'REQ-3004', title: '接口联调测试', priority: '中', liked: true },
  { id: 'REQ-3005', title: '性能优化专项', priority: '高', liked: true },
  { id: 'REQ-3006', title: 'API接口开发', priority: '中', liked: true },
  { id: 'REQ-3007', title: '前端页面重构', priority: '低', liked: true },
  { id: 'REQ-3008', title: '数据库索引优化', priority: '低', liked: false },
  { id: 'REQ-3009', title: '缓存策略升级', priority: '中', liked: true },
  { id: 'REQ-3010', title: '日志监控接入', priority: '低', liked: true },
  { id: 'REQ-3011', title: '权限模块重构', priority: '高', liked: true },
  { id: 'REQ-3012', title: '消息队列改造', priority: '中', liked: true },
  { id: 'REQ-3013', title: '文档编写整理', priority: '低', liked: true },
  { id: 'REQ-3014', title: '集成测试验证', priority: '中', liked: true },
  { id: 'REQ-3015', title: '样式调整适配', priority: '低', liked: false },
];

const orderSatisfactionScore = calcOrderSatisfactionScore(orderSatisfactionDetailData);

export const modelTokenUsageData: ModelTokenUsageItem[] = [
  { model: 'GPT-4o', unitPrice: 0.21, tokens: 45200 },
  { model: 'Claude-3.5', unitPrice: 0.18, tokens: 31800 },
  { model: 'DeepSeek-V3', unitPrice: 0.08, tokens: 28600 },
  { model: 'GPT-4o-mini', unitPrice: 0.05, tokens: 19400 },
];

const totalTokenConsumed = calcTotalTokens(modelTokenUsageData);

const PRODUCT_OUTPUT_BASE: ProductAssistantOutputItem[] = [
  { productName: 'OpenAkita研发平台', docCount: 28, codeCount: 16 },
  { productName: '团队AI总视图', docCount: 18, codeCount: 22 },
  { productName: '智能助手 SDK', docCount: 12, codeCount: 34 },
  { productName: '运维监控中心', docCount: 9, codeCount: 11 },
  { productName: '数据中台', docCount: 15, codeCount: 8 },
];

const TIME_RANGE_OUTPUT_SCALE: Record<TimeRange, number> = {
  day: 0.18,
  week: 1,
  month: 3.8,
  quarter: 10.5,
  year: 38,
};

function scaleProductOutput(items: ProductAssistantOutputItem[], scale: number): ProductAssistantOutputItem[] {
  return items.map((item) => ({
    ...item,
    docCount: Math.max(1, Math.round(item.docCount * scale)),
    codeCount: Math.max(1, Math.round(item.codeCount * scale)),
  }));
}

const productAssistantOutputByTimeRange: Record<TimeRange, ProductAssistantOutputItem[]> = {
  day: scaleProductOutput(PRODUCT_OUTPUT_BASE, TIME_RANGE_OUTPUT_SCALE.day),
  week: scaleProductOutput(PRODUCT_OUTPUT_BASE, TIME_RANGE_OUTPUT_SCALE.week),
  month: scaleProductOutput(PRODUCT_OUTPUT_BASE, TIME_RANGE_OUTPUT_SCALE.month),
  quarter: scaleProductOutput(PRODUCT_OUTPUT_BASE, TIME_RANGE_OUTPUT_SCALE.quarter),
  year: scaleProductOutput(PRODUCT_OUTPUT_BASE, TIME_RANGE_OUTPUT_SCALE.year),
};

export function getProductAssistantOutputByTimeRange(timeRange: TimeRange): ProductAssistantOutputItem[] {
  return productAssistantOutputByTimeRange[timeRange];
}

// ==================== KPI ====================
export const kpiData: KpiItem[] = [
  { key: 'efficiencyGain', title: '工单处理提效程度', value: `${orderEfficiencyGainAvg}%`, trend: 5, trendLabel: '本周环比', isPositive: true },
  { key: 'aiCoverage', title: '智能研发覆盖率', value: '0%', trend: 8, trendLabel: '本周环比', isPositive: true },
  { key: 'orderCoverage', title: '需求工单覆盖率', value: `${orderCoverageAvg}%`, trend: 3, trendLabel: '本周环比', isPositive: true },
  { key: 'satisfaction', title: '工单处理质量', value: formatOrderSatisfactionScore(orderSatisfactionScore), trend: 0.2, trendLabel: '本周环比', isPositive: true },
  { key: 'tokenConsumed', title: 'Token总消耗', value: formatTotalTokens(totalTokenConsumed), trend: -2, trendLabel: '本周环比', isPositive: false },
  { key: 'assistantOutput', title: '研发助手产出', value: '', trend: 12, trendLabel: '本周环比', isPositive: true },
];

export const demandStatusData: DemandStatusItem[] = [
  { name: '已完成', value: 120, color: '#165DFF' },
  { name: '进行中', value: 55, color: '#00B42A' },
  { name: '待开始', value: 25, color: '#FF7D00' },
];

const TEAM_NAMES = [
  '张三', '李四', '王五', '赵六', '钱七', '孙八', '周九', '吴十',
  '郑十一', '冯十二', '陈十三', '褚十四', '卫十五', '蒋十六', '沈十七', '韩十八',
  '杨十九', '朱二十',
];

const REQ_TITLES = [
  '需求分析模块优化', '代码审查工具接入', '单元测试补充', '接口联调测试', '性能优化专项',
  '文档编写整理', 'API接口开发', '集成测试验证', '前端页面重构', '样式调整适配',
  '数据库索引优化', '缓存策略升级', '日志监控接入', '权限模块重构', '消息队列改造',
];

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function buildSopNodes(status: RequirementStatus) {
  return buildRequirementSopNodes(status);
}

function buildRequirements(): PersonRequirement[] {
  const list: PersonRequirement[] = [];
  let reqIndex = 1001;

  TEAM_NAMES.forEach((name, personIdx) => {
    const count = 3 + (personIdx % 4);
    for (let i = 0; i < count; i += 1) {
      const statusCycle: RequirementStatus[] = ['completed', 'inProgress', 'pending'];
      const status = statusCycle[(personIdx + i) % 3];
      const startDay = (personIdx + i * 2) % 5;
      const duration = 1 + (i % 3);
      const endDay = Math.min(startDay + duration - 1, 6);

      list.push({
        id: `REQ-${reqIndex}`,
        title: REQ_TITLES[(personIdx + i) % REQ_TITLES.length],
        status,
        assignee: name,
        startDay,
        duration,
        priority: i % 3 === 0 ? '高' : i % 3 === 1 ? '中' : '低',
        description: `${REQ_TITLES[(personIdx + i) % REQ_TITLES.length]}的详细说明，包含业务背景与交付要求。`,
        createdAt: WEEKDAYS[startDay],
        plannedEnd: WEEKDAYS[endDay],
        sopNodes: buildSopNodes(status),
      });
      reqIndex += 1;
    }
  });

  return list;
}

const overlapDemoRequirements: PersonRequirement[] = [
  {
    id: 'REQ-9001',
    title: '紧急缺陷修复',
    status: 'inProgress',
    assignee: '张三',
    startDay: 2,
    duration: 1,
    priority: '高',
    description: '周三发现的线上缺陷，需当天修复上线。',
    createdAt: '周三',
    plannedEnd: '周三',
    sopNodes: buildSopNodes('inProgress'),
  },
  {
    id: 'REQ-9002',
    title: '接口文档补全',
    status: 'pending',
    assignee: '张三',
    startDay: 2,
    duration: 2,
    priority: '中',
    description: '与周三联调并行，补齐 OpenAPI 文档。',
    createdAt: '周三',
    plannedEnd: '周四',
    sopNodes: buildSopNodes('pending'),
  },
  {
    id: 'REQ-9003',
    title: 'CodeReview 排队',
    status: 'pending',
    assignee: '张三',
    startDay: 2,
    duration: 1,
    priority: '低',
    description: '等待审查同事合入的 PR。',
    createdAt: '周三',
    plannedEnd: '周三',
    sopNodes: buildSopNodes('pending'),
  },
];

const personRequirementData: PersonRequirement[] = [
  ...buildRequirements(),
  ...overlapDemoRequirements,
];

export const workOrderTicketData = buildWorkOrderTickets(
  personRequirementData.slice(0, 28),
);

export const personDemandData: PersonDemandItem[] = TEAM_NAMES.map((name, idx) => ({
  name,
  completed: TEAM_NAMES.length - idx,
  inProgress: (idx % 3) + 1,
  pending: ((idx + 1) % 3) + 1,
})).sort((a, b) => b.completed - a.completed);

export const personAiCoverageDetailData: PersonAiCoverageItem[] = personDemandData.map((person, idx) => {
  const totalOrders = person.completed + person.inProgress + person.pending;
  const aiRatio = 0.38 + ((idx * 5 + 2) % 10) * 0.06;
  const aiOrders = Math.min(totalOrders, Math.max(0, Math.round(totalOrders * aiRatio)));

  return {
    name: person.name,
    totalOrders,
    aiOrders,
  };
});

const aiCoverageAvg = calcAverageAiCoverageRate(personAiCoverageDetailData);
const aiCoverageKpi = kpiData.find((item) => item.key === 'aiCoverage');
if (aiCoverageKpi) {
  aiCoverageKpi.value = `${aiCoverageAvg}%`;
}

export const personDemandPreviewData: PersonDemandItem[] = personDemandData.slice(
  0,
  PERSON_WORKLOAD_DISPLAY_LIMIT,
);

// ==================== Person Table ====================
const personDetailData: PersonDetail[] = [
  { name: '张三', totalOrders: 128, completed: 96, inProgress: 18, avgHoursPerOrder: 2.5, aiEfficiencyRate: 0.75, tokenConsumed: 28500, personalCost: 820, satisfaction: 4.8 },
  { name: '李四', totalOrders: 105, completed: 78, inProgress: 15, avgHoursPerOrder: 3.1, aiEfficiencyRate: 0.68, tokenConsumed: 23200, personalCost: 910, satisfaction: 4.6 },
  { name: '王五', totalOrders: 156, completed: 132, inProgress: 14, avgHoursPerOrder: 1.8, aiEfficiencyRate: 0.82, tokenConsumed: 35100, personalCost: 750, satisfaction: 4.9 },
  { name: '赵六', totalOrders: 89, completed: 55, inProgress: 20, avgHoursPerOrder: 3.5, aiEfficiencyRate: 0.58, tokenConsumed: 19800, personalCost: 980, satisfaction: 4.3 },
];

const PERSON_COST_USAGE_FALLBACK: Record<string, { avgHours: number; avgUsage: number }> = {
  钱七: { avgHours: 2.9, avgUsage: 2050 },
  孙八: { avgHours: 2.3, avgUsage: 1880 },
  周九: { avgHours: 3.0, avgUsage: 2180 },
  吴十: { avgHours: 2.8, avgUsage: 2100 },
  郑十一: { avgHours: 2.5, avgUsage: 1920 },
  冯十二: { avgHours: 3.3, avgUsage: 2350 },
  陈十三: { avgHours: 2.7, avgUsage: 2010 },
  褚十四: { avgHours: 2.4, avgUsage: 1950 },
  卫十五: { avgHours: 3.1, avgUsage: 2280 },
  蒋十六: { avgHours: 2.6, avgUsage: 1980 },
  沈十七: { avgHours: 2.8, avgUsage: 2120 },
  韩十八: { avgHours: 3.2, avgUsage: 2410 },
  杨十九: { avgHours: 2.5, avgUsage: 1870 },
  朱二十: { avgHours: 2.9, avgUsage: 2060 },
};

export const personCostUsageData: PersonCostUsageItem[] = personDemandData.map((person, idx) => {
  const detail = personDetailData.find((item) => item.name === person.name);
  if (detail) {
    return {
      name: person.name,
      avgHours: detail.avgHoursPerOrder,
      avgUsage: Math.round(detail.tokenConsumed / detail.totalOrders),
    };
  }

  const fallback = PERSON_COST_USAGE_FALLBACK[person.name] ?? {
    avgHours: Number((2.2 + (idx % 4) * 0.25).toFixed(1)),
    avgUsage: 1800 + idx * 70,
  };

  return {
    name: person.name,
    avgHours: fallback.avgHours,
    avgUsage: fallback.avgUsage,
  };
});