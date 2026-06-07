/** 研发会议室 API（Phase 0/1/2） */

/** 整场会议 token 预算（看板卡片进度条分母） */
export const MEETING_ROOM_TOKEN_BUDGET = 20_000_000;
/** 单个 SOP 节点 token 预算（会议室顶栏节点指标分母） */
export const MEETING_NODE_TOKEN_BUDGET = 3_000_000;

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
  status: 'processing' | 'human_intervention' | 'completed' | 'failed' | 'stopped';
  pipeline_enabled: boolean;
  meeting_room_active: boolean;
  updated_at?: string;
  tokenConsumed?: number;
  tokenBudget?: number;
  stageDuration?: string;
  /** ISO 时间，来自 room_state.metrics.stage_started_at */
  meetingStartedAt?: string;
}

export type MeetingChatSpeakerRoleWire = 'system' | 'host' | 'worker' | 'user';

export type MeetingChatDisplayKindWire =
  | 'node_context'
  | 'participants'
  | 'work_plan'
  | 'delegation_start'
  | 'delegation_done'
  | 'human_report'
  | 'hitl_tool'
  | 'pending_confirm'
  | 'flow_meta'
  | 'pipeline'
  | 'plain';

export interface MeetingRoomChatLogWire {
  id: string;
  agentId: string;
  text: string;
  timestamp: string;
  type: 'info' | 'error' | 'success' | 'warning' | 'user';
  /** 所属 SOP 节点，用于切换节点时过滤历史发言 */
  nodeId?: string;
  rich?: boolean;
  event?: string;
  speakerRole?: MeetingChatSpeakerRoleWire;
  displayKind?: MeetingChatDisplayKindWire;
  payload?: Record<string, unknown>;
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
  skipped_node_ids?: string[];
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
    /** 进行中节点：activity.jsonl 动态汇总；已完成与 ``tokens`` 相同 */
    tokens_live?: number;
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
    stage_started_at?: string;
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
  /** @deprecated 会议目标已写死为 SOP Manifest，不再持久化 */
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
  stage_id?: number;
  stage_name?: string;
  tokenConsumed?: number;
  tokenBudget?: number;
  stageDuration?: string;
  meetingStartedAt?: string;
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
  /** 仅当请求带 node_id 时：本次 recent_chat 对应的浏览节点，不等于流水线 current_node_id */
  view_node_id?: string;
  /** 带 node_id 轮询时返回的节点级 token（动态/静态） */
  view_node_token?: number;
  skipped_node_ids?: string[];
  participants?: MeetingRoomParticipantWire[];
  intervention_kind?: string;
  /** 中栏面板：solution_review | node_review | hitl */
  intervention_panel?: string | null;
  hitl_form_schema?: HitlFormSchema;
  hitl_locked?: boolean;
  hitl_submission?: { values?: Record<string, unknown>; submitted_at?: string; locked?: boolean };
  pending_delivery?: {
    report_body?: string;
    await_confirm?: boolean;
    solution_review_payload?: SolutionReviewPayload;
  };
  solution_review_blocked?: boolean;
}

// ─── 方案评审面板 ──────────────────────────────────────

export interface SolutionReviewSuggestion {
  severity?: string;
  dimension?: string;
  title?: string;
  detail?: string;
  evidence_refs?: string[];
}

export interface SolutionReviewWhaleReview {
  score?: number;
  score_breakdown?: Record<string, number>;
  verdict?: string;
  summary_markdown?: string;
  suggestions?: SolutionReviewSuggestion[];
}

export interface SolutionReviewRepoRow {
  branch_version_id?: string;
  repo_url?: string;
  change_summary?: string;
  product_module_name?: string;
  branch_version_name?: string;
}

/** 影响评估单节：标题来自文档子标题，rows 为原文表格解析结果 */
export interface SolutionReviewImpactSection {
  title: string;
  heading?: string;
  rows: Record<string, string>[];
}

export interface SolutionReviewImpactAssessment {
  /** 按文档顺序；仅含文中实际出现的子节 */
  sections?: SolutionReviewImpactSection[];
  /** 兼容旧 payload / 拆单汇总 */
  performance?: Record<string, string>[];
  functional?: Record<string, string>[];
  config?: Record<string, string>[];
  upgrade_risk?: Record<string, string>[];
  security?: Record<string, string>[];
  compatibility?: Record<string, string>[];
  ui_ue?: Record<string, string>[];
}

export interface SolutionReviewArtifactInput {
  node_id: string;
  node_name?: string;
  artifact: string;
  relative_path?: string;
  file_exists?: boolean;
  included?: boolean;
}

export interface SplitTaskDraft {
  taskNo?: string;
  taskTitle?: string;
  comments?: string;
  productModuleName?: string;
  branchVersionName?: string;
  patchName?: string;
  taskImpactDesc?: string;
  performanceImpact?: string;
  functionalImpact?: string;
  cfgChangeDescription?: string;
  upgradeRisk?: string;
  securityImpact?: string;
  compatibilityImpact?: string;
  branch_version_id?: string;
}

export interface SolutionReviewHumanReview {
  status?: 'pending' | 'approved' | 'rejected';
  comment?: string;
  decided_at?: string | null;
}

export interface SolutionReviewPayload {
  schema_version?: number;
  demand_no?: string;
  requirement_name?: string;
  reviewed_at?: string;
  inputs?: { stage2_artifacts?: SolutionReviewArtifactInput[] };
  whale_review?: SolutionReviewWhaleReview;
  func_solution_parsed?: {
    repos?: SolutionReviewRepoRow[];
    impact_assessment?: SolutionReviewImpactAssessment;
  };
  split_tasks_draft?: SplitTaskDraft[];
  human_review?: SolutionReviewHumanReview;
}

export interface SolutionReviewGetResponse {
  room_id: string;
  scope_id: string;
  payload: SolutionReviewPayload;
  /** 项目空间 ID（来自会议室产品定位，补丁查询必传） */
  project_id?: string;
  project_name?: string;
  intervention_kind?: string;
  blocked?: boolean;
}

export interface PatchVersionItem {
  patchName?: string;
  state?: string;
  closingDate?: string;
}

export async function fetchSolutionReview(
  synapseApiBase: string,
  roomId: string,
): Promise<SolutionReviewGetResponse> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiGet<SolutionReviewGetResponse>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/solution-review`,
  );
}

export async function fetchPatchVersions(
  synapseApiBase: string,
  roomId: string,
  branchVersionIdList: string[],
  projectId?: number | string,
): Promise<{ patches?: PatchVersionItem[] }> {
  const base = synapseApiBase.replace(/\/$/, '');
  const body: Record<string, unknown> = { branch_version_id_list: branchVersionIdList };
  if (projectId !== undefined && projectId !== null && String(projectId).trim() !== '') {
    body.projectId = Number(projectId);
  }
  return apiPost<{ patches?: PatchVersionItem[] }>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/patch-versions`,
    body,
  );
}

export interface SolutionReviewDecisionResult {
  status: string;
  node_id?: string;
  solution_review_payload?: SolutionReviewPayload;
  next_node_id?: string | null;
}

export async function submitSolutionReviewDecision(
  synapseApiBase: string,
  roomId: string,
  body: {
    decision: 'approve' | 'reject';
    comment: string;
    patches?: { branch_version_id: string; patch_name: string }[];
  },
): Promise<SolutionReviewDecisionResult> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPost<SolutionReviewDecisionResult>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/solution-review/decision`,
    body,
  );
}

export async function fetchMeetingRoomLive(
  synapseApiBase: string,
  roomId: string,
  nodeId?: string,
): Promise<MeetingRoomLivePayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const qs = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : '';
  return apiGet<MeetingRoomLivePayload>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/live${qs}`,
  );
}

export interface MeetingRoomNodeChatPayload {
  room_id: string;
  scope_id?: string;
  node_id: string;
  history?: Record<string, unknown>[];
  chat_logs?: MeetingRoomChatLogWire[];
}

export async function fetchMeetingRoomNodeChat(
  synapseApiBase: string,
  roomId: string,
  nodeId: string,
): Promise<MeetingRoomNodeChatPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const qs = `?node_id=${encodeURIComponent(nodeId)}`;
  return apiGet<MeetingRoomNodeChatPayload>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/chat${qs}`,
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
    | 'llm_usage'
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
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  model?: string;
  usage_scene?: string;
  presentation_tier?: 'primary' | 'secondary';
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
  live_node_id?: string;
  host_session_id?: string;
  agents: MeetingAgentContextEntry[];
  sub_agents?: MeetingRoomLivePayload['sub_agents'];
  probed_at?: string;
  dump_path?: string;
}

export async function fetchMeetingAgentContexts(
  synapseApiBase: string,
  roomId: string,
  options?: { messageCharLimit?: number; nodeId?: string },
): Promise<MeetingAgentContextsPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const params = new URLSearchParams();
  if (options?.messageCharLimit != null) {
    params.set('message_char_limit', String(options.messageCharLimit));
  }
  const nodeId = (options?.nodeId || '').trim();
  if (nodeId) {
    params.set('node_id', nodeId);
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

export async function reprocessMeetingRoom(
  synapseApiBase: string,
  roomId: string,
  nodeId?: string,
  reason?: string,
): Promise<MeetingRoomDetail> {
  const base = synapseApiBase.replace(/\/$/, '');
  const body: { node_id?: string; reason?: string } = {};
  if (nodeId) body.node_id = nodeId;
  const trimmedReason = (reason || '').trim();
  if (trimmedReason) body.reason = trimmedReason;
  return apiPost<MeetingRoomDetail>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/reprocess`,
    body,
  );
}

export async function stopMeetingRoom(
  synapseApiBase: string,
  roomId: string,
): Promise<MeetingRoomDetail> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiPost<MeetingRoomDetail>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/stop`,
    {},
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

export async function fetchMeetingNodeParticipants(
  synapseApiBase: string,
  roomId: string,
  nodeId: string,
): Promise<{ node_id: string; participants: MeetingRoomParticipantWire[] }> {
  const base = synapseApiBase.replace(/\/$/, '');
  return apiGet<{ node_id: string; participants: MeetingRoomParticipantWire[] }>(
    base,
    `/api/dev/meeting-rooms/${encodeURIComponent(roomId)}/nodes/${encodeURIComponent(nodeId)}/participants`,
  );
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

/** meeting-summary archive_index 曾用 archive 内相对路径；artifact-file 需要 scope 根下路径。 */
export function normalizeArtifactRelativePath(path: string): string {
  const p = (path || '').trim().replace(/\\/g, '/').replace(/^\/+/, '');
  if (!p || p.startsWith('archive/') || p.includes('..')) return p;
  return `archive/${p}`;
}

export async function fetchArtifactFile(
  synapseApiBase: string,
  roomId: string,
  path: string,
): Promise<ArtifactFileContent> {
  const base = synapseApiBase.replace(/\/$/, '');
  const params = new URLSearchParams({ path: normalizeArtifactRelativePath(path) });
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
