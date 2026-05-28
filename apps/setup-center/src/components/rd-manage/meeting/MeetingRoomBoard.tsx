import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { ConfigProvider, theme, Avatar, Modal, Button, Tag, Badge, Tooltip, Progress } from 'antd';
import {
  fetchMeetingRoomDetail,
  fetchMeetingRoomLive,
  fetchMeetingRooms,
  fetchMeetingNodeParticipants,
  fetchMeetingRoomConfig,
  interveneMeetingRoom,
  reprocessMeetingRoom,
  type MeetingRoomChatLogWire,
  type MeetingRoomDetail,
  type MeetingRoomListItem,
  type MeetingRoomLivePayload,
  type MeetingRoomConfigPayload,
  type MeetingRoomNodeOverride,
  type MeetingRoomParticipantWire,
} from '../../../api/meetingRoomService';
import {
  buildConfiguredRoomRoster,
  liveAgentsById,
  profilesToMap,
  type MeetingAgentProfileWire,
} from './meetingRoomRoster';
import { consumeMeetingRoomFocus } from '../../../rd-meeting/focus';
import { MeetingRoomConfigDrawer } from './MeetingRoomConfigDrawer';
import { MeetingHitlForm, type HitlFormSchema } from './MeetingHitlForm';
import { NodeReviewPanel } from './NodeReviewPanel';
import type { NodeReviewPayload } from '../../../api/meetingRoomService';
import {
  MeetingAgentContextDrawer,
  type AgentContextTarget,
} from './MeetingAgentContextDrawer';
import { toast } from 'sonner';
import {
  NODE_TYPE_LABEL,
  SOP_STAGES,
  ALL_NODES,
  stageIdForNodeId,
  stageNameForId,
  type NodeType,
  type SOPNode,
  type SOPStage,
} from '../../../rd-sop/constants';
import { MeetingNodeDetailPanel, type MeetingNodeVisualState } from './panels/MeetingNodeDetailPanel';
import { MeetingChatEmpty, MeetingChatMessage } from './MeetingChatMessage';
import {
  HOST_PROFILE_ID,
  MeetingAgentAvatar,
  resolveLogAgent,
  stubWorkerAgent,
  workerColor,
} from './MeetingAgentAvatar';
import {
  filterLogsForNodeExact,
  mergeChatLogs,
  resolveChatSpeakerName,
  shouldShowChatAvatar,
  sopScopeKey,
  type MeetingChatLog,
} from './meetingChatUtils';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Bot, Cpu, FileText, TerminalSquare, AlertTriangle, ShieldAlert, Sparkles, 
  Users, MessageSquare, CheckCircle2, ChevronRight, Hash, Activity, Zap, Settings2,
  Globe, Clock, Coins, MoreHorizontal, CircleDashed, 
  Terminal, Code2, GitBranch, FileCode2, Play, User, Info, Network, Code, 
  TestTube, CheckSquare, Flame, TrendingUp, Loader2, AlertCircle, MessageSquareText, ClipboardCheck,
  SkipForward, RotateCw, ArrowLeft,
} from 'lucide-react';

const { darkAlgorithm } = theme;

function useAntThemeDark() {
  const [dark, setDark] = useState(() => {
    if (typeof document === 'undefined') return false;
    const t = document.documentElement.getAttribute('data-theme') || 'light';
    return t === 'dark' || t === 'daltonized-dark' || t === 'high-contrast';
  });
  useEffect(() => {
    const read = () => {
      const t = document.documentElement.getAttribute('data-theme') || 'light';
      setDark(t === 'dark' || t === 'daltonized-dark' || t === 'high-contrast');
    };
    read();
    const m = new MutationObserver(read);
    m.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => m.disconnect();
  }, []);
  return dark;
}

// --- Types for Meeting Room ---
type AgentRole = 'coordinator' | 'executor' | 'reviewer' | 'designer' | 'expert';

interface Agent {
  id: string;
  name: string;
  role: string;
  avatarColor: string;
  icon: React.ReactNode;
}

interface RoomAgent extends Agent {
  status: 'idle' | 'processing' | 'error';
  currentAction: string;
}

type LogEntry = MeetingChatLog;

interface MeetingRoom {
  id: string;
  ticketId: string;
  ticketTitle: string;
  branch: string;
  stageName: string;
  stageIndex: number;
  currentNode: string;
  totalStages: number;
  status: 'processing' | 'human_intervention' | 'completed' | 'failed';
  stageDuration: string;
  tokenConsumed: number;
  tokenBudget: number;
  agents: RoomAgent[];
  /** 当前节点协作流快照（卡片预览用） */
  logs: LogEntry[];
  /** 全量协作流（按 nodeId 隔离展示） */
  allChatLogs: LogEntry[];
  brief: string;
  phase?: string;
  runInProgress?: boolean;
  hitlFormSchema?: HitlFormSchema | null;
  hitlPendingSummary?: string | null;
  reviewPayload?: NodeReviewPayload | null;
  hitlLocked?: boolean;
  hitlSubmission?: { values?: Record<string, unknown>; submitted_at?: string } | null;
  participants?: MeetingRoomParticipantWire[];
  scopeType?: 'demand' | 'task';
  scopeId?: string;
  /** 当前对话绑定的 SOP 作用域（stage:node） */
  chatSopKey?: string;
  skippedNodeIds?: string[];
  reprocessing?: boolean;
}


function participantToRoomAgent(p: MeetingRoomParticipantWire, status: RoomAgent['status'] = 'idle'): RoomAgent {
  const isHost = p.role === 'host' || p.profile_id === HOST_PROFILE_ID;
  const label = (p.display_name || '').trim();
  return {
    id: p.profile_id,
    name: label && label !== p.profile_id ? label : isHost ? '小鲸' : '协作智能体',
    role: isHost ? '会议主持' : '协作智能体',
    avatarColor: isHost ? 'bg-violet-500' : workerColor(p.profile_id),
    icon: isHost ? <Bot className="w-3 h-3" /> : <Cpu className="w-3 h-3" />,
    status,
    currentAction: isHost ? '主持本节点' : '待命',
  };
}

function buildAgentsFromDetail(item: MeetingRoomDetail): RoomAgent[] {
  const fromApi = item.participants;
  if (fromApi?.length) {
    const host = fromApi.find((p) => p.role === 'host') ?? fromApi[0];
    const workers = fromApi.filter((p) => p.profile_id !== host.profile_id);
    const runBusy = item.status === 'processing';
    return [
      participantToRoomAgent(host, runBusy ? 'processing' : 'idle'),
      ...workers.map((w) => participantToRoomAgent(w, runBusy ? 'processing' : 'idle')),
    ];
  }
  const rs = item.room_state;
  const active = Array.isArray(rs?.agents_active)
    ? (rs.agents_active as { profile_id?: string; role?: string; display_name?: string; status?: string }[])
    : [];
  if (active.length) {
    return active.map((a) =>
      participantToRoomAgent(
        {
          profile_id: String(a.profile_id || HOST_PROFILE_ID),
          role: String(a.role || 'worker'),
          display_name: String(a.display_name || a.profile_id || ''),
        },
        a.status === 'failed' ? 'error' : a.status === 'delegating' || a.status === 'running' ? 'processing' : 'idle',
      ),
    );
  }
  return [participantToRoomAgent({ profile_id: HOST_PROFILE_ID, role: 'host', display_name: '小鲸' }, 'processing')];
}

function mergeAgentsWithLive(roster: RoomAgent[], live: MeetingRoomLivePayload): RoomAgent[] {
  const liveAgents = mapLiveAgents(live, roster);
  if (!liveAgents.length) return roster;
  const byId = new Map(roster.map((a) => [a.id, a]));
  for (const la of liveAgents) {
    const prev = byId.get(la.id);
    if (prev) {
      byId.set(la.id, {
        ...prev,
        status: la.status,
        currentAction: la.currentAction || prev.currentAction,
      });
    } else if (la.id !== 'host') {
      byId.set(la.id, la);
    }
  }
  const host = byId.get(HOST_PROFILE_ID) ?? roster[0];
  if (host && live.run_in_progress) {
    byId.set(host.id, { ...host, status: 'processing', currentAction: '主持本节点' });
  }
  return Array.from(byId.values());
}

function resolveSpeakerName(room: MeetingRoom, agentId: string): string {
  if (agentId === 'user') return '我 (人类专家)';
  const hit = room.agents.find((a) => a.id === agentId);
  if (hit?.name && hit.name !== hit.id) return hit.name;
  const p = room.participants?.find((x) => x.profile_id === agentId);
  if (p?.display_name && p.display_name !== p.profile_id) return p.display_name;
  if (agentId === HOST_PROFILE_ID || agentId === 'host') return '小鲸';
  if (agentId === 'system') return '系统';
  return '小鲸';
}

function mapLiveAgents(live: MeetingRoomLivePayload, roster: RoomAgent[] = []): RoomAgent[] {
  const rosterById = new Map(roster.map((a) => [a.id, a]));
  // 按 profile_id 合并多次委派产生的多条 sub_agent 记录，避免「分身」
  const STATUS_RANK: Record<string, number> = {
    running: 3,
    delegating: 3,
    failed: 2,
    starting: 2,
    idle: 1,
    completed: 1,
    cancelled: 0,
    timeout: 2,
  };
  const merged = new Map<
    string,
    { name: string; status: string; current_tool_summary?: string }
  >();
  for (const [i, s] of (live.sub_agents || []).entries()) {
    const pid = String(s.profile_id || s.agent_id || `worker-${i}`);
    const st = String(s.status || 'idle').toLowerCase();
    const prev = merged.get(pid);
    const nextRank = STATUS_RANK[st] ?? 0;
    const prevRank = prev ? STATUS_RANK[prev.status] ?? 0 : -1;
    if (!prev || nextRank > prevRank) {
      merged.set(pid, {
        name: String(s.name || prev?.name || '').trim(),
        status: st,
        current_tool_summary: String(s.current_tool_summary || prev?.current_tool_summary || ''),
      });
    }
  }
  const workers: RoomAgent[] = Array.from(merged.entries()).map(([pid, info]) => {
    const uiStatus: RoomAgent['status'] =
      info.status === 'running' || info.status === 'delegating'
        ? 'processing'
        : info.status === 'failed' || info.status === 'timeout'
          ? 'error'
          : 'idle';
    const fromRoster = rosterById.get(pid);
    const name =
      (info.name && info.name !== pid && info.name) ||
      live.participants?.find((p) => p.profile_id === pid)?.display_name ||
      fromRoster?.name ||
      '协作智能体';
    return {
      id: pid,
      name,
      role: '协作智能体',
      avatarColor: fromRoster?.avatarColor || workerColor(pid),
      icon: fromRoster?.icon || <Cpu className="w-3 h-3" />,
      status: uiStatus,
      currentAction: info.current_tool_summary || info.status || '',
    };
  });
  const hostStatus: RoomAgent['status'] = live.run_in_progress ? 'processing' : 'idle';
  const hostRow =
    live.participants?.find((p) => p.role === 'host') ?? {
      profile_id: HOST_PROFILE_ID,
      role: 'host',
      display_name: '小鲸',
    };
  return [participantToRoomAgent(hostRow, hostStatus), ...workers];
}

function rosterFromLiveParticipants(live: MeetingRoomLivePayload): RoomAgent[] {
  const parts = live.participants || [];
  if (!parts.length) return [];
  const host = parts.find((p) => p.role === 'host') ?? parts[0];
  const workers = parts.filter((p) => p.profile_id !== host.profile_id);
  const runBusy = Boolean(live.run_in_progress);
  return [
    participantToRoomAgent(host, runBusy ? 'processing' : 'idle'),
    ...workers.map((w) => participantToRoomAgent(w, runBusy ? 'processing' : 'idle')),
  ];
}

function applyLivePatch(room: MeetingRoom, live: MeetingRoomLivePayload): MeetingRoom {
  const uiStatus = live.status as MeetingRoom['status'] | undefined;
  const nextNodeId = (live.current_node_id || '').trim() || room.currentNode;
  const nodeChanged = nextNodeId !== room.currentNode;
  const nextStageIndex =
    live.stage_id != null && Number(live.stage_id) > 0
      ? Number(live.stage_id)
      : nodeChanged
        ? stageIdForNodeId(nextNodeId)
        : room.stageIndex;
  const nextStageName =
    (live.stage_name || '').trim() || stageNameForId(nextStageIndex) || room.stageName;
  const nextSopKey = sopScopeKey(nextStageIndex, nextNodeId);

  let allChatLogs = room.allChatLogs?.length ? room.allChatLogs : room.logs;
  if (live.recent_chat && live.recent_chat.length > 0) {
    allChatLogs = mergeChatLogs(allChatLogs, live.recent_chat.map(mapChatWireToLog));
  }

  const rosterFromLive = rosterFromLiveParticipants(live);
  const roster = nodeChanged && rosterFromLive.length > 0
    ? rosterFromLive
    : room.agents.length > 0
      ? room.agents
      : rosterFromLive.length > 0
        ? rosterFromLive
        : (live.participants || []).map((p) => participantToRoomAgent(p, 'idle'));
  const agents = mergeAgentsWithLive(roster, live);
  const localState = room.brief.split(' · ')[0] || room.brief;
  const nextBrief = live.current_node_name
    ? `${localState} · ${live.current_node_name}`
    : room.brief;
  const displayLogs = filterLogsForNodeExact(allChatLogs, nextNodeId);
  return {
    ...room,
    currentNode: nextNodeId,
    stageIndex: nextStageIndex,
    stageName: nextStageName,
    status: uiStatus && ['processing', 'human_intervention', 'completed', 'failed'].includes(uiStatus)
      ? uiStatus
      : room.status,
    phase: live.phase || room.phase,
    runInProgress: live.run_in_progress ?? room.runInProgress,
    allChatLogs,
    logs: displayLogs,
    agents,
    tokenConsumed: live.tokenConsumed ?? room.tokenConsumed,
    tokenBudget: live.tokenBudget ?? room.tokenBudget,
    stageDuration: live.stageDuration || room.stageDuration,
    hitlFormSchema:
      live.hitl_form_schema !== undefined
        ? ((live.hitl_form_schema as HitlFormSchema | null) ?? null)
        : room.hitlFormSchema,
    hitlLocked: live.hitl_locked ?? room.hitlLocked,
    hitlSubmission:
      (live.hitl_submission as MeetingRoom['hitlSubmission']) ?? room.hitlSubmission ?? null,
    hitlPendingSummary:
      live.pending_delivery?.report_body ?? room.hitlPendingSummary ?? null,
    reviewPayload:
      ((live.pending_delivery as { review_payload?: NodeReviewPayload } | undefined)
        ?.review_payload as NodeReviewPayload | undefined) ?? room.reviewPayload ?? null,
    brief: live.phase ? `${nextBrief.split(' · ')[0] || nextBrief} · ${live.phase}` : nextBrief,
    chatSopKey: nextSopKey,
    participants: live.participants?.length ? live.participants : room.participants,
    reprocessing: false,
  };
}

function mapChatWireToLog(w: MeetingRoomChatLogWire): LogEntry {
  const rich =
    Boolean(w.rich) ||
    w.displayKind === 'work_plan' ||
    /^(【步骤|\*\*流程迁移|# 工作安排计划)/.test((w.text || '').trim());
  return {
    id: w.id,
    agentId: w.agentId,
    text: w.text,
    timestamp: w.timestamp,
    type: w.type,
    rich,
    nodeId: w.nodeId,
    event: w.event,
    speakerRole: w.speakerRole,
    displayKind: w.displayKind,
    payload: w.payload,
  };
}

/** live 轮询会重建 logs 数组；用尾部指纹判断是否有新消息，避免无变化时反复滚到底。 */
function getLogsTailKey(logs: LogEntry[]): string {
  if (!logs.length) return '';
  const last = logs[logs.length - 1];
  return `${logs.length}:${last.id}:${last.timestamp}:${last.text.length}`;
}

function mapDetailToRoom(item: MeetingRoomDetail): MeetingRoom {
  const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const nodeId = item.current_node_id || 'pending';
  const allChatLogs = (item.chat_logs || []).map(mapChatWireToLog);
  const logs =
    filterLogsForNodeExact(allChatLogs, nodeId).length > 0
      ? filterLogsForNodeExact(allChatLogs, nodeId)
      : [
          {
            id: 'boot',
            agentId: 'system',
            text: `工单 ${item.scope_id} · ${item.stage_name} / ${item.current_node_name}（${item.local_process_state}）`,
            timestamp: timeStr,
            type: 'info' as const,
          },
        ];
  return {
    id: item.room_id || `${item.scope_type}-${item.scope_id}`,
    ticketId: item.ticket_id || item.scope_id,
    ticketTitle: item.ticket_title || item.scope_id,
    branch: item.branch || '—',
    stageName: item.stage_name || '',
    stageIndex: item.stage_id ?? 0,
    currentNode: item.current_node_id || 'pending',
    totalStages: SOP_STAGES.length,
    status: item.status,
    stageDuration: item.stageDuration || '—',
    tokenConsumed: item.tokenConsumed ?? 0,
    tokenBudget: item.tokenBudget ?? 150000,
    agents: buildAgentsFromDetail(item),
    allChatLogs: allChatLogs.length ? allChatLogs : logs,
    logs,
    brief: `${item.local_process_state} · ${item.current_node_name || item.current_node_id}`,
    hitlFormSchema: (item.room_state?.hitl_form_schema as HitlFormSchema | undefined) ?? null,
    hitlLocked: Boolean(item.room_state?.hitl_locked),
    hitlSubmission:
      (item.room_state?.hitl_submission as MeetingRoom['hitlSubmission']) ?? null,
    hitlPendingSummary:
      (item.room_state?.pending_delivery as { report_body?: string } | undefined)?.report_body ?? null,
    reviewPayload:
      ((item.room_state?.pending_delivery as { review_payload?: NodeReviewPayload } | undefined)
        ?.review_payload as NodeReviewPayload | undefined) ?? null,
    participants: item.participants,
    scopeType: item.scope_type,
    scopeId: item.scope_id,
    chatSopKey: sopScopeKey(item.stage_id ?? 0, item.current_node_id || 'pending'),
    skippedNodeIds: item.skipped_node_ids ?? [],
  };
}

function mapListItemToRoom(item: MeetingRoomListItem): MeetingRoom {
  return mapDetailToRoom(item as MeetingRoomDetail);
}

function isSopNodeEnabled(
  overrides: Record<string, MeetingRoomNodeOverride>,
  nodeId: string,
): boolean {
  const v = overrides[nodeId]?.enabled;
  if (v === undefined || v === null) return true;
  return v !== false;
}

function buildDisabledSopNodeIds(
  overrides: Record<string, MeetingRoomNodeOverride> | undefined,
): Set<string> {
  const out = new Set<string>();
  if (!overrides) return out;
  for (const node of ALL_NODES) {
    if (!isSopNodeEnabled(overrides, node.id)) out.add(node.id);
  }
  return out;
}

const getNodeStateGlobal = (
  room: MeetingRoom,
  nodeId: string,
  disabledNodeIds?: ReadonlySet<string>,
): 'completed' | 'processing' | 'error' | 'human_intervention' | 'pending' | 'skipped' => {
  const skipped = room.skippedNodeIds ?? [];
  if (skipped.includes(nodeId)) return 'skipped';
  if (disabledNodeIds?.has(nodeId)) return 'skipped';

  const targetIndex = ALL_NODES.findIndex((n) => n.id === nodeId);
  const currentIndex = ALL_NODES.findIndex((n) => n.id === room.currentNode);

  if (targetIndex < currentIndex) return 'completed';
  if (targetIndex > currentIndex) return 'pending';

  if (room.status === 'failed') return 'error';
  if (room.status === 'processing') return 'processing';
  if (room.status === 'human_intervention') {
    const node = ALL_NODES[targetIndex];
    if (
      node.type.includes('human') ||
      node.type === 'human_multi' ||
      node.type === 'human_start' ||
      node.type === 'ai_exception'
    ) {
      return 'human_intervention';
    }
    return 'error';
  }
  return 'pending';
};

type NodeDetailViewMode = 'live' | 'review' | 'skipped';

function resolveNodeDetailViewMode(
  state: ReturnType<typeof getNodeStateGlobal>,
): NodeDetailViewMode {
  if (state === 'skipped') return 'skipped';
  if (state === 'completed') return 'review';
  return 'live';
}

function toMeetingNodeVisualState(
  state: ReturnType<typeof getNodeStateGlobal>,
): MeetingNodeVisualState {
  if (state === 'skipped') return 'pending';
  return state;
};

const SkippedNodeDetailPanel = ({ nodeName }: { nodeName: string }) => (
  <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-8 py-16 text-center">
    <SkipForward className="mb-4 h-14 w-14 text-slate-400" />
    <h3 className="text-base font-medium text-foreground">{nodeName}</h3>
    <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
      该节点未开启，流程已自动跳过，无节点处理详情。
    </p>
  </div>
);

// --- Sub-components (AgentAvatar → MeetingAgentAvatar.tsx) ---

/** 看板卡片用：不含「待处理」的流水线阶段 */
const MEETING_PIPELINE_STAGES = SOP_STAGES.filter((s) => s.id > 0);

function roomCardStatusLabel(status: MeetingRoom['status']): string {
  switch (status) {
    case 'human_intervention':
      return '待介入';
    case 'processing':
      return '进行中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '异常';
    default:
      return '';
  }
}

/** 会议室阶段进度：与标题分行，圆点+文案强制单行（必要时横向滚动） */
const RoomCardStageProgress = ({ room }: { room: MeetingRoom }) => {
  const statusTone =
    room.status === 'human_intervention'
      ? 'text-red-400'
      : room.status === 'processing'
        ? 'text-blue-400'
        : room.status === 'failed'
          ? 'text-red-400'
          : 'text-green-400';

  const statusDot =
    room.status === 'human_intervention'
      ? 'bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.8)]'
      : room.status === 'processing'
        ? 'bg-blue-500 shadow-[0_0_6px_rgba(59,130,246,0.8)] animate-pulse'
        : room.status === 'failed'
          ? 'bg-red-500'
          : 'bg-green-500';

  const currentStageLabel = room.stageName || stageNameForId(room.stageIndex);

  return (
    <div className="flex w-full min-w-0 items-center gap-2">
      <div
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto flex-nowrap [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        aria-label="SOP 阶段进度"
      >
        {MEETING_PIPELINE_STAGES.map((stage, idx) => {
          const isPast = room.stageIndex > stage.id || room.status === 'completed';
          const isActive = room.stageIndex === stage.id && room.status !== 'completed';
          const dotCls = isPast
            ? 'bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)]'
            : isActive
              ? room.status === 'human_intervention'
                ? 'bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.7)]'
                : 'bg-blue-500 shadow-[0_0_6px_rgba(59,130,246,0.8)]'
              : 'bg-muted-foreground/35';
          const textCls = isPast
            ? 'text-emerald-600/90 dark:text-emerald-400/90'
            : isActive
              ? room.status === 'human_intervention'
                ? 'text-amber-400'
                : 'text-blue-400'
              : 'text-muted-foreground/50';

          return (
            <React.Fragment key={stage.id}>
              {idx > 0 ? (
                <span
                  className={`h-px w-2 shrink-0 ${isPast || isActive ? 'bg-emerald-500/40' : 'bg-border/50'}`}
                  aria-hidden
                />
              ) : null}
              <Tooltip title={stage.name}>
                <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotCls}`} aria-hidden />
                  <span className={`text-[9px] font-medium leading-none ${textCls}`}>{stage.name}</span>
                </span>
              </Tooltip>
            </React.Fragment>
          );
        })}
      </div>
      <span
        className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[10px] font-medium ${statusTone}`}
      >
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDot}`} aria-hidden />
        [{room.stageIndex}/{room.totalStages}] {currentStageLabel}
        <span className="text-muted-foreground/60">·</span>
        {roomCardStatusLabel(room.status)}
      </span>
    </div>
  );
};

const RoomCard = ({
  room,
  rosterAgents,
  onClick,
}: {
  room: MeetingRoom;
  rosterAgents: RoomAgent[];
  onClick: (r: MeetingRoom) => void;
}) => {
  const [activeLogIndex, setActiveLogIndex] = useState(room.logs.length - 1);

  useEffect(() => {
    if (room.status !== 'processing') return;
    const interval = setInterval(() => {
      setActiveLogIndex(prev => (prev === room.logs.length - 1 ? Math.max(0, room.logs.length - 3) : prev + 1));
    }, 4000);
    return () => clearInterval(interval);
  }, [room]);

  const activeLog = room.logs[activeLogIndex] || room.logs[room.logs.length - 1];
  const activeAgent =
    rosterAgents.find((a) => a.id === activeLog?.agentId) ||
    room.agents.find((a) => a.id === activeLog?.agentId);

  const borderColor = 
    room.status === 'human_intervention' ? 'border-red-500/50 hover:border-red-400' :
    room.status === 'processing' ? 'border-blue-500/50 hover:border-blue-400' :
    'border-border hover:border-muted-foreground';

  const glowColor =
    room.status === 'human_intervention' ? 'shadow-[0_0_15px_rgba(239,68,68,0.15)]' :
    room.status === 'processing' ? 'shadow-[0_0_15px_rgba(59,130,246,0.15)]' :
    'shadow-none';

  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.01 }}
      whileTap={{ scale: 0.98 }}
      onClick={() => onClick(room)}
      className={`cursor-pointer bg-card border ${borderColor} ${glowColor} rounded-2xl overflow-hidden flex flex-col h-[380px] transition-all duration-300 relative group`}
    >
      <div className="shrink-0 border-b border-border/50 bg-muted/10 p-3 flex flex-col gap-2">
        <Tooltip title={`${room.ticketId} · ${room.ticketTitle}`}>
          <div className="flex min-w-0 items-center gap-2 whitespace-nowrap">
            <Hash className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="shrink-0 font-mono text-xs text-muted-foreground">{room.ticketId}</span>
            <span className="shrink-0 text-muted-foreground/40">|</span>
            <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
              {room.ticketTitle}
            </h3>
          </div>
        </Tooltip>
        <RoomCardStageProgress room={room} />

        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 text-muted-foreground bg-muted/40 px-2 py-1 rounded-md border border-border/50">
            <Clock className="w-3 h-3 text-indigo-400" />
            <span className="font-mono">{room.stageDuration}</span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground bg-muted/40 px-2 py-1 rounded-md border border-border/50 flex-1">
            <Coins className="w-3 h-3 text-amber-400" />
            <div className="flex-1 flex items-center gap-2">
              <span className="font-mono">{(room.tokenConsumed / 1000).toFixed(1)}k</span>
              <Progress 
                percent={Math.min(100, (room.tokenConsumed / room.tokenBudget) * 100)} 
                showInfo={false} 
                size="small"
                strokeColor={room.tokenConsumed > room.tokenBudget * 0.9 ? '#ef4444' : '#3b82f6'}
                trailColor="rgba(255,255,255,0.1)"
                style={{ marginBottom: 0, minWidth: '40px' }}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
        <div className="shrink-0">
          <span className="mb-1.5 flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
            <Users className="h-3 w-3" /> 参会代表 ({rosterAgents.length})
          </span>
          <div className="flex items-center gap-2 overflow-x-auto flex-nowrap [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {rosterAgents.map((agent) => (
              <Tooltip
                key={agent.id}
                title={
                  <div className="flex flex-col gap-1">
                    <span className="font-medium text-white">
                      {agent.name} · {agent.role}
                    </span>
                    <span className="text-xs text-foreground/90">状态: {agent.currentAction}</span>
                  </div>
                }
              >
                <div className="group/ag flex shrink-0 flex-col items-center gap-1">
                  <MeetingAgentAvatar agent={agent} />
                  <span className="max-w-[52px] truncate text-center text-[10px] text-muted-foreground transition-colors group-hover/ag:text-foreground">
                    {agent.name}
                  </span>
                </div>
              </Tooltip>
            ))}
          </div>
        </div>

        <div className="relative flex min-h-[88px] min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-border/50 bg-muted/40 p-3 group-hover:border-border transition-colors">
          <div className="mb-1 flex shrink-0 items-center gap-1 font-mono text-[9px] text-muted-foreground">
            <Activity className="h-3 w-3" /> 最新发言
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={activeLog?.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
              className="flex min-h-0 flex-1 items-start gap-2 overflow-hidden"
            >
              <div className={`mt-0.5 w-4 h-4 rounded-full flex shrink-0 items-center justify-center text-white opacity-80 ${activeAgent?.avatarColor || 'bg-muted'}`}>
                {activeAgent?.icon || <Bot className="w-2.5 h-2.5" />}
              </div>
              <div className="flex flex-col">
                <span className="text-xs text-foreground/90 leading-relaxed line-clamp-2">
                  <span className="text-muted-foreground mr-1 font-mono">[{activeLog?.timestamp}]</span>
                  {activeLog?.text}
                </span>
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* Footer Action */}
      <div className={`p-3 flex items-center justify-between border-t border-border/50 ${
        room.status === 'human_intervention' ? 'bg-red-950/20' : 'bg-muted/30'
      }`}>
        <span className={`text-xs font-medium line-clamp-1 flex-1 pr-2 ${
          room.status === 'human_intervention' ? 'text-red-400 flex items-center gap-1' : 'text-muted-foreground'
        }`}>
          {room.status === 'human_intervention' && <AlertTriangle className="w-3.5 h-3.5 shrink-0" />}
          {room.brief}
        </span>
        <Button 
          type="primary" 
          size="small" 
          className={`shrink-0 flex items-center gap-1 text-[11px] h-7 px-3 border-none ${
            room.status === 'human_intervention' 
              ? 'bg-red-600 hover:bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.4)]' 
              : 'bg-blue-600 hover:bg-blue-500 shadow-[0_0_10px_rgba(37,99,235,0.4)] opacity-0 group-hover:opacity-100 transition-opacity'
          }`}
        >
          介入会议 <ChevronRight className="w-3 h-3" />
        </Button>
      </div>
    </motion.div>
  );
};


const InterventionDialog = ({ 
  room, 
  open, 
  onClose,
  onHitlSubmit,
  onReprocess,
  synapseApiBase,
}: { 
  room: MeetingRoom | null; 
  open: boolean; 
  onClose: () => void;
  /** 仅中栏人工确认表单提交时使用，协作流只读 */
  onHitlSubmit?: (text: string) => void;
  onReprocess?: () => void;
  synapseApiBase?: string;
}) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [centerTab, setCenterTab] = useState<'detail' | 'hitl'>('detail');
  const [selectedNodeParticipants, setSelectedNodeParticipants] = useState<MeetingRoomParticipantWire[]>([]);
  const [disabledSopNodeIds, setDisabledSopNodeIds] = useState<Set<string>>(() => new Set());
  const [contextOpen, setContextOpen] = useState(false);
  const [contextAgent, setContextAgent] = useState<AgentContextTarget | null>(null);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const lastLogKeyRef = useRef('');
  const interventionRoomIdRef = useRef<string | null>(null);
  const hitlAutoFocusRef = useRef<string | null>(null);

  const hitlLocked = Boolean(room?.hitlLocked);
  const hasReviewPayload = !!(room?.reviewPayload && room.status === 'human_intervention' && !hitlLocked);
  const hitlAvailable = !!(
    (room?.hitlFormSchema || hasReviewPayload) &&
    room?.status === 'human_intervention' &&
    !hitlLocked
  );
  const hitlKind = (room?.hitlFormSchema as { summary_kind?: string; intervention_kind?: string } | undefined)
    ?? (hasReviewPayload ? { intervention_kind: 'result_confirm' as const } : undefined);
  const hitlBadgeText = useMemo(() => {
    const k = (hitlKind?.summary_kind || hitlKind?.intervention_kind || '').toLowerCase();
    if (k === 'exception') return '异常待裁决';
    if (k === 'result_confirm') return '结果待确认';
    if (k === 'interactive') return '澄清待回复';
    return '待人工确认';
  }, [hitlKind]);

  const hitlFocusKey = useMemo(() => {
    if (!hitlAvailable || !room) return null;
    const schema = room.hitlFormSchema as { title?: string; questions?: unknown[] } | null | undefined;
    const schemaSig = schema
      ? `${schema.title ?? ''}:${schema.questions?.length ?? 0}`
      : hasReviewPayload
        ? `review:${room.reviewPayload?.node_id ?? room.currentNode}`
        : 'hitl';
    return `${room.id}:${room.currentNode}:${schemaSig}`;
  }, [hitlAvailable, room, hasReviewPayload]);

  const chatNodeId = selectedNodeId || room?.currentNode || 'pending';
  const displayChatLogs = useMemo(
    () => (room ? filterLogsForNodeExact(room.allChatLogs ?? room.logs, chatNodeId) : []),
    [room, chatNodeId],
  );

  const currentStage = room ? SOP_STAGES.find((s) => s.id === room.stageIndex) : undefined;
  const stageNodes = currentStage?.nodes || [];
  const selectedNode =
    stageNodes.find((n) => n.id === selectedNodeId) ||
    stageNodes.find((n) => n.id === room?.currentNode) ||
    stageNodes[0];

  const canReprocess = Boolean(
    room &&
    selectedNode?.id === room.currentNode &&
    room.status !== 'completed' &&
    !room.reprocessing &&
    (
      room.status === 'failed' ||
      (room.status === 'processing' && !room.runInProgress) ||
      (room.status === 'human_intervention' && !hitlAvailable)
    ),
  );

  const displayAgents = useMemo((): RoomAgent[] => {
    if (!room) return [];
    const parts =
      selectedNodeParticipants.length > 0
        ? selectedNodeParticipants
        : chatNodeId === room.currentNode
          ? room.participants || []
          : [];
    const isCurrentNode = chatNodeId === room.currentNode;
    return parts.map((p) => {
      if (isCurrentNode) {
        const live = room.agents.find((a) => a.id === p.profile_id);
        if (live) return live;
      }
      return participantToRoomAgent(
        p,
        isCurrentNode && room.runInProgress ? 'processing' : 'idle',
      );
    });
  }, [room, selectedNodeParticipants, chatNodeId]);

  useEffect(() => {
    if (!open) {
      setDisabledSopNodeIds(new Set());
      return;
    }
    const base = (synapseApiBase || '').trim();
    if (!base) return;
    let cancelled = false;
    void fetchMeetingRoomConfig(base)
      .then((cfg) => {
        if (!cancelled) setDisabledSopNodeIds(buildDisabledSopNodeIds(cfg.node_overrides));
      })
      .catch(() => {
        if (!cancelled) setDisabledSopNodeIds(new Set());
      });
    return () => {
      cancelled = true;
    };
  }, [open, synapseApiBase]);

  useEffect(() => {
    if (!open || !room?.id || !chatNodeId) {
      setSelectedNodeParticipants([]);
      return;
    }
    const base = (synapseApiBase || '').trim();
    if (!base) return;
    let cancelled = false;
    void fetchMeetingNodeParticipants(base, room.id, chatNodeId)
      .then((res) => {
        if (!cancelled) setSelectedNodeParticipants(res.participants || []);
      })
      .catch(() => {
        if (!cancelled) setSelectedNodeParticipants([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, room?.id, chatNodeId, synapseApiBase]);

  const scrollLogsToBottom = useCallback(() => {
    setTimeout(() => {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
  }, []);

  useEffect(() => {
    if (!open) {
      setSelectedNodeId(null);
      setCenterTab('detail');
      interventionRoomIdRef.current = null;
      hitlAutoFocusRef.current = null;
      return;
    }
    if (!room) return;
    if (interventionRoomIdRef.current !== room.id) {
      interventionRoomIdRef.current = room.id;
      setSelectedNodeId(room.currentNode);
    }
  }, [open, room?.id, room?.currentNode]);

  /** 人工确认触发或待办更新时，自动切到「人工确认」并聚焦当前节点 */
  useEffect(() => {
    if (!open) return;
    if (!hitlAvailable || !hitlFocusKey) {
      hitlAutoFocusRef.current = null;
      setCenterTab((tab) => (tab === 'hitl' ? 'detail' : tab));
      return;
    }
    if (hitlAutoFocusRef.current === hitlFocusKey) return;
    hitlAutoFocusRef.current = hitlFocusKey;
    setCenterTab('hitl');
    if (room?.currentNode) setSelectedNodeId(room.currentNode);
  }, [open, hitlAvailable, hitlFocusKey, room?.currentNode]);

  useEffect(() => {
    if (!open) return;
    lastLogKeyRef.current = '';
    const pane = logsEndRef.current?.parentElement;
    if (pane) pane.scrollTop = 0;
  }, [open, chatNodeId, room?.id]);

  /** 仅当尾部指纹变化（有新消息）时滚到底；live 轮询会重建 room 但不会改 logs 内容 */
  useEffect(() => {
    if (!open || !room) return;
    const key = getLogsTailKey(displayChatLogs);
    if (key === lastLogKeyRef.current) return;
    lastLogKeyRef.current = key;
    scrollLogsToBottom();
  }, [open, room, displayChatLogs, scrollLogsToBottom]);

  if (!room) return null;

  const openAgentContext = (agent: RoomAgent) => {
    setContextAgent({
      profileId: agent.id,
      name: agent.name,
      role: agent.role,
      avatarColor: agent.avatarColor,
      isHost: agent.id === HOST_PROFILE_ID || agent.role === '会议主持',
      nodeId: chatNodeId,
    });
    setContextOpen(true);
  };

  const getNodeTypeInfo = (type: NodeType) => {
    const label = NODE_TYPE_LABEL[type] ?? '未知';
    switch (type) {
      case 'ai':
        return { label, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/30' };
      case 'human':
      case 'human_start':
        return { label, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30' };
      case 'ai_human':
        return { label, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/30' };
      case 'human_multi':
        return { label, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/30' };
      case 'system':
        return { label, color: 'text-muted-foreground', bg: 'bg-muted/10 border-border/30' };
      case 'ai_exception':
        return { label, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' };
      default:
        return { label, color: 'text-muted-foreground', bg: 'bg-muted/30 border-border/30' };
    }
  };

  return (
    <Modal
      title={null}
      open={open}
      footer={null}
      width={1840}
      style={{ maxWidth: '96vw' }}
      centered
      closable={false}
      maskClosable={false}
      keyboard={false}
      className="intervention-modal"
      classNames={{
        // antd v5: 部分版本不在 ModalClassNamesType 中暴露 content；通过 className 兜底
        ...({
          content: 'bg-[color:var(--panel)] p-0 overflow-hidden border border-border/50 rounded-2xl shadow-2xl',
          mask: 'backdrop-blur-sm bg-black/70',
        } as Record<string, string>),
      }}
    >
      <div className="flex h-[min(92vh,960px)] divide-x divide-slate-800/60">
        
        {/* COL 1: Current Stage Agenda List (320px) */}
        <div className="w-[320px] bg-[color:var(--panel)] flex flex-col shrink-0">
          {/* Ticket Header */}
          <div className="p-4 border-b border-border/60 flex flex-col justify-center gap-1.5 min-h-[88px]">
            <div className="text-xs text-muted-foreground font-mono flex items-center gap-1.5 min-w-0">
              <GitBranch className="w-3 h-3 shrink-0" />
              <span className="truncate">{room.ticketId}</span>
            </div>
            <h3 className="text-sm font-semibold text-foreground line-clamp-3 leading-snug break-words">
              {room.ticketTitle}
            </h3>
          </div>
          
          {/* Stage Banner */}
          <div className="px-4 py-3 border-b border-border/40 bg-muted/30">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_6px_rgba(59,130,246,0.8)]" />
              <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
                {currentStage?.name} · 会议议题清单
              </span>
            </div>
            <p className="text-[10px] text-muted-foreground/80 mt-1 ml-4">
              共 {stageNodes.length} 个议题节点 · 点击查看产物
            </p>
          </div>

          {/* Agenda Items - only current stage nodes */}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-2">
            {stageNodes.map((node, idx) => {
              const state = getNodeStateGlobal(room, node.id, disabledSopNodeIds);
              const typeInfo = getNodeTypeInfo(node.type);
              const isSelected = selectedNode?.id === node.id;
              const isCurrentNode = node.id === room.currentNode;

              return (
                <motion.div
                  key={node.id}
                  whileHover={{ x: 2 }}
                  onClick={() => setSelectedNodeId(node.id)}
                  className={`cursor-pointer rounded-xl p-3 border transition-all duration-200 ${
                    isSelected
                      ? 'bg-blue-950/30 border-blue-700/60 shadow-[0_0_12px_rgba(59,130,246,0.1)]'
                      : state === 'error' ? 'bg-red-950/20 border-red-900/40 hover:border-red-700/50'
                      : state === 'human_intervention' ? 'bg-amber-950/20 border-amber-900/40 hover:border-amber-700/50'
                      : state === 'completed' ? 'bg-emerald-950/10 border-emerald-900/30 hover:border-emerald-700/40'
                      : state === 'skipped' ? 'bg-slate-900/20 border-slate-700/40 hover:border-slate-600/50'
                      : state === 'processing' ? 'bg-blue-950/15 border-blue-900/30 hover:border-blue-700/50'
                      : 'bg-muted/40 border-border/50 hover:border-border'
                  }`}
                >
                  {/* Node Header Row */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-muted-foreground/80">#{String(idx + 1).padStart(2, '0')}</span>
                      <div className="flex items-center gap-1.5">
                        {state === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />}
                        {state === 'skipped' && (
                          <Tooltip title="未开启，已跳过">
                            <SkipForward className="w-3.5 h-3.5 text-slate-400" />
                          </Tooltip>
                        )}
                        {state === 'processing' && <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />}
                        {state === 'error' && <AlertCircle className="w-3.5 h-3.5 text-red-500 animate-pulse" />}
                        {state === 'human_intervention' && <AlertTriangle className="w-3.5 h-3.5 text-amber-500 animate-pulse" />}
                        {state === 'pending' && <CircleDashed className="w-3.5 h-3.5 text-muted-foreground/80" />}
                        <span className={`text-xs font-medium ${
                          isSelected ? 'text-blue-300' :
                          state === 'error' ? 'text-red-400' :
                          state === 'human_intervention' ? 'text-amber-400' :
                          state === 'processing' ? 'text-blue-300' :
                          state === 'skipped' ? 'text-slate-400' :
                          state === 'completed' ? 'text-foreground/90' : 'text-muted-foreground'
                        }`}>
                          {node.name}
                        </span>
                      </div>
                    </div>
                    {isCurrentNode && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-900/40 border border-blue-700/50 text-blue-400 whitespace-nowrap shrink-0">当前</span>
                    )}
                  </div>

                  {/* 主要动作 */}
                  <div className={`inline-flex items-center gap-1.5 mb-2 px-2 py-0.5 rounded-md border ${typeInfo.bg}`}>
                    <Zap className={`w-2.5 h-2.5 ${typeInfo.color}`} />
                    <span className={`text-[10px] font-medium ${typeInfo.color}`}>{typeInfo.label}</span>
                  </div>

                  {/* 会议目标 */}
                  <p className="text-[10px] text-muted-foreground leading-relaxed line-clamp-2">
                    {node.desc}
                  </p>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* COL 2: Tabs【节点详情 / 人工确认】 */}
        <div className="flex-1 bg-background flex flex-col relative overflow-hidden">
          {/* Tab Header */}
          <div className="h-[72px] border-b border-border/60 px-6 flex items-center justify-between bg-[color:var(--panel)] shrink-0">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCenterTab('detail')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all border ${
                  centerTab === 'detail'
                    ? 'bg-blue-500/15 border-blue-500/40 text-blue-300 shadow-[0_0_12px_rgba(59,130,246,0.18)]'
                    : 'bg-transparent border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/40'
                }`}
              >
                <FileText className="w-4 h-4" />
                节点处理详情
                {selectedNode ? (
                  <span className="text-[10px] text-muted-foreground/70 font-mono">· {selectedNode.name}</span>
                ) : null}
              </button>
              <button
                type="button"
                onClick={() => hitlAvailable && setCenterTab('hitl')}
                disabled={!hitlAvailable}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all border relative ${
                  centerTab === 'hitl'
                    ? 'bg-amber-500/15 border-amber-500/45 text-amber-300 shadow-[0_0_14px_rgba(245,158,11,0.22)]'
                    : hitlAvailable
                      ? 'bg-transparent border-transparent text-amber-400 hover:bg-amber-500/10'
                      : 'bg-transparent border-transparent text-muted-foreground/40 cursor-not-allowed'
                }`}
              >
                <ClipboardCheck className="w-4 h-4" />
                人工确认
                {hitlAvailable ? (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-500/25 text-amber-200 border border-amber-500/40">
                    {hitlBadgeText}
                  </span>
                ) : null}
                {hitlAvailable && centerTab !== 'hitl' ? (
                  <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                ) : null}
              </button>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="small"
                icon={<ArrowLeft className="w-3.5 h-3.5" />}
                onClick={onClose}
              >
                返回看板
              </Button>
              {canReprocess ? (
                <Button
                  size="small"
                  type="primary"
                  danger={room.status === 'failed'}
                  icon={<RotateCw className={`w-3.5 h-3.5 ${room.reprocessing ? 'animate-spin' : ''}`} />}
                  loading={room.reprocessing}
                  onClick={() => onReprocess?.()}
                >
                  重新处理
                </Button>
              ) : null}
              {selectedNode && centerTab === 'detail' ? (
                <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs ${getNodeTypeInfo(selectedNode.type).bg} ${getNodeTypeInfo(selectedNode.type).color}`}>
                  <Zap className="w-3 h-3" />
                  {getNodeTypeInfo(selectedNode.type).label}
                </div>
              ) : null}
            </div>
          </div>

          {/* Tab Body */}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            {centerTab === 'hitl' && hitlAvailable && (hitlKind?.intervention_kind === 'result_confirm' || (hasReviewPayload && !room.hitlFormSchema)) ? (
              <div className="min-h-0 flex-1 overflow-hidden">
                <NodeReviewPanel
                  synapseApiBase={synapseApiBase || ''}
                  roomId={room.id}
                  nodeId={room.currentNode}
                  initialPayload={room.reviewPayload ?? null}
                  onDecided={() => setCenterTab('detail')}
                />
              </div>
            ) : centerTab === 'hitl' && hitlAvailable && room.hitlFormSchema ? (
              <div className="h-full min-h-0 overflow-y-auto custom-scrollbar bg-[color:var(--panel)] p-6">
                <div className="max-w-[920px] mx-auto">
                  <MeetingHitlForm
                    key={`hitl-${room.id}-${room.hitlFormSchema.title ?? ''}-${room.hitlFormSchema.questions?.length ?? 0}`}
                    schema={room.hitlFormSchema}
                    summaryMarkdown={
                      room.hitlPendingSummary ??
                      room.hitlFormSchema.summary_markdown ??
                      undefined
                    }
                    submitLabel={
                      hitlKind?.summary_kind === 'result_confirm' ||
                      hitlKind?.intervention_kind === 'result_confirm'
                        ? '确认并归档推进'
                        : '提交并继续处理'
                    }
                    onSubmit={(values) => {
                      setCenterTab('detail');
                      const summary = Object.entries(values)
                        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(',') : String(v)}`)
                        .join('\n');
                      onHitlSubmit?.(`[人工确认表单]\n${summary}`);
                    }}
                  />
                </div>
              </div>
            ) : selectedNode ? (
              (() => {
                const selectedNodeState = getNodeStateGlobal(room, selectedNode.id, disabledSopNodeIds);
                const detailViewMode = resolveNodeDetailViewMode(selectedNodeState);
                const typeInfo = getNodeTypeInfo(selectedNode.type);

                return (
                  <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    {/* Node sub-header（节点名 / 状态） */}
                    <div className="shrink-0 border-b border-border/40 bg-[color:var(--panel)]/40 px-6 pb-3 pt-4">
                      <div className="flex items-center gap-3">
                        <div className={`rounded-lg p-2 ${
                          selectedNode.type.includes('ai') ? 'bg-blue-500/20 text-blue-400' :
                          selectedNode.type === 'system' ? 'bg-muted/20 text-muted-foreground' :
                          'bg-amber-500/20 text-amber-500'
                        }`}>
                          {selectedNode.type.includes('ai') ? <Bot className="h-5 w-5" /> :
                           selectedNode.type === 'system' ? <TerminalSquare className="h-5 w-5" /> :
                           <User className="h-5 w-5" />}
                        </div>
                        <div>
                          <h3 className="flex items-center gap-2.5 text-base font-semibold text-foreground">
                            {selectedNode.name}
                            {selectedNode.id === room.currentNode ? (
                              <Badge
                                status={room.status === 'human_intervention' ? 'error' : 'processing'}
                                text={
                                  <span className={`text-xs ${room.status === 'human_intervention' ? 'text-red-400' : 'text-blue-400'}`}>
                                    {room.status === 'human_intervention' ? '等待人工干预' : '智能体处理中'}
                                  </span>
                                }
                              />
                            ) : selectedNodeState === 'completed' ? (
                              <Badge status="success" text={<span className="text-xs text-green-400">已完成</span>} />
                            ) : selectedNodeState === 'skipped' ? (
                              <Badge status="default" text={<span className="text-xs text-slate-400">未开启</span>} />
                            ) : selectedNodeState === 'pending' ? (
                              <Badge status="default" text={<span className="text-xs text-muted-foreground">待执行</span>} />
                            ) : null}
                          </h3>
                          <p className="mt-0.5 text-[10px] text-muted-foreground">{selectedNode.desc}</p>
                        </div>
                      </div>
                    </div>

                    {detailViewMode === 'skipped' ? (
                      <SkippedNodeDetailPanel nodeName={selectedNode.name} />
                    ) : detailViewMode === 'review' ? (
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <NodeReviewPanel
                          key={`detail-${room.id}-${selectedNode.id}`}
                          synapseApiBase={synapseApiBase || ''}
                          roomId={room.id}
                          nodeId={selectedNode.id}
                          readOnly
                          title="节点处理详情"
                        />
                      </div>
                    ) : (
                      <div className="min-h-0 flex-1 overflow-hidden p-5">
                        <MeetingNodeDetailPanel
                          synapseApiBase={synapseApiBase || ''}
                          roomId={room.id}
                          scopeType={room.scopeType}
                          scopeId={room.scopeId}
                          nodeId={selectedNode.id}
                          nodeName={selectedNode.name}
                          nodeState={toMeetingNodeVisualState(selectedNodeState)}
                          pollMs={selectedNodeState === 'processing' ? 4000 : 0}
                        />
                      </div>
                    )}
                  </div>
                );
              })()
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-muted-foreground/80">
                <CircleDashed className="w-12 h-12 mb-3 opacity-30" />
                <p className="text-sm">请从左侧选择议题节点</p>
              </div>
            )}
          </div>
        </div>

        {/* COL 3: Multi-Agent Chat / Interventions (440px) */}
        <div className="w-[440px] flex flex-col h-full bg-[color:var(--panel)] shrink-0">
          {/* Main Header / Members Top Bar */}
          <div className="p-3 border-b border-border bg-[color:var(--panel2)] shrink-0 h-[72px] flex flex-col justify-center">
            <div className="flex items-center justify-between mb-1.5">
               <span className="text-sm font-semibold text-foreground flex items-center gap-2 min-w-0">
                 <MessageSquare className="w-4 h-4 text-violet-400 shrink-0" />
                 <span className="truncate">
                   协作会议流
                   {selectedNode ? (
                     <span className="font-normal text-muted-foreground">
                       {' '}
                       · {selectedNode.name}
                     </span>
                   ) : null}
                 </span>
               </span>
               <Tag color={room.status === 'human_intervention' ? 'error' : room.status === 'failed' ? 'error' : 'processing'} className="m-0 border-0 text-[10px]">
                 {room.status === 'human_intervention' ? '请求专家介入' : room.status === 'failed' ? '流程异常' : 'AI 处理中'}
               </Tag>
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
               <span>参会成员:</span>
               <div className="flex items-center gap-2">
                 <Avatar size="small" className="bg-muted text-[10px] ring-2 ring-background">我</Avatar>
                 <span className="mx-1 text-muted-foreground/70">|</span>
                 {displayAgents.map(a => (
                   <MeetingAgentAvatar
                     key={a.id}
                     agent={a}
                     size="small"
                     showStatusBadge={false}
                     onClick={() => openAgentContext(a)}
                   />
                 ))}
               </div>
            </div>
          </div>

          {/* Chat Logs */}
          <div className="flex-1 overflow-y-auto px-4 py-4 custom-scrollbar scroll-smooth">
            <div className="rd-meeting-chat-stream">
              {displayChatLogs.length === 0 ? <MeetingChatEmpty /> : null}
              {displayChatLogs.map((log, index) => {
                const agent = resolveLogAgent(displayAgents, log.agentId, log);
                const speaker = resolveChatSpeakerName(
                  log,
                  agent?.name || resolveSpeakerName(room, log.agentId),
                );
                const showAvatar = shouldShowChatAvatar(log);
                const avatarAgent =
                  agent ??
                  (log.speakerRole === 'worker'
                    ? stubWorkerAgent(log.agentId, speaker)
                    : undefined);
                return (
                  <motion.div
                    key={log.id || `log-${index}`}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.22 }}
                  >
                    <MeetingChatMessage
                      log={log}
                      speakerName={speaker}
                      agent={showAvatar ? avatarAgent : undefined}
                      showAvatar={showAvatar}
                      onAvatarClick={
                        showAvatar && avatarAgent && log.speakerRole !== 'system'
                          ? () => openAgentContext(avatarAgent)
                          : undefined
                      }
                    />
                  </motion.div>
                );
              })}
            </div>
            <div ref={logsEndRef} className="h-2" />
          </div>
        </div>

      </div>

      <MeetingAgentContextDrawer
        open={contextOpen}
        onClose={() => setContextOpen(false)}
        synapseApiBase={synapseApiBase || ''}
        roomId={room.id}
        agent={contextAgent}
      />
    </Modal>
  );
};

export const MeetingRoomBoard = ({ synapseApiBase }: { synapseApiBase?: string }) => {
  const antDark = useAntThemeDark();
  const [rooms, setRooms] = useState<MeetingRoom[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeRoom, setActiveRoom] = useState<MeetingRoom | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [roomConfig, setRoomConfig] = useState<MeetingRoomConfigPayload | null>(null);
  const [agentProfiles, setAgentProfiles] = useState<Map<string, MeetingAgentProfileWire>>(
    () => new Map(),
  );
  const configOpenPrev = useRef(false);

  const loadMeetingConfig = useCallback(async () => {
    const base = (synapseApiBase || '').trim();
    if (!base) {
      setRoomConfig(null);
      setAgentProfiles(new Map());
      return;
    }
    try {
      const [cfg, profilesRes] = await Promise.all([
        fetchMeetingRoomConfig(base),
        fetch(`${base}/api/agents/profiles?include_hidden=true`).then((r) => r.json()),
      ]);
      setRoomConfig(cfg);
      setAgentProfiles(profilesToMap((profilesRes?.profiles as MeetingAgentProfileWire[]) || []));
    } catch {
      /* 配置拉取失败时卡片仍用 API 参会人兜底 */
    }
  }, [synapseApiBase]);

  useEffect(() => {
    void loadMeetingConfig();
  }, [loadMeetingConfig]);

  useEffect(() => {
    if (configOpenPrev.current && !configOpen) void loadMeetingConfig();
    configOpenPrev.current = configOpen;
  }, [configOpen, loadMeetingConfig]);

  const rosterForRoom = useCallback(
    (room: MeetingRoom): RoomAgent[] => {
      const configured = buildConfiguredRoomRoster(room.currentNode, roomConfig, agentProfiles, {
        roomStatus: room.status,
        liveById: liveAgentsById(room.agents),
      });
      if (roomConfig) return configured;
      return room.agents.length > 0 ? room.agents : configured;
    },
    [roomConfig, agentProfiles],
  );
  const reloadRooms = useCallback(async () => {
    const base = (synapseApiBase || '').trim();
    if (!base) {
      setLoadError('未配置 Synapse API 地址');
      setRooms([]);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const list = await fetchMeetingRooms(base);
      setRooms(list.map(mapListItemToRoom));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
      setRooms([]);
    } finally {
      setLoading(false);
    }
  }, [synapseApiBase]);

  useEffect(() => {
    void reloadRooms();
  }, [reloadRooms]);

  useEffect(() => {
    if (!dialogOpen || !activeRoom?.id) return;
    const base = (synapseApiBase || '').trim();
    if (!base) return;
    const roomId = activeRoom.id;
    const poll = () => {
      void fetchMeetingRoomLive(base, roomId)
        .then((live) => {
          setActiveRoom((prev) => {
            if (!prev || prev.id !== roomId) return prev;
            const merged = applyLivePatch(prev, live);
            return merged;
          });
          setRooms((prev) =>
            prev.map((r) => (r.id === roomId ? applyLivePatch(r, live) : r)),
          );
        })
        .catch(() => {
          /* 轮询失败静默，避免打断会中操作 */
        });
    };
    poll();
    const timer = window.setInterval(poll, 3000);
    return () => window.clearInterval(timer);
  }, [dialogOpen, activeRoom?.id, synapseApiBase]);

  useEffect(() => {
    const focus = consumeMeetingRoomFocus();
    if (!focus?.roomId) return;
    const base = (synapseApiBase || '').trim();
    if (!base) return;
    void fetchMeetingRoomDetail(base, focus.roomId)
      .then((detail) => {
        const merged = mapDetailToRoom(detail);
        setActiveRoom(merged);
        setDialogOpen(true);
        setRooms((prev) => {
          const exists = prev.some((r) => r.id === merged.id);
          return exists ? prev.map((r) => (r.id === merged.id ? merged : r)) : [merged, ...prev];
        });
      })
      .catch(() => {
        /* 列表刷新后用户可手动点开 */
      });
  }, [synapseApiBase]);

  const humanCount = rooms.filter((r) => r.status === 'human_intervention').length;
  const processingCount = rooms.filter((r) => r.status === 'processing').length;

  const handleOpenRoom = (room: MeetingRoom) => {
    const base = (synapseApiBase || '').trim();
    setActiveRoom(room);
    setDialogOpen(true);
    if (!base || !room.id) return;
    void fetchMeetingRoomDetail(base, room.id)
      .then((detail) => {
        const merged = mapDetailToRoom(detail);
        setActiveRoom(merged);
        setRooms((prev) => prev.map((r) => (r.id === merged.id ? merged : r)));
      })
      .catch(() => {
        /* 保留列表态数据 */
      });
  };

  const handleHitlSubmit = (text: string) => {
    if (!activeRoom) return;
    const base = (synapseApiBase || '').trim();
    if (!base) return;

    void interveneMeetingRoom(base, activeRoom.id, text, 'instruction', { resumeRun: true })
      .then((detail) => {
        const updatedRoom = mapDetailToRoom(detail);
        updatedRoom.brief = Boolean(detail.room_state?.hitl_locked)
          ? '表单已提交并锁定，系统正在继续处理…'
          : updatedRoom.brief;
        setActiveRoom(updatedRoom);
        setRooms((prev) => prev.map((r) => (r.id === updatedRoom.id ? updatedRoom : r)));
        if ((detail as { resume_run_started?: boolean }).resume_run_started) {
          toast.success('已提交，后台已继续执行当前节点');
        }
      })
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
      });
  };

  const handleReprocess = () => {
    if (!activeRoom) return;
    const base = (synapseApiBase || '').trim();
    if (!base) return;

    setActiveRoom((prev) => (prev ? { ...prev, reprocessing: true } : prev));
    void reprocessMeetingRoom(base, activeRoom.id)
      .then((detail) => {
        const updatedRoom = mapDetailToRoom(detail);
        updatedRoom.brief = '正在重新处理当前节点…';
        setActiveRoom(updatedRoom);
        setRooms((prev) => prev.map((r) => (r.id === updatedRoom.id ? updatedRoom : r)));
        toast.success('已清理过程数据，正在从节点初始化重跑');
      })
      .catch((e) => {
        setActiveRoom((prev) => (prev ? { ...prev, reprocessing: false } : prev));
        toast.error(e instanceof Error ? e.message : String(e));
      });
  };

  return (
    <ConfigProvider theme={{ algorithm: antDark ? theme.darkAlgorithm : theme.defaultAlgorithm }}>
      <div className="rdMeetingRoot flex flex-col h-full w-full bg-background text-foreground overflow-hidden font-sans">
        
        {/* Header */}
        <div className="h-16 px-8 flex items-center justify-between border-b border-border/60 bg-[color:var(--panel)]/80 backdrop-blur-md z-10 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shadow-[0_0_15px_rgba(99,102,241,0.2)]">
              <Users className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-foreground tracking-wide">多智能体研发会议室</h1>
              <p className="text-[10px] text-muted-foreground mt-0.5">实时监控、干预多个工单阶段的 AI 协作过程</p>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2 bg-red-950/30 px-3 py-1.5 rounded-full border border-red-900/50">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
              <span className="text-xs text-red-700 dark:text-red-200 font-medium">{humanCount} 会议待介入</span>
            </div>
            <div className="flex items-center gap-2 bg-blue-950/30 px-3 py-1.5 rounded-full border border-blue-900/50">
              <span className="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.8)]" />
              <span className="text-xs text-blue-700 dark:text-blue-200 font-medium">{processingCount} 会议进行中</span>
            </div>
            <Button size="small" icon={<Settings2 className="h-3.5 w-3.5" />} onClick={() => setConfigOpen(true)}>
              阵容配置
            </Button>
            <Button size="small" onClick={() => void reloadRooms()} loading={loading}>
              刷新
            </Button>
          </div>
        </div>

        {/* Board Grid */}
        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar relative">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900/10 via-background/0 to-background/0 pointer-events-none" />
          {loadError ? (
            <div className="relative z-10 text-center text-red-400 text-sm py-12">{loadError}</div>
          ) : null}
          {!loadError && !loading && rooms.length === 0 ? (
            <div className="relative z-10 text-center text-muted-foreground text-sm py-12 max-w-lg mx-auto">
              暂无活跃会议室。请在 work 目录下为工单创建 dev.status，或调用开会接口。
            </div>
          ) : null}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 max-w-[1600px] mx-auto relative z-10">
            <AnimatePresence>
              {rooms.map((room) => (
                <RoomCard
                  key={room.id}
                  room={room}
                  rosterAgents={rosterForRoom(room)}
                  onClick={handleOpenRoom}
                />
              ))}
            </AnimatePresence>
          </div>
        </div>

        {/* Intervention Dialog */}
        <InterventionDialog 
          room={activeRoom}
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
          onHitlSubmit={handleHitlSubmit}
          onReprocess={handleReprocess}
          synapseApiBase={synapseApiBase}
        />

        <MeetingRoomConfigDrawer
          open={configOpen}
          onClose={() => setConfigOpen(false)}
          synapseApiBase={synapseApiBase || ''}
        />
        
      </div>
    </ConfigProvider>
  );
};