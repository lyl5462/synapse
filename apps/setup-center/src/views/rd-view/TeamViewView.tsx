import React from 'react';
import { TeamDashboardWithTheme } from '../../components/rd-view/TeamDashboardWithTheme';
import '../../components/rd-view/rd-view-shell.css';
import '../../components/rd-view/theme.css';
import '../../components/rd-view/index.css';

export function TeamViewView({ synapseApiBase }: { synapseApiBase?: string }) {
  void synapseApiBase;
  return (
    <div className="rdViewRoot">
      <TeamDashboardWithTheme />
    </div>
  );
}
