import type { OrderEfficiencyDetailItem } from '@rd-view/types';

/**
 * 同一工单二选一：要么 AI 做，要么人工做。
 * aiHours / manualHours 为同一工作的两种耗时。
 * 提效率 = (人工耗时 - AI耗时) / 人工耗时 × 100%
 */
export function calcOrderEfficiencyGain(aiHours: number, manualHours: number): number {
  if (manualHours <= 0 || aiHours <= 0) return 0;
  if (aiHours >= manualHours) return 0;

  return Math.round(((manualHours - aiHours) / manualHours) * 100);
}

/** 多条工单平均提效率（仅统计有提效的工单） */
export function calcAverageOrderEfficiencyGain(items: OrderEfficiencyDetailItem[]): number {
  if (items.length === 0) return 0;

  const totalGain = items.reduce(
    (sum, item) => sum + calcOrderEfficiencyGain(item.aiHours, item.manualHours),
    0,
  );

  return Math.round(totalGain / items.length);
}
