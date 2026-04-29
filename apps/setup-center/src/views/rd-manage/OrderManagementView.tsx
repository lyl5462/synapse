import React from 'react';
import { OrderManagement } from '../../components/rd-manage/OrderManagement';
import { ViewId } from '../../types';

export function OrderManagementView({ 
  synapseApiBase, 
  onViewChange 
}: { 
  synapseApiBase?: string;
  onViewChange?: (view: ViewId) => void;
}) {
  return (
    <div style={{ width: '100%', height: '100%', overflow: 'hidden' }}>
      <OrderManagement synapseApiBase={synapseApiBase} onViewChange={onViewChange} />
    </div>
  );
}
