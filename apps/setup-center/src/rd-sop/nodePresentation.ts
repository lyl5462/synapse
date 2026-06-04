/**
 * SOP 节点展示语义（工单管理流水线 / 研发会议室共用）
 * — 类型标签来自 rd-sop/constants.ts；开启状态来自 meeting-room-config
 */
import { ALL_NODES, NODE_TYPE_LABEL, type NodeType } from './constants';
import type {
  MeetingRoomConfigPayload,
  MeetingRoomNodeOverride,
} from '../api/meetingRoomService';

/** 流水线节点在 UI 上的状态（会议室与工单看板对齐） */
export type SopPipelineNodeState =
  | 'completed'
  | 'processing'
  | 'error'
  | 'human_intervention'
  | 'pending'
  | 'skipped'
  | 'stopped';

export type SopPipelineRunStatus =
  | 'processing'
  | 'human_intervention'
  | 'completed'
  | 'failed'
  | 'stopped'
  | 'prepare'
  | 'pending'
  | 'full_manual';

export interface SopPipelineStateInput {
  currentNodeId: string;
  status: SopPipelineRunStatus;
  skippedNodeIds?: readonly string[];
  disabledNodeIds?: ReadonlySet<string>;
}

export interface SopNodeTypePresentation {
  label: string;
  color: string;
  bg: string;
}

/** 与后端 / 配置抽屉 `_coerce_enabled` 一致：未配置视为开启 */
export function isSopNodeEnabled(
  overrides: Record<string, MeetingRoomNodeOverride>,
  nodeId: string,
): boolean {
  const v = overrides[nodeId]?.enabled;
  if (v === undefined || v === null) return true;
  return v !== false;
}

export function buildDisabledSopNodeIds(
  overrides: Record<string, MeetingRoomNodeOverride> | undefined,
): Set<string> {
  const out = new Set<string>();
  if (!overrides) return out;
  for (const node of ALL_NODES) {
    if (!isSopNodeEnabled(overrides, node.id)) out.add(node.id);
  }
  return out;
}

export function getSopNodeTypeInfo(type: NodeType): SopNodeTypePresentation {
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
}

/** 已跳过节点卡片样式（与 styles.css 中 rd-meeting-node-card--skipped 配套） */
export const SOP_NODE_SKIPPED_CARD_CLASS = 'rd-meeting-node-card--skipped';
export const SOP_NODE_SKIPPED_CARD_SELECTED_CLASS = 'rd-meeting-node-card--skipped-selected';

export type LlmEndpointCatalogRow = {
  name: string;
  model?: string;
  priority?: number;
  enabled?: boolean;
};

/** 与后端 LLMClient 一致：未指定端点时取启用项中 priority 最小者 */
export function pickDefaultLlmEndpointFromCatalog(
  catalog: readonly LlmEndpointCatalogRow[],
): LlmEndpointCatalogRow | undefined {
  const enabled = catalog.filter((row) => row.enabled !== false);
  const pool = enabled.length > 0 ? enabled : [...catalog];
  if (!pool.length) return undefined;
  return [...pool].sort((a, b) => {
    const pa = Number.isFinite(a.priority) ? (a.priority as number) : 999;
    const pb = Number.isFinite(b.priority) ? (b.priority as number) : 999;
    if (pa !== pb) return pa - pb;
    return a.name.localeCompare(b.name);
  })[0];
}

/** 会议室 host_llm_endpoint_key：`default` 表示自动路由，非目录中的端点名 */
export function resolveLlmEndpointFromCatalog(
  endpointKey: string,
  catalog: readonly LlmEndpointCatalogRow[],
): LlmEndpointCatalogRow | undefined {
  const key = (endpointKey || 'default').trim() || 'default';
  if (key === 'default') return pickDefaultLlmEndpointFromCatalog(catalog);
  return catalog.find((row) => row.name === key);
}

/** 系统节点不展示 LLM 模型；其余节点（含人工/协同）均走主控小鲸绑定端点 */
export function sopNodeShowsLlmMetrics(nodeType: NodeType): boolean {
  return nodeType !== 'system';
}

/** 流水线节点卡片「模型」：主控绑定端点在目录中的 model 字段（与会议室配置一致） */
export function resolveSopNodeModelDisplay(
  nodeType: NodeType,
  nodeId: string,
  config: Pick<MeetingRoomConfigPayload, 'host_llm_endpoint_key' | 'bindings'> | null | undefined,
  catalog: readonly LlmEndpointCatalogRow[],
): string {
  if (nodeType === 'system') return '系统';
  const binding = config?.bindings?.find((b) => b.node_id === nodeId);
  const hostKey =
    (binding?.host_llm_endpoint_key || config?.host_llm_endpoint_key || 'default').trim() ||
    'default';
  const ep = resolveLlmEndpointFromCatalog(hostKey, catalog);
  const model = (ep?.model || '').trim();
  if (model) return model;
  if (ep?.name) return ep.name;
  return hostKey === 'default' ? '—' : hostKey;
}

export type SopNodeRuntimeMetrics = {
  deal_seconds: number;
  tokens: number;
};

export type SopNodeReviewMetricsSlice = {
  node_token_total: number;
  node_duration_seconds: number;
};

/**
 * 与 MeetingNodeDetailPanel 一致：优先 node-review（activity 汇总），其次 meeting-summary。
 */
export function pickSopNodePipelineMetrics(
  review: SopNodeReviewMetricsSlice | undefined,
  summary: SopNodeRuntimeMetrics | undefined,
  hasMeetingSummary: boolean,
): SopNodeRuntimeMetrics | null {
  if (review) {
    return {
      tokens: review.node_token_total,
      deal_seconds: review.node_duration_seconds,
    };
  }
  if (!hasMeetingSummary) return null;
  if (!summary) return { deal_seconds: 0, tokens: 0 };
  return summary;
}

export function resolveSopPipelineNodeState(
  input: SopPipelineStateInput,
  nodeId: string,
): SopPipelineNodeState {
  const skipped = input.skippedNodeIds ?? [];
  if (skipped.includes(nodeId)) return 'skipped';
  if (input.disabledNodeIds?.has(nodeId)) return 'skipped';

  if (input.status === 'prepare' || input.status === 'full_manual') return 'pending';
  if (input.status === 'pending') {
    if (nodeId === 'pending') return 'processing';
    return 'pending';
  }

  const targetIndex = ALL_NODES.findIndex((n) => n.id === nodeId);
  if (targetIndex < 0) return 'pending';

  if (input.status === 'completed') return 'completed';

  const currentIndex = ALL_NODES.findIndex((n) => n.id === input.currentNodeId);

  if (targetIndex < currentIndex) return 'completed';
  if (targetIndex > currentIndex) return 'pending';

  if (input.status === 'failed') return 'error';
  if (input.status === 'stopped') return 'stopped';
  if (input.status === 'processing') return 'processing';
  if (input.status === 'human_intervention') {
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
}
