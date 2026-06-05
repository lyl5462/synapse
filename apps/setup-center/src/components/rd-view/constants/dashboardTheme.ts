/** 看板卡片通用 inline 样式（支持主题变量） */
export const dashboardCardStyle = {
  borderRadius: 8,
  border: '1px solid var(--border)',
  height: '100%',
  display: 'flex',
  flexDirection: 'column' as const,
  background: 'var(--bg-card)',
};

export const chartCardTitleStyle = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
};

export const chartCardTitleIconStyle = {
  color: 'var(--primary)',
  fontSize: 12,
};

export const chartCardTitleTextStyle = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-primary)',
};
