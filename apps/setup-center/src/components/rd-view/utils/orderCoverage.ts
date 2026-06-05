import type { OrderCoverageDetailItem } from '@rd-view/types';

/** 需求工单覆盖率 = 已覆盖工单数 / 总工单数 × 100% */
export function calcOrderCoverageRate(coveredCount: number, totalCount: number): number {
  if (totalCount <= 0 || coveredCount <= 0) return 0;
  return Math.round((coveredCount / totalCount) * 100);
}

export function calcAverageOrderCoverageRate(items: OrderCoverageDetailItem[]): number {
  if (items.length === 0) return 0;
  const coveredCount = items.filter((item) => item.covered).length;
  return calcOrderCoverageRate(coveredCount, items.length);
}
