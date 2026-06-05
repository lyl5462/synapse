import type { ProductAssistantOutputItem, TimeRange } from '@rd-view/types';

export const TIME_RANGE_LABEL: Record<TimeRange, string> = {
  day: '今日',
  week: '本周',
  month: '本月',
  quarter: '本季',
  year: '本年',
};

export function getTimeRangeTrendLabel(timeRange: TimeRange): string {
  return `${TIME_RANGE_LABEL[timeRange]}环比`;
}

export function sumAssistantOutput(items: ProductAssistantOutputItem[]) {
  return items.reduce(
    (acc, item) => ({
      docCount: acc.docCount + item.docCount,
      codeCount: acc.codeCount + item.codeCount,
    }),
    { docCount: 0, codeCount: 0 },
  );
}
