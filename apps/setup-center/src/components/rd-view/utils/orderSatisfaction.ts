import type { OrderSatisfactionDetailItem } from '@rd-view/types';

/** 满意度得分（5 分制）= 点赞工单数 / 总工单数 × 5 */
export function calcOrderSatisfactionScore(items: OrderSatisfactionDetailItem[]): number {
  if (items.length === 0) return 0;
  const likeCount = items.filter((item) => item.liked).length;
  return Math.round((likeCount / items.length) * 50) / 10;
}

export function formatOrderSatisfactionScore(score: number): string {
  return `${score.toFixed(1)}/5.0`;
}
