import { Card } from 'antd';
import { PieChartOutlined } from '@ant-design/icons';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import { demandStatusData, personDemandPreviewData } from '@rd-view/data/mockData';
import {
  CHART_CARD_BODY_PADDING,
  CHART_LEGEND_HEIGHT,
  PERSON_WORKLOAD_X_AXIS_HEIGHT,
  calcPersonWorkloadPlotHeight,
  calcPersonWorkloadChartHeight,
} from '@rd-view/constants/chartLayout';

import {
  chartCardTitleIconStyle,
  chartCardTitleStyle,
  chartCardTitleTextStyle,
  dashboardCardStyle,
} from '@rd-view/constants/dashboardTheme';

const cardStyle = dashboardCardStyle;

const cardBodyStyle = {
  padding: CHART_CARD_BODY_PADDING,
  flex: 1,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column' as const,
};

export function DemandStatusCard() {
  const total = demandStatusData.reduce((sum, item) => sum + item.value, 0);
  const rowCount = personDemandPreviewData.length;
  const plotHeight = calcPersonWorkloadPlotHeight(rowCount);
  const chartBlockHeight = calcPersonWorkloadChartHeight(rowCount);

  return (
    <Card
      className="dashboard-card chart-pair-card"
      title={
        <div style={chartCardTitleStyle}>
          <PieChartOutlined style={chartCardTitleIconStyle} />
          <span style={chartCardTitleTextStyle}>总需求状态分布</span>
        </div>
      }
      styles={{ body: cardBodyStyle }}
      style={cardStyle}
    >
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
        <div className="chart-pair-chart-block" style={{ height: chartBlockHeight }}>
          <div className="demand-pie-plot" style={{ height: plotHeight }}>
            <div className="demand-pie-chart">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                  <Pie
                    data={demandStatusData}
                    cx="50%"
                    cy="50%"
                    innerRadius="52%"
                    outerRadius="88%"
                    paddingAngle={2}
                    dataKey="value"
                    nameKey="name"
                    stroke="none"
                  >
                    {demandStatusData.map((entry, idx) => (<Cell key={idx} fill={entry.color} />))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className="demand-pie-side-legend">
              {demandStatusData.map((item) => (
                <li key={item.name} className="demand-pie-side-legend-item">
                  <span className="demand-pie-side-mark" style={{ background: item.color }} />
                  <div className="demand-pie-side-text">
                    <div>{item.name}</div>
                    <div className="demand-pie-side-meta">
                      {item.value} ({((item.value / total) * 100).toFixed(0)}%)
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="chart-pair-axis" style={{ height: PERSON_WORKLOAD_X_AXIS_HEIGHT }} />
        </div>
      </div>
      <div className="chart-pair-legend chart-pair-legend--spacer" style={{ height: CHART_LEGEND_HEIGHT }} />
    </Card>
  );
}
