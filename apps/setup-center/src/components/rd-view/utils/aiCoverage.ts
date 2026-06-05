import type { PersonAiCoverageItem } from '@rd-view/types';

/** 使用率 = 智能助手处理工单数 / 总工单数 × 100% */
export function calcPersonAiCoverageRate(aiOrders: number, totalOrders: number): number {
  if (totalOrders <= 0 || aiOrders <= 0) return 0;
  return Math.round((aiOrders / totalOrders) * 100);
}

/** 按人员平均使用率 */
export function calcAverageAiCoverageRate(items: PersonAiCoverageItem[]): number {
  if (items.length === 0) return 0;

  const totalRate = items.reduce(
    (sum, item) => sum + calcPersonAiCoverageRate(item.aiOrders, item.totalOrders),
    0,
  );

  return Math.round(totalRate / items.length);
}
