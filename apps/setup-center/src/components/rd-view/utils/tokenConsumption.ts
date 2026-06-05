import type { ModelTokenUsageItem } from '@rd-view/types';

/** 实际成本 = 使用量 / 1000 × 定价（元/千Token） */
export function calcModelTokenCost(tokens: number, unitPrice: number): number {
  return Math.round((tokens / 1000) * unitPrice * 100) / 100;
}

export function calcTotalTokens(items: ModelTokenUsageItem[]): number {
  return items.reduce((sum, item) => sum + item.tokens, 0);
}

export function formatTotalTokens(tokens: number): string {
  if (tokens >= 10000) {
    return `${(tokens / 10000).toFixed(1)}万`;
  }
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k`;
  }
  return String(tokens);
}

export function formatTokenTick(value: number): string {
  if (value >= 10000) {
    return `${(value / 10000).toFixed(1)}万`;
  }
  return `${(value / 1000).toFixed(0)}k`;
}

export function formatUnitPrice(unitPrice: number): string {
  return `¥${unitPrice.toFixed(3)}/千Token`;
}

export function formatCostYuan(cost: number): string {
  return `¥${cost.toFixed(2)}`;
}
