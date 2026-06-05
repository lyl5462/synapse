import { Segmented, Button, Space, Badge } from 'antd';
import { ReloadOutlined, FilterOutlined } from '@ant-design/icons';
import { useDashboard } from '@rd-view/context/DashboardContext';
import type { TimeRange } from '@rd-view/types';

export function DashboardToolbar() {
  const { state, setTimeRange } = useDashboard();

  return (
    <div className="dashboard-header">
      <div className="dashboard-header-brand">
        <span className="dashboard-header-title">团队 AI 提效总视图</span>
      </div>
      <Space size={12}>
        <Segmented<TimeRange>
          className="dashboard-header-segmented"
          value={state.timeRange}
          onChange={(val) => setTimeRange(val as TimeRange)}
          options={[
            { label: '日', value: 'day' },
            { label: '周', value: 'week' },
            { label: '月', value: 'month' },
            { label: '季', value: 'quarter' },
            { label: '年', value: 'year' },
          ]}
        />
        <Button
          icon={<ReloadOutlined />}
          shape="circle"
          size="small"
          className="dashboard-header-icon-btn"
          title="刷新数据"
        />
        <Badge dot>
          <Button
            icon={<FilterOutlined />}
            shape="circle"
            size="small"
            className="dashboard-header-icon-btn"
            title="筛选条件"
          />
        </Badge>
      </Space>
    </div>
  );
}
