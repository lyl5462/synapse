import React from 'react';
import { Bot, Cpu, Server } from 'lucide-react';
import type {
  MeetingRoomConfigPayload,
  MeetingRoomNodeBinding,
} from '../../../api/meetingRoomService';
import { HOST_PROFILE_ID, workerColor } from './MeetingAgentAvatar';
import type { RoomAgent } from './meetingChatTypes';

export interface MeetingAgentProfileWire {
  id: string;
  name: string;
  icon?: string;
  color?: string;
}

function bindingFor(
  bindings: MeetingRoomNodeBinding[] | undefined,
  nodeId: string,
): MeetingRoomNodeBinding | undefined {
  return bindings?.find((b) => b.node_id === nodeId);
}

/** 当前节点在会议室配置中绑定的协作智能体 profile id（不含主持） */
export function workerProfileIdsForNode(
  config: MeetingRoomConfigPayload | null | undefined,
  nodeId: string,
): string[] {
  if (!config || !nodeId) return [];
  const ov = config.node_overrides?.[nodeId];
  const binding = bindingFor(config.bindings, nodeId);
  const raw = ov?.worker_profile_ids ?? binding?.worker_profile_ids;
  if (!Array.isArray(raw)) return [];
  return raw.map((id) => String(id).trim()).filter((id) => id && id !== HOST_PROFILE_ID);
}

/** 按 SOP 节点配置渲染参会阵容：主持 + 协作智能体；system 节点仅展示系统执行方 */
export function buildConfiguredRoomRoster(
  nodeId: string,
  config: MeetingRoomConfigPayload | null | undefined,
  profilesById: Map<string, MeetingAgentProfileWire>,
  options?: {
    roomStatus?: 'processing' | 'human_intervention' | 'completed' | 'failed' | 'stopped';
    liveById?: Map<string, RoomAgent>;
    nodeType?: string;
  },
): RoomAgent[] {
  const liveById = options?.liveById;
  const runBusy = options?.roomStatus === 'processing';
  const binding = bindingFor(config?.bindings, nodeId);
  const nodeType = options?.nodeType ?? binding?.type ?? '';

  if (nodeType === 'system') {
    const live = liveById?.get('system');
    return [
      {
        id: 'system',
        name: '系统',
        role: '系统执行',
        avatarColor: 'bg-slate-500',
        icon: live?.icon ?? <Server className="w-3 h-3" />,
        status: live?.status ?? (runBusy ? 'processing' : 'idle'),
        currentAction: live?.currentAction || (runBusy ? '脚本执行中' : '待命'),
      },
    ];
  }

  const hostProfile = profilesById.get(HOST_PROFILE_ID);
  const hostLive = liveById?.get(HOST_PROFILE_ID);
  const host: RoomAgent = {
    id: HOST_PROFILE_ID,
    name: hostProfile?.name?.trim() || '小鲸',
    role: '会议主持',
    avatarColor: 'bg-violet-500',
    icon: hostLive?.icon ?? <Bot className="w-3 h-3" />,
    status: hostLive?.status ?? (runBusy ? 'processing' : 'idle'),
    currentAction: hostLive?.currentAction || (runBusy ? '主持本节点' : '待命'),
  };

  const workerIds = workerProfileIdsForNode(config, nodeId);
  const workers: RoomAgent[] = workerIds.map((pid) => {
    const p = profilesById.get(pid);
    const live = liveById?.get(pid);
    const label = (p?.name || '').trim();
    return {
      id: pid,
      name: label && label !== pid ? label : '协作智能体',
      role: '协作智能体',
      avatarColor: live?.avatarColor || workerColor(pid),
      icon: live?.icon ?? <Cpu className="w-3 h-3" />,
      status: live?.status ?? (runBusy ? 'processing' : 'idle'),
      currentAction: live?.currentAction || (runBusy ? '协作中' : '待命'),
    };
  });

  return [host, ...workers];
}

export function liveAgentsById(agents: RoomAgent[]): Map<string, RoomAgent> {
  return new Map(agents.map((a) => [a.id, a]));
}

export function profilesToMap(
  profiles: MeetingAgentProfileWire[],
): Map<string, MeetingAgentProfileWire> {
  const map = new Map<string, MeetingAgentProfileWire>();
  for (const p of profiles) {
    if (p?.id) map.set(p.id, p);
  }
  if (!map.has(HOST_PROFILE_ID)) {
    map.set(HOST_PROFILE_ID, { id: HOST_PROFILE_ID, name: '小鲸' });
  }
  return map;
}
