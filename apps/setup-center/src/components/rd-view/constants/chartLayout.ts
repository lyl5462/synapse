export const CHART_CARD_BODY_PADDING = '8px 10px';
export const CHART_LEGEND_HEIGHT = 36;
export const PERSON_WORKLOAD_BAR_SIZE = 14;
export const PERSON_WORKLOAD_BAR_GAP = 6;
export const PERSON_WORKLOAD_X_AXIS_HEIGHT = 22;
export const PERSON_WORKLOAD_PLOT_PADDING = 8;
export const PERSON_WORKLOAD_DENSE_THRESHOLD = 8;
export const PERSON_WORKLOAD_DISPLAY_LIMIT = 8;

export function getPersonWorkloadBarSize(rowCount: number): number {
  return rowCount > PERSON_WORKLOAD_DENSE_THRESHOLD ? 10 : PERSON_WORKLOAD_BAR_SIZE;
}

export function getPersonWorkloadBarGap(rowCount: number): number {
  return rowCount > PERSON_WORKLOAD_DENSE_THRESHOLD ? 4 : PERSON_WORKLOAD_BAR_GAP;
}

/** 条形图绘图区高度（不含 X 轴） */
export function calcPersonWorkloadPlotHeight(rowCount: number): number {
  const barSize = getPersonWorkloadBarSize(rowCount);
  const barGap = getPersonWorkloadBarGap(rowCount);
  const barsHeight = rowCount * barSize + Math.max(rowCount - 1, 0) * barGap;
  return barsHeight + PERSON_WORKLOAD_PLOT_PADDING;
}

/** 条形图总高度（含 X 轴） */
export function calcPersonWorkloadChartHeight(rowCount: number): number {
  return calcPersonWorkloadPlotHeight(rowCount) + PERSON_WORKLOAD_X_AXIS_HEIGHT;
}
