import { ConfigProvider, theme as antTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { DashboardProvider } from '@rd-view/context/DashboardContext';
import { DashboardToolbar } from '@rd-view/components/DashboardToolbar';
import { KpiCards } from '@rd-view/components/cards/KpiCards';
import { DemandStatusCard } from '@rd-view/components/cards/DemandStatusCard';
import { PersonWorkloadCard } from '@rd-view/components/cards/PersonWorkloadCard';
import { CostAnalysisCard } from '@rd-view/components/cards/CostAnalysisCard';
import { ScrollChartPanel } from '@rd-view/components/cards/ScrollChartPanel';
import { useAntThemeDark } from '@rd-view/useAntThemeDark';

function TeamDashboardBody() {
  return (
    <DashboardProvider>
      <div className="dashboard-shell">
        <DashboardToolbar />
        <div className="dashboard-body">
          <div className="dashboard-kpi-row">
            <KpiCards />
          </div>
          <div className="dashboard-grid">
            <div className="dashboard-grid-left">
              <div className="chart-pair-row">
                <DemandStatusCard />
                <PersonWorkloadCard />
              </div>
              <CostAnalysisCard />
            </div>
            <div className="dashboard-grid-right">
              <ScrollChartPanel />
            </div>
          </div>
        </div>
      </div>
    </DashboardProvider>
  );
}

export function TeamDashboardWithTheme() {
  const antDark = useAntThemeDark();

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: antDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
        token: {
          colorPrimary: antDark ? '#4080FF' : '#165DFF',
          borderRadius: 8,
          colorBgContainer: antDark ? '#141414' : '#FFFFFF',
          colorBgElevated: antDark ? '#1a1a1a' : '#FFFFFF',
          colorBorder: antDark ? '#2a2a2a' : '#E5E6EB',
          colorText: antDark ? '#F2F3F7' : '#1D2129',
          colorTextSecondary: antDark ? '#C9CDD4' : '#4E5969',
        },
      }}
    >
      <TeamDashboardBody />
    </ConfigProvider>
  );
}
