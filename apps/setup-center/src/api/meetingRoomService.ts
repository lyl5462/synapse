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

export interface MeetingRoomParticipantWire {
  profile_id: string;
  role: 'host' | 'worker' | string;
  display_name: string;
}

export interface MeetingRoomDetail extends MeetingRoomListItem {
  room_state?: Record<string, unknown> | null;
  history?: Record<string, unknown>[];
  archive_index?: MeetingRoomArchiveEntry[];
  chat_logs?: MeetingRoomChatLogWire[];
  participants?: MeetingRoomParticipantWire[];
  current_node_binding?: Record<string, unknown>;
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

export interface HitlQuestionOption {
  value: string;
  label: string;
  selected?: boolean;
}

export interface HitlQuestionRender {
  layout?: 'vertical' | 'horizontal' | 'grid';
  optionStyle?: 'radio' | 'checkbox' | 'boolean';
  showProgress?: boolean;
  progress?: { current: number; total: number };
}

export interface HitlQuestion {
  id: string;
  type: 'single' | 'multiple' | 'boolean' | 'text' | 'textarea';
  title: string;
  context?: string;
  options?: HitlQuestionOption[];
  inputEnabled?: boolean;
  inputPlaceholder?: string;
  required?: boolean;
  render?: HitlQuestionRender;
}

export interface HitlFormSchema {
  type?: 'questionnaire';
  version?: string;
  title?: string;
  description?: string;
  questions?: HitlQuestion[];
  render?: {
    layout?: 'stepped' | 'flat';
    showOverallProgress?: boolean;
    accent?: 'blue' | 'violet' | 'emerald';
    animate?: boolean;
  };
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
  llm_endpoint_key?: string;
}

export interface MeetingRoomConfigPayload {
  version: string;
  /** 小鲸（Host）专属 LLM 端点 key，会议室级 */
  host_llm_endpoint_key?: string;
  /** 协作智能体（Worker）统一 LLM 端点 key，会议室级 */
  worker_llm_endpoint_key?: string;
  node_overrides: Record<string, MeetingRoomNodeOverride>;
  manifest_version?: string;
  stages?: { id: number; name: string; nodes: string[] }[];
  bindings?: MeetingRoomNodeBinding[];
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
  /** 节点级 worker 端点（覆盖会议室级 worker_llm_endpoint_key） */
  llm_endpoint_key?: string;
  host_llm_endpoint_key?: string;
  worker_llm_endpoint_key?: string;
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

export interface MeetingRoomLivePayload {
  room_id: string;
  scope_id?: string;
  scope_type?: MeetingRoomScopeType;
  status?: string;
  phase?: string;
  run_in_progress?: boolean;
  current_node_id?: string;
  current_node_name?: string;
  tokenConsumed?: number;
  tokenBudget?: number;
  stageDuration?: string;
  agents_active?: { profile_id: string; role?: string; status?: string }[];
  sub_agents?: {
    agent_id?: string;
    profile_id?: string;
    name?: string;
    status?: string;
    iteration?: number;
    tools_executed?: string[];
    tools_total?: number;
    skills_executed?: SkillExecutionEntry[];
    skills_total?: number;
    elapsed_s?: number;
    current_tool_summary?: string;
    reason?: string;
    from_agent?: string;
  }[];
  recent_history?: Record<string, unknown>[];
  recent_chat?: MeetingRoomChatLogWire[];
  participants?: MeetingRoomParticipantWire[];
  intervention_kind?: string;
  hitl_form_schema?: HitlFormSchema;
  hitl_locked?: boolean;
  hitl_submission?: { values?: Record<string, unknown>; submitted_at?: string; locked?: boolean };
  pending_delivery?: { report_body?: string; await_confirm?: boolean };
}

export async function fetchMeetingRoomLive(
  synapseApiBase: string,
  roomId: string,
): Promise<MeetingRoomLivePayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiGet<MeetingRoomLivePayload>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/live`,
  );
}

export interface SkillExecutionEntry {
  /** SKILL 名称，如 `whalecloud-dev-tool-doc-generate` */
  skill: string;
  /** 触发本次 SKILL 调用的具体工具，如 `run_skill_script` / `get_skill_info` */
  tool?: string;
  /** 仅 `run_skill_script` 时有值：调用的脚本文件名 */
  script?: string;
  /** load=加载说明, exec=脚本执行, instruction=instruction-only 上下文工具 */
  kind?: 'load' | 'exec' | 'instruction' | string;
  /** Wall-clock 时间戳（秒），由后端写入 */
  ts?: number;
}

export interface MeetingAgentContextTask {
  task_id?: string;
  status?: string;
  iteration?: number;
  tools_executed?: string[];
  tools_total_hint?: number;
  skills_executed?: SkillExecutionEntry[];
  skills_total_hint?: number;
  description_preview?: string;
  usage_scene?: string;
}

export interface MeetingAgentDelegationRun {
  status?: string;
  reason?: string;
  from_agent?: string;
  task_preview?: string;
  result_summary?: string;
  plan_item_id?: string;
  elapsed_s?: number;
  iteration?: number;
  tools_total?: number;
  tools_executed?: string[];
  skills_total?: number;
  current_tool_summary?: string;
  started_at?: number | string;
  finished_at?: string;
}

export interface ProcessingHistoryEntry {
  id?: string;
  seq?: number;
  ts?: string;
  category:
    | 'input'
    | 'output'
    | 'tool'
    | 'skill_load'
    | 'skill_load_blocked'
    | 'skill_exec'
    | 'skill'
    | string;
  category_label?: string;
  display_title?: string;
  title?: string;
  summary?: string;
  source?: 'human' | 'system' | 'host' | string;
  source_label?: string;
  input_kind?: string;
  output_kind?: string;
  tool_name?: string;
  tool_input?: unknown;
  result_preview?: string;
  skill_name?: string;
  skill_tool?: string;
  script_name?: string;
  executing_skill_id?: string;
  executing_script_name?: string;
  chain_label?: string;
  block_reason?: string;
  success?: boolean;
  duration_ms?: number;
  detail?: Record<string, unknown>;
  node_id?: string;
  profile_id?: string;
}

export interface MeetingAgentContextEntry {
  session_id: string;
  profile_id: string;
  role: 'host' | 'worker' | string;
  current_node_id?: string;
  preferred_endpoint?: string;
  default_cwd?: string;
  system_prompt?: string;
  system_prompt_truncated?: boolean;
  custom_prompt_suffix?: string;
  custom_prompt_suffix_truncated?: boolean;
  messages?: { role?: string; content?: unknown }[];
  messages_count?: number;
  messages_truncated?: boolean;
  processing_history?: ProcessingHistoryEntry[];
  processing_history_count?: number;
  offline_from_disk?: boolean;
  task?: MeetingAgentContextTask | null;
  delegation_runs?: MeetingAgentDelegationRun[];
  last_usage?: Record<string, unknown> | null;
}

export interface MeetingAgentContextsPayload {
  room_id: string;
  scope_id?: string | null;
  current_node_id?: string;
  host_session_id?: string;
  agents: MeetingAgentContextEntry[];
  sub_agents?: MeetingRoomLivePayload['sub_agents'];
  probed_at?: string;
  dump_path?: string;
}

export async function fetchMeetingAgentContexts(
  synapseApiBase: string,
  roomId: string,
  options?: { messageCharLimit?: number },
): Promise<MeetingAgentContextsPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const params = new URLSearchParams();
  if (options?.messageCharLimit != null) {
    params.set('message_char_limit', String(options.messageCharLimit));
  }
  const qs = params.toString();
  const path = `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/agent-contexts${qs ? `?${qs}` : ''}`;
  return apiGet<MeetingAgentContextsPayload>(base, path);
}

export async function openMeetingRoom(
  synapseApiBase: string,
  scopeType: MeetingRoomScopeType,
  scopeId: string,
  options: {
    prod: string;
    promoteToProcessing?: boolean;
    syncUserwork?: boolean;
  },
): Promise<MeetingRoomDetail> {
  const base = synapseApiBase.replace(/\/$/, '');
  const prod = (options.prod || '').trim();
  if (!prod) {
    throw new Error('missing_prod');
  }
  return apiPost<MeetingRoomDetail>(base, '/api/dev/meeting-rooms/open', {
    scope_type: scopeType,
    scope_id: scopeId,
    prod,
    sync_userwork: options.syncUserwork ?? true,
    promote_to_processing: options.promoteToProcessing ?? true,
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

/** 人工确认待归档总结后归档并推进（或纯人工节点一键通过） */
export async function approveAndResumeMeetingNode(
  synapseApiBase: string,
  roomId: string,
  text = '人工确认通过，确认总结并归档推进',
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
    'version' | 'node_overrides' | 'host_llm_endpoint_key' | 'worker_llm_endpoint_key'
  >,
): Promise<MeetingRoomConfigPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPut<MeetingRoomConfigPayload>(base, '/api/dev/meeting-room-config', body);
}

// ─── PR4：NodeReviewPanel 配套 API ──────────────────────────────────────

export interface NodeReviewAgentRow {
  profile_id: string;
  display_name: string;
  role: 'host' | 'worker' | string;
  delegations: number;
  tool_calls: number;
  skill_calls: number;
  tokens: number;
  tools: { name: string; count: number }[];
  skills: { skill: string; count: number }[];
}

export interface NodeReviewMetrics {
  node_token_total: number;
  node_duration_seconds: number;
  delegation_total: number;
  tool_call_total: number;
  skill_call_total: number;
  host: NodeReviewAgentRow | null;
  workers: NodeReviewAgentRow[];
}

export interface NodeReviewArtifactFile {
  name: string;
  relative_path: string;
  size: number;
  mtime: string;
  ext: string;
}

export interface NodeReviewSummary {
  profile_id: string;
  display_name: string;
  role: 'host' | 'worker' | string;
  summary_markdown: string;
  source: 'llm' | 'rule' | 'fallback' | string;
  conversation_path?: string;
}

export interface NodeReviewPayload {
  schema_version: number;
  scope_type: MeetingRoomScopeType;
  scope_id: string;
  room_id: string;
  node_id: string;
  node_name: string;
  node_intent?: string;
  stage_id: number;
  metrics: NodeReviewMetrics;
  summaries: NodeReviewSummary[];
  artifacts: NodeReviewArtifactFile[];
  report_body: string;
  generated_at?: string;
}

export async function fetchNodeReview(
  synapseApiBase: string,
  roomId: string,
  options?: { nodeId?: string; refresh?: boolean },
): Promise<NodeReviewPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const params = new URLSearchParams();
  if (options?.nodeId) params.set('node_id', options.nodeId);
  if (options?.refresh) params.set('refresh', 'true');
  const qs = params.toString();
  const path = `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/node-review${qs ? `?${qs}` : ''}`;
  return apiGet<NodeReviewPayload>(base, path);
}

export interface AgentTraceMessageSpeaker {
  kind: 'user' | 'host' | 'coworker' | 'system' | 'tool' | 'unknown';
  profile_id?: string;
  display_name?: string;
}

export interface AgentTraceMessage {
  index: number;
  role: string;
  speaker: AgentTraceMessageSpeaker;
  text: string;
  tool_uses?: { id: string; name: string; input?: unknown }[];
  tool_results?: { tool_use_id: string; content?: unknown }[];
}

export interface AgentTracePayload {
  scope_id: string;
  room_id: string;
  profile_id: string;
  node_id: string;
  meta: {
    profile_id: string;
    role: string;
    display_name: string;
    llm_endpoint?: string;
    capabilities?: Record<string, unknown>;
    updated_at?: string;
  } | null;
  conversation: AgentTraceMessage[];
  tools: { tools_executed: string[]; updated_at?: string } | null;
  skills: { skills_executed: unknown[]; updated_at?: string } | null;
  usage: { last_usage: Record<string, unknown>; updated_at?: string } | null;
  events: { ts: string; event: string; node_id?: string; detail?: unknown }[];
}

export async function fetchAgentTrace(
  synapseApiBase: string,
  roomId: string,
  options: { profileId: string; nodeId: string; tailMessages?: number },
): Promise<AgentTracePayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const params = new URLSearchParams({
    profile_id: options.profileId,
    node_id: options.nodeId,
  });
  if (options.tailMessages != null) params.set('tail_messages', String(options.tailMessages));
  return apiGet<AgentTracePayload>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/agent-trace?${params.toString()}`,
  );
}

export interface ArtifactFileContent {
  path: string;
  ext: string;
  content: string;
  size: number;
}

export async function fetchArtifactFile(
  synapseApiBase: string,
  roomId: string,
  path: string,
): Promise<ArtifactFileContent> {
  const base = synapseApiBase.replace(/\/$/, '');
  const params = new URLSearchParams({ path });
  return apiGet<ArtifactFileContent>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/artifact-file?${params.toString()}`,
  );
}

export type ReviewDecisionMode = 'approve' | 'reject' | 'escalate';

export interface ReviewDecisionResult {
  status: 'approved' | 'rework' | 'escalated' | string;
  node_id?: string;
  room_state?: Record<string, unknown>;
  next_node_id?: string | null;
}

export async function submitReviewDecision(
  synapseApiBase: string,
  roomId: string,
  mode: ReviewDecisionMode,
  comment = '',
): Promise<ReviewDecisionResult> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPost<ReviewDecisionResult>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/review-decision`,
    { mode, comment },
  );
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
