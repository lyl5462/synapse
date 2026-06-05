import { useEffect, useRef, useState } from 'react';
import { Card } from 'antd';
import { DollarOutlined } from '@ant-design/icons';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { personCostUsageData } from '@rd-view/data/mockData';
import {
  chartCardTitleIconStyle,
  chartCardTitleStyle,
  chartCardTitleTextStyle,
  dashboardCardStyle,
} from '@rd-view/constants/dashboardTheme';

const CHART_MARGIN = { top: 4, right: 8, left: 4, bottom: 6 };
const TIME_COLOR = 'var(--primary)';
const USAGE_COLOR = '#FF7D00';

const formatUsageTick = (value: number) => `${(value / 1000).toFixed(1)}k`;

type CostTooltipPayload = {
  dataKey?: string | number;
  value?: number | string;
  name?: string;
};

function CostTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: CostTooltipPayload[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;

  return (
    <div
      style={{
        background: 'var(--overlay-bg)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: '8px 10px',
        fontSize: 10,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-primary)' }}>{label}</div>
      {payload.map((item) => {
        const isUsage = item.dataKey === 'avgUsage';
        const color = isUsage ? USAGE_COLOR : TIME_COLOR;
        const value = isUsage
          ? Number(item.value).toLocaleString()
          : `${item.value} h`;

        return (
          <div key={String(item.dataKey)} style={{ color, marginTop: 2 }}>
            {item.name}：{value}
          </div>
        );
      })}
    </div>
  );
}

function useContainerHeight() {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;

    const update = () => setHeight(el.clientHeight);
    update();

    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { ref, height };
}

export function CostAnalysisCard() {
  const personCount = personCostUsageData.length;
  const { ref: chartWrapRef, height: chartHeight } = useContainerHeight();
  const barSize = personCount > 12
    ? Math.min(28, Math.max(16, Math.round(chartHeight / personCount * 0.55)))
    : personCount > 8
      ? Math.min(42, Math.max(30, Math.round(chartHeight * 0.075)))
      : Math.min(36, Math.max(24, Math.round(chartHeight * 0.065)));
  const xTickFontSize = personCount > 12 ? 9 : personCount > 8 ? 10 : 11;
  const xAxisHeight = personCount > 12 ? 52 : 30;
  const xLabelAngle = personCount > 10 ? -35 : 0;
  const xLabelAnchor = personCount > 10 ? 'end' : 'middle';

  return (
    <Card
      className="dashboard-card cost-analysis-card"
      title={
        <div style={chartCardTitleStyle}>
          <DollarOutlined style={chartCardTitleIconStyle} />
          <span style={chartCardTitleTextStyle}>需求耗时&成本</span>
        </div>
      }
      styles={{ body: { padding: '8px 12px 6px', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' } }}
      style={dashboardCardStyle}
    >
      <div className="cost-analysis-plot">
        <div className="cost-analysis-axis-labels">
          <span className="cost-analysis-axis-label cost-analysis-axis-label--time">平均耗时(h)</span>
          <span className="cost-analysis-axis-label cost-analysis-axis-label--usage">平均使用量</span>
        </div>
        <div ref={chartWrapRef} className="cost-analysis-chart-wrap">
          {chartHeight > 0 && (
            <ResponsiveContainer width="100%" height={chartHeight}>
              <ComposedChart data={personCostUsageData} margin={CHART_MARGIN} barCategoryGap="8%">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: xTickFontSize, fill: 'var(--text-secondary)' }}
                  axisLine={false}
                  tickLine={false}
                  interval={0}
                  angle={xLabelAngle}
                  textAnchor={xLabelAnchor}
                  height={xAxisHeight}
                />
                <YAxis
                  yAxisId="time"
                  orientation="left"
                  tick={{ fontSize: 10, fill: TIME_COLOR, fontWeight: 500 }}
                  axisLine={false}
                  tickLine={false}
                  width={36}
                  domain={[0, (max: number) => Math.ceil(max * 1.15 * 10) / 10]}
                />
                <YAxis
                  yAxisId="usage"
                  orientation="right"
                  tick={{ fontSize: 10, fill: USAGE_COLOR, fontWeight: 500 }}
                  tickFormatter={formatUsageTick}
                  axisLine={false}
                  tickLine={false}
                  width={44}
                  domain={[0, (max: number) => Math.ceil(max * 1.15)]}
                />
                <Tooltip content={<CostTooltip />} />
                <Bar
                  yAxisId="time"
                  dataKey="avgHours"
                  name="平均耗时"
                  fill={TIME_COLOR}
                  barSize={barSize}
                  radius={[3, 3, 0, 0]}
                  legendType="none"
                />
                <Line
                  yAxisId="usage"
                  type="monotone"
                  dataKey="avgUsage"
                  name="平均使用量"
                  stroke="none"
                  dot={{ r: 5, fill: USAGE_COLOR, stroke: '#fff', strokeWidth: 2 }}
                  activeDot={{ r: 6, fill: USAGE_COLOR, stroke: '#fff', strokeWidth: 2 }}
                  legendType="none"
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="cost-analysis-legend">
          <span className="cost-analysis-legend-item cost-analysis-legend-item--time">
            <span className="cost-analysis-legend-bar" />
            平均耗时
          </span>
          <span className="cost-analysis-legend-item cost-analysis-legend-item--usage">
            <span className="cost-analysis-legend-dot" />
            平均使用量
          </span>
        </div>
      </div>
    </Card>
  );
}
