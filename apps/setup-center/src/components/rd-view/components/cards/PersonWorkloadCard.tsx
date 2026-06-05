import { useMemo, useState } from 'react';
import { Card, Drawer, Button } from 'antd';
import { BarChartOutlined } from '@ant-design/icons';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { personDemandData, personDemandPreviewData } from '@rd-view/data/mockData';
import type { PersonDemandItem } from '@rd-view/types';
import {
  CHART_CARD_BODY_PADDING,
  getPersonWorkloadBarGap,
  getPersonWorkloadBarSize,
  calcPersonWorkloadChartHeight,
} from '@rd-view/constants/chartLayout';
import {
  chartCardTitleIconStyle,
  chartCardTitleStyle,
  chartCardTitleTextStyle,
  dashboardCardStyle,
} from '@rd-view/constants/dashboardTheme';

const barColors = { completed: '#165DFF', inProgress: '#00B42A', pending: '#FF7D00' };

const LEGEND_ITEMS = [
  { label: '已完成', color: barColors.completed },
  { label: '进行中', color: barColors.inProgress },
  { label: '待开始', color: barColors.pending },
];

const cardStyle = dashboardCardStyle;

const cardBodyStyle = {
  padding: CHART_CARD_BODY_PADDING,
  flex: 1,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column' as const,
};

function WorkloadLegend() {
  return (
    <div className="chart-pair-legend chart-pair-legend--inline">
      {LEGEND_ITEMS.map((item) => (
        <div key={item.label} className="chart-pair-legend-item">
          <span className="chart-pair-legend-bar" style={{ background: item.color }} />
          {item.label}
        </div>
      ))}
    </div>
  );
}

interface PersonWorkloadChartProps {
  data: PersonDemandItem[];
  height: number;
}

function PersonWorkloadChart({ data, height }: PersonWorkloadChartProps) {
  const rowCount = data.length;
  const barSize = getPersonWorkloadBarSize(rowCount);
  const barGap = getPersonWorkloadBarGap(rowCount);

  const xMax = useMemo(() => {
    const max = Math.max(...data.map((p) => p.completed + p.inProgress + p.pending), 1);
    return max + 1;
  }, [data]);

  return (
    <div className="chart-pair-chart-block" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          layout="vertical"
          data={data}
          barSize={barSize}
          barCategoryGap={barGap}
          margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, xMax]}
            tick={{ fontSize: rowCount > 8 ? 8 : 10, fill: 'var(--text-muted)' }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
            tickCount={Math.min(xMax + 1, 6)}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: rowCount > 8 ? 9 : 11, fill: 'var(--text-muted)' }}
            axisLine={false}
            tickLine={false}
            width={42}
            interval={0}
          />
          <Tooltip contentStyle={{ borderRadius: 6, border: '1px solid var(--border)', fontSize: 10, background: 'var(--overlay-bg)', color: 'var(--text-primary)' }} />
          <Bar dataKey="completed" name="已完成" stackId="stack" fill={barColors.completed} />
          <Bar dataKey="inProgress" name="进行中" stackId="stack" fill={barColors.inProgress} />
          <Bar dataKey="pending" name="待开始" stackId="stack" fill={barColors.pending} radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PersonWorkloadCard() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const totalCount = personDemandData.length;
  const previewHeight = calcPersonWorkloadChartHeight(personDemandPreviewData.length);
  const fullHeight = calcPersonWorkloadChartHeight(totalCount);
  const showViewAll = totalCount > personDemandPreviewData.length;

  return (
    <>
      <Card
        className="dashboard-card chart-pair-card"
        title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <div style={chartCardTitleStyle}>
              <BarChartOutlined style={chartCardTitleIconStyle} />
              <span style={chartCardTitleTextStyle}>人员工作量</span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 400 }}>
                Top {personDemandPreviewData.length}
              </span>
            </div>
            {showViewAll && (
              <Button
                type="link"
                size="small"
                style={{ fontSize: 10, padding: 0, height: 'auto' }}
                onClick={() => setDrawerOpen(true)}
              >
                查看全部 ({totalCount})
              </Button>
            )}
          </div>
        }
        styles={{ body: cardBodyStyle }}
        style={cardStyle}
      >
        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
          <PersonWorkloadChart data={personDemandPreviewData} height={previewHeight} />
        </div>
        <WorkloadLegend />
      </Card>

      <Drawer
        title={`人员工作量（共 ${totalCount} 人）`}
        placement="right"
        width={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <div className="person-workload-drawer-scroll">
          <PersonWorkloadChart data={personDemandData} height={fullHeight} />
        </div>
        <div style={{ marginTop: 12 }}>
          <WorkloadLegend />
        </div>
      </Drawer>
    </>
  );
}
