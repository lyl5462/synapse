import { Card, Dropdown, Popover } from 'antd';
import { CaretUpOutlined, CaretDownOutlined, MoreOutlined } from '@ant-design/icons';
import { useMemo, useState, type ComponentType } from 'react';
import { getProductAssistantOutputByTimeRange, kpiData } from '@rd-view/data/mockData';
import { useDashboard } from '@rd-view/context/DashboardContext';
import type { KpiItem } from '@rd-view/types';
import { getTimeRangeTrendLabel, sumAssistantOutput } from '@rd-view/utils/assistantOutput';
import { dashboardCardStyle } from '@rd-view/constants/dashboardTheme';
import { EfficiencyGainPopoverContent } from './EfficiencyGainPopoverContent';
import { AiCoveragePopoverContent } from './AiCoveragePopoverContent';
import { OrderCoveragePopoverContent } from './OrderCoveragePopoverContent';
import { OrderSatisfactionPopoverContent } from './OrderSatisfactionPopoverContent';
import { TokenConsumedPopoverContent } from './TokenConsumedPopoverContent';
import { AssistantOutputPopoverContent } from './AssistantOutputPopoverContent';

const KPI_POPOVER_CONTENT: Record<string, ComponentType> = {
  efficiencyGain: EfficiencyGainPopoverContent,
  aiCoverage: AiCoveragePopoverContent,
  orderCoverage: OrderCoveragePopoverContent,
  satisfaction: OrderSatisfactionPopoverContent,
  tokenConsumed: TokenConsumedPopoverContent,
  assistantOutput: AssistantOutputPopoverContent,
};

function AssistantOutputKpiValue() {
  const { state } = useDashboard();
  const summary = useMemo(() => {
    const products = getProductAssistantOutputByTimeRange(state.timeRange);
    return sumAssistantOutput(products);
  }, [state.timeRange]);

  return (
    <div className="assistant-output-kpi-value">
      <div className="assistant-output-kpi-metric">
        <span className="assistant-output-kpi-number">{summary.docCount}</span>
        <span className="assistant-output-kpi-label">文档</span>
      </div>
      <div className="assistant-output-kpi-metric">
        <span className="assistant-output-kpi-number">{summary.codeCount}</span>
        <span className="assistant-output-kpi-label">代码</span>
      </div>
    </div>
  );
}

function KpiCardBody({ item }: { item: KpiItem }) {
  const { state } = useDashboard();
  const trendLabel = item.key === 'assistantOutput'
    ? getTimeRangeTrendLabel(state.timeRange)
    : item.trendLabel;

  return (
    <>
      <div className="dropdown-trigger" style={{ position: 'absolute', top: 4, right: 6, zIndex: 1 }}>
        <Dropdown
          menu={{
            items: [
              { key: '1', label: '查看详情' },
              { key: '2', label: '按人员下钻' },
              { key: '3', label: '按工单下钻' },
            ],
          }}
          trigger={['click']}
        >
          <MoreOutlined style={{ fontSize: 11, color: 'var(--text-muted)', cursor: 'pointer' }} />
        </Dropdown>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, lineHeight: 1.2 }}>{item.title}</div>
      {item.key === 'assistantOutput' ? (
        <AssistantOutputKpiValue />
      ) : (
        <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4, lineHeight: 1.1 }}>
          {item.value}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: item.key === 'assistantOutput' ? 2 : 0 }}>
        {item.isPositive ? (
          <CaretUpOutlined style={{ color: '#00B42A', fontSize: 10 }} />
        ) : (
          <CaretDownOutlined style={{ color: '#F53F3F', fontSize: 10 }} />
        )}
        <span style={{ fontSize: 10, fontWeight: 500, color: item.isPositive ? '#00B42A' : '#F53F3F' }}>
          {item.trend > 0 ? '+' : ''}
          {item.trend}
          {item.key === 'satisfaction' || item.key === 'assistantOutput' ? '' : '%'}
        </span>
        <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{trendLabel}</span>
      </div>
    </>
  );
}

export function KpiCards() {
  const [popoverKeys, setPopoverKeys] = useState<Record<string, number>>({
    efficiencyGain: 0,
    aiCoverage: 0,
    orderCoverage: 0,
    satisfaction: 0,
    tokenConsumed: 0,
    assistantOutput: 0,
  });

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10 }}>
      {kpiData.map((item) => {
        const PopoverContent = KPI_POPOVER_CONTENT[item.key];

        const card = (
          <Card
            className="kpi-card dashboard-card"
            styles={{ body: { padding: '8px 12px' } }}
            style={{ ...dashboardCardStyle, overflow: 'hidden' }}
          >
            <KpiCardBody item={item} />
          </Card>
        );

        if (!PopoverContent) {
          return (
            <div key={item.key} style={{ height: '100%' }}>
              {card}
            </div>
          );
        }

        return (
          <Popover
            key={item.key}
            content={<PopoverContent key={popoverKeys[item.key]} />}
            trigger="hover"
            placement="bottom"
            mouseEnterDelay={0.15}
            onOpenChange={(open) => {
              if (open) {
                setPopoverKeys((keys) => ({ ...keys, [item.key]: (keys[item.key] ?? 0) + 1 }));
              }
            }}
            overlayClassName="efficiency-popover-overlay"
            arrow={false}
          >
            <div style={{ height: '100%' }}>{card}</div>
          </Popover>
        );
      })}
    </div>
  );
}
