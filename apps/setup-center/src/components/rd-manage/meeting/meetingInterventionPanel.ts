import type { NodeType } from '../../../rd-sop/constants';

export type InterventionPanelKind = 'solution_review' | 'node_review' | 'hitl';

/** 仅人工主导节点可在配置里开关「人工确认」。 */
export function humanConfirmSwitchVisible(nodeType: NodeType | string | undefined): boolean {
  return nodeType === 'human' || nodeType === 'human_start' || nodeType === 'human_multi' || nodeType === 'ai_exception';
}

/** 按 SOP 节点类型计算有效的人工确认（与后端 binding 对齐）。 */
export function effectiveHumanConfirmByType(
  nodeType: NodeType | string | undefined,
  override?: boolean | null,
  bindingDefault?: boolean,
): boolean {
  if (nodeType === 'system' || nodeType === 'ai') return false;
  if (nodeType === 'ai_human') return true;
  if (override !== undefined && override !== null) return Boolean(override);
  return Boolean(bindingDefault);
}

export type MeetingInterventionRoomSlice = {
  status?: string;
  currentNode?: string;
  interventionKind?: string | null;
  interventionPanel?: string | null;
  hitlFormSchema?: unknown;
  hitlLocked?: boolean;
  reviewPayload?: { node_id?: string } | null;
  solutionReviewPayload?: unknown;
  /** pending_delivery.node_id：人工门控所属 SOP 节点（优先于 currentNode） */
  hitlPendingNodeId?: string | null;
};

const INTERVENTION_KIND_LABELS: Record<string, string> = {
  solution_review: '方案评审',
  result_confirm: '结果确认',
  interactive: '会中澄清',
  exception: '异常裁决',
  gate: '流程门控',
};

export function interventionKindLabel(kind: string | null | undefined): string {
  const k = (kind || '').trim().toLowerCase();
  return INTERVENTION_KIND_LABELS[k] || k || '人工处理';
}

/**
 * 人工确认 Tab / 高亮应绑定的 SOP 节点。
 * 方案评审必须用 pending_delivery.node_id，不能误用上一节点的 review_payload.node_id。
 */
export function resolveHitlTargetNodeId(room: MeetingInterventionRoomSlice): string {
  const pendingNid = (room.hitlPendingNodeId || '').trim();
  const current = (room.currentNode || '').trim();
  const kind = (room.interventionKind || '').trim().toLowerCase();
  const panel = (room.interventionPanel || '').trim();

  if (
    kind === 'solution_review' ||
    panel === 'solution_review' ||
    room.solutionReviewPayload
  ) {
    return pendingNid || current || 'solution_review';
  }

  if (panel === 'node_review' || kind === 'result_confirm') {
    const fromReview = (room.reviewPayload?.node_id || '').trim();
    return fromReview || pendingNid || current;
  }

  if (kind === 'interactive' || kind === 'exception' || room.hitlFormSchema) {
    return pendingNid || current;
  }

  const fromReview = (room.reviewPayload?.node_id || '').trim();
  return pendingNid || fromReview || current;
}

/**
 * 中栏「人工确认」Tab 应渲染的面板。
 * 优先使用 live 下发的 intervention_panel；否则按节点类型 + intervention_kind 推断。
 */
export function resolveMeetingInterventionPanel(
  room: MeetingInterventionRoomSlice,
  nodeType: NodeType | string | undefined,
  nodeId: string,
): InterventionPanelKind | null {
  if (room.status !== 'human_intervention' || room.hitlLocked) return null;

  const panel = (room.interventionPanel || '').trim();
  if (panel === 'solution_review' || panel === 'node_review' || panel === 'hitl') {
    return panel;
  }

  const kind = (room.interventionKind || '').toLowerCase();
  const nid = (nodeId || room.currentNode || '').trim();

  if (kind === 'solution_review' || room.solutionReviewPayload) {
    return 'solution_review';
  }
  if (kind === 'result_confirm' || room.reviewPayload) {
    return 'node_review';
  }

  if (nodeType === 'ai_human') {
    if (nid === 'solution_review' && room.solutionReviewPayload) return 'solution_review';
    if (room.reviewPayload) return 'node_review';
  }

  if (
    (kind === 'interactive' || kind === 'exception' || room.hitlFormSchema) &&
    humanConfirmSwitchVisible(nodeType)
  ) {
    return 'hitl';
  }

  if (room.hitlFormSchema && nodeType !== 'ai_human' && nodeType !== 'ai') {
    return 'hitl';
  }

  return null;
}
