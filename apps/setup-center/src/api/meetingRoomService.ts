/** 研发会议室 API（Phase 0/1/2） */

type SynapseWire = { errorcode: number; message?: string; data?: unknown };

export type MeetingRoomScopeType = 'demand' | 'task';

export interface MeetingRoomListItem {
  room_id: string;
  scope_type: MeetingRoomScopeType;
  scope_id: string;
  ticket_id: string;
  ticket_title: string;
  branch: string;
  stage_id: number;
  stage_name: string;
  current_node_id: string;
  current_node_name: string;
  local_process_state: string;
  status: 'processing' | 'human_intervention' | 'completed';
  pipeline_enabled: boolean;
  meeting_room_active: boolean;
  updated_at?: string;
  tokenConsumed?: number;
  tokenBudget?: number;
  stageDuration?: string;
}

export interface MeetingRoomChatLogWire {
  id: string;
  agentId: string;
  text: string;
  timestamp: string;
  type: 'info' | 'error' | 'success' | 'warning' | 'user';
}

export interface MeetingRoomDetail extends MeetingRoomListItem {
  room_state?: Record<string, unknown> | null;
  history?: Record<string, unknown>[];
  archive_index?: MeetingRoomArchiveEntry[];
  chat_logs?: MeetingRoomChatLogWire[];
}

export interface MeetingRoomArchiveEntry {
  stage_id: number;
  node_id: string;
  node_name: string;
  files: { name: string; relative_path: string; size: number }[];
}

export interface MeetingSummaryNode {
  node_id: string;
  node_name: string;
  stage_id: number;
  stage_name: string;
  status: string;
  metrics: {
    deal_seconds: number;
    tokens: number;
    started_at?: string;
    completed_at?: string;
  };
}

export interface MeetingSummaryPayload {
  scope_type: MeetingRoomScopeType;
  scope_id: string;
  dev_status?: Record<string, unknown> | null;
  room_state?: Record<string, unknown> | null;
  room_id?: string;
  summary_metrics?: {
    stage_seconds: number;
    tokens: number;
    token_budget: number;
    human_interventions: number;
  };
  nodes: MeetingSummaryNode[];
  archive_index: MeetingRoomArchiveEntry[];
  recent_history?: Record<string, unknown>[];
  recent_chat?: MeetingRoomChatLogWire[];
}

export interface HitlFormFieldOption {
  label: string;
  value: string;
}

export interface HitlFormField {
  id: string;
  label: string;
  type: 'text' | 'textarea' | 'select' | 'radio' | 'checkbox';
  required?: boolean;
  placeholder?: string;
  options?: HitlFormFieldOption[];
}

export interface HitlFormSchema {
  title?: string;
  description?: string;
  fields: HitlFormField[];
}

export interface MeetingRoomNodeOverride {
  /** 会议室 SOP 节点是否参与流水线，默认 true */
  enabled?: boolean;
  /** 会议目标（不可留空；未配置时用 Manifest 默认） */
  node_intent?: string;
  /** 完成后是否需人工确认再推进下一节点 */
  human_confirm?: boolean;
  /** 人工确认表单 schema（可选；缺省由后端按节点生成） */
  hitl_form_schema?: HitlFormSchema;
  prompt_supplement?: string;
  host_profile_id?: string;
  worker_profile_ids?: string[];
  skill_ids?: string[];
  llm_endpoint_key?: string;
}

export interface MeetingRoomSkillPreview {
  skill_id: string;
  exists: boolean;
  path?: string | null;
  title?: string;
  summary?: string;
  length?: number;
}

export interface MeetingRoomConfigPayload {
  version: string;
  /** 小鲸（Host）专属 LLM 端点 key，会议室级 */
  host_llm_endpoint_key?: string;
  /** 协作智能体（Worker）统一 LLM 端点 key，会议室级 */
  worker_llm_endpoint_key?: string;
  /** 会议室专属 SKILL ID（host / worker 进入会议室时都会加载） */
  meeting_skill_id?: string;
  node_overrides: Record<string, MeetingRoomNodeOverride>;
  manifest_version?: string;
  stages?: { id: number; name: string; nodes: string[] }[];
  bindings?: MeetingRoomNodeBinding[];
  meeting_skill?: MeetingRoomSkillPreview;
}

export interface MeetingRoomNodeBinding {
  node_id: string;
  node_name?: string;
  stage_id?: number;
  stage_name?: string;
  type?: string;
  intent?: string;
  enabled?: boolean;
  node_intent?: string;
  default_node_intent?: string;
  human_confirm?: boolean;
  default_human_confirm?: boolean;
  hitl_form_schema?: HitlFormSchema | null;
  node_outputs?: string[];
  host_profile_id?: string;
  worker_profile_ids?: string[];
  skill_ids?: string[];
  /** 节点级 worker 端点（覆盖会议室级 worker_llm_endpoint_key） */
  llm_endpoint_key?: string;
  host_llm_endpoint_key?: string;
  worker_llm_endpoint_key?: string;
  meeting_skill_id?: string;
  prompt_supplement?: string;
}

export interface DevStatusPayload {
  schema_version: number;
  scope: { type: MeetingRoomScopeType; id: string };
  local_process_state: string;
  stage_id: number;
  current_node_id: string;
  sop_node_display: string;
  pipeline_enabled: boolean;
  meeting_room: { active: boolean; room_id: string };
  updated_at?: string;
}

async function parseJson(res: Response): Promise<SynapseWire> {
  return (await res.json()) as SynapseWire;
}

async function apiGet<T>(base: string, path: string): Promise<T> {
  const res = await fetch(`${base}${path}`, { signal: AbortSignal.timeout(60_000) });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'api_error');
  }
  return j.data as T;
}

async function apiPut<T>(base: string, path: string, body: unknown): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(120_000),
  });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'api_error');
  }
  return j.data as T;
}

async function apiPost<T>(base: string, path: string, body: unknown): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60_000),
  });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'api_error');
  }
  return j.data as T;
}

export async function fetchMeetingRooms(synapseApiBase: string): Promise<MeetingRoomListItem[]> {
  const base = synapseApiBase.replace(/\/$/, '');
  const data = await apiGet<{ list?: MeetingRoomListItem[] }>(base, '/api/dev/meeting-rooms');
  return Array.isArray(data?.list) ? data.list! : [];
}

export async function fetchMeetingRoomDetail(
  synapseApiBase: string,
  roomId: string,
): Promise<MeetingRoomDetail> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiGet<MeetingRoomDetail>(base, `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}`);
}

export async function openMeetingRoom(
  synapseApiBase: string,
  scopeType: MeetingRoomScopeType,
  scopeId: string,
  options?: {
    promoteToProcessing?: boolean;
    autoRunFirstNode?: boolean;
    syncUserwork?: boolean;
  },
): Promise<MeetingRoomDetail> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPost<MeetingRoomDetail>(base, '/api/dev/meeting-rooms/open', {
    scope_type: scopeType,
    scope_id: scopeId,
    sync_userwork: options?.syncUserwork ?? true,
    promote_to_processing: options?.promoteToProcessing ?? true,
    auto_run_first_node: options?.autoRunFirstNode ?? false,
  });
}

export async function interveneMeetingRoom(
  synapseApiBase: string,
  roomId: string,
  text: string,
  messageType: 'instruction' | 'chat' = 'instruction',
  options?: { resumeRun?: boolean },
): Promise<MeetingRoomDetail> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPost<MeetingRoomDetail>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/intervene`,
    {
      text,
      message_type: messageType,
      resume_run: options?.resumeRun ?? false,
    },
  );
}

export async function fetchPendingHumanIntervention(
  synapseApiBase: string,
): Promise<MeetingRoomListItem[]> {
  const base = synapseApiBase.replace(/\/$/, '');
  const data = await apiGet<{ list?: MeetingRoomListItem[] }>(
    base,
    '/api/dev/meeting-rooms/pending/human-intervention',
  );
  return Array.isArray(data?.list) ? data.list! : [];
}

/** 人工确认后继续当前节点（Phase 3 一键通过） */
export async function approveAndResumeMeetingNode(
  synapseApiBase: string,
  roomId: string,
  text = '人工确认通过，继续执行当前节点',
): Promise<MeetingRoomDetail> {
  return interveneMeetingRoom(synapseApiBase, roomId, text, 'instruction', { resumeRun: true });
}

export async function fetchMeetingSummary(
  synapseApiBase: string,
  scopeType: MeetingRoomScopeType,
  scopeId: string,
): Promise<MeetingSummaryPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiGet<MeetingSummaryPayload>(
    base,
    `/api/dev/work-orders/${scopeType}/${encodeURIComponent(scopeId)}/meeting-summary`,
  );
}

export async function fetchMeetingRoomConfig(
  synapseApiBase: string,
): Promise<MeetingRoomConfigPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiGet<MeetingRoomConfigPayload>(base, '/api/dev/meeting-room-config');
}

export async function putMeetingRoomConfig(
  synapseApiBase: string,
  body: Pick<
    MeetingRoomConfigPayload,
    | 'version'
    | 'node_overrides'
    | 'host_llm_endpoint_key'
    | 'worker_llm_endpoint_key'
    | 'meeting_skill_id'
  >,
): Promise<MeetingRoomConfigPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPut<MeetingRoomConfigPayload>(base, '/api/dev/meeting-room-config', body);
}

export async function runMeetingRoomNode(
  synapseApiBase: string,
  roomId: string,
  options?: { dryRun?: boolean; sync?: boolean },
): Promise<{ result?: unknown; room?: MeetingRoomDetail; run_status?: string }> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPost(base, `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/run-node`, {
    dry_run: options?.dryRun,
    sync: options?.sync ?? false,
  });
}

export async function putDevStatus(
  synapseApiBase: string,
  scopeType: MeetingRoomScopeType,
  scopeId: string,
  body: Partial<DevStatusPayload> & { sync_userwork?: boolean },
): Promise<DevStatusPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const res = await fetch(`${base}/api/dev/work/${scopeType}/${encodeURIComponent(scopeId)}/dev.status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60_000),
  });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'dev_status_put_failed');
  }
  return j.data as DevStatusPayload;
}
