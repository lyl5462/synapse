import React from 'react';
import { MeetingRoomBoard } from '../../components/rd-manage/meeting/MeetingRoomBoard';
import '../../components/rd-manage/rd-orders.css';

export function MeetingRoomView({ 
  synapseApiBase
}: { 
  synapseApiBase?: string;
}) {
  return (
    <div className="rdOrdersRoot">
      <MeetingRoomBoard synapseApiBase={synapseApiBase} />
    </div>
  );
}
