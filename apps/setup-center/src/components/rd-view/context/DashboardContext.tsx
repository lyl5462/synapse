import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import type { TimeRange } from '@rd-view/types';

interface DashboardState {
  timeRange: TimeRange;
}

interface DashboardContextType {
  state: DashboardState;
  setTimeRange: (range: TimeRange) => void;
}

const DashboardContext = createContext<DashboardContextType | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DashboardState>({
    timeRange: 'week',
  });

  const setTimeRange = useCallback((range: TimeRange) => {
    setState((prev) => ({ ...prev, timeRange: range }));
  }, []);

  return (
    <DashboardContext.Provider value={{ state, setTimeRange }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardContextType {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error('useDashboard must be used within a DashboardProvider');
  }
  return context;
}