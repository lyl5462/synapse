/** 协作会议流：消息分类与 SOP 作用域过滤 */

export type ChatSpeakerRole = 'system' | 'host' | 'worker' | 'user';

export type ChatDisplayKind =
  | 'node_context'
  | 'participants'
  | 'system_roster'
  | 'system_exec'
  | 'work_plan'
  | 'delegation_start'
  | 'delegation_done'
  | 'human_report'
  | 'hitl_tool'
  | 'pending_confirm'
  | 'human_gate'
  | 'solution_review_gate'
  | 'flow_meta'
  | 'pipeline'
  | 'plain';

export interface MeetingChatLog {
  id: string;
  agentId: string;
  text: string;
  timestamp: string;
  type: 'info' | 'error' | 'success' | 'warning' | 'user';
  rich?: boolean;
  nodeId?: string;
  /** 后端 history event */
  event?: string;
  /** 发言角色（优先于 agentId 展示） */
  speakerRole?: ChatSpeakerRole;
  /** 结构化卡片类型 */
  displayKind?: ChatDisplayKind;
  payload?: Record<string, unknown>;
}

export type MeetingChatKind =
  | 'user'
  | 'system'
  | 'pipeline'
  | 'rich'
  | 'delegation'
  | 'status'
  | 'agent'
  | 'structured';

const PIPELINE_TITLE_RE =
  /^(开启会议室|节点初始化|系统节点初始化|系统节点执行|主控提示词组装|流程待机|主控触发执行|主控触发总结|\*\*流程迁移|【步骤)/;

const STRUCTURED_KINDS: ChatDisplayKind[] = [
  'node_context',
  'participants',
  'system_roster',
  'system_exec',
  'work_plan',
  'delegation_start',
  'delegation_done',
  'human_report',
  'hitl_tool',
  'pending_confirm',
  'human_gate',
  'solution_review_gate',
  'flow_meta',
];

export function isStructuredDisplayKind(kind?: ChatDisplayKind): boolean {
  return !!kind && STRUCTURED_KINDS.includes(kind);
}

export function classifyMeetingChat(log: MeetingChatLog): MeetingChatKind {
  if (log.displayKind && isStructuredDisplayKind(log.displayKind)) return 'structured';
  if (log.speakerRole === 'system' && log.displayKind === 'pipeline') return 'pipeline';
  if (log.type === 'user' || log.speakerRole === 'user') return 'user';
  const t0 = (log.text || '').trim();
  if (/^已进入 SOP 节点：/.test(t0)) return 'system';
  if (log.rich) return 'rich';
  if (log.type === 'error' || log.type === 'warning' || log.type === 'success') return 'status';
  const t = (log.text || '').trim();
  if (!t) return 'agent';
  if (
    /小鲸已委派|协作智能体已返回|委派内容：/.test(t) ||
    /^计划项：/.test(t.split('\n')[1] || '')
  ) {
    return 'delegation';
  }
  const firstLine = t.split('\n')[0]?.trim() || '';
  if (PIPELINE_TITLE_RE.test(firstLine) || PIPELINE_TITLE_RE.test(t)) return 'pipeline';
  if (/^# 工作安排计划/.test(t)) return 'rich';
  if (/^会议室流程日志/.test(t)) return 'system';
  return 'agent';
}

export function resolveChatSpeakerName(log: MeetingChatLog, agentName?: string): string {
  const role = log.speakerRole;
  if (role === 'system') return '系统';
  if (role === 'user' || log.type === 'user') return '我 (人类专家)';
  if (role === 'host') return agentName && agentName !== log.agentId ? agentName : '小鲸';
  if (role === 'worker') return agentName || '协作智能体';
  if (log.agentId === 'system') return '系统';
  return agentName || '小鲸';
}

export function shouldShowChatAvatar(log: MeetingChatLog): boolean {
  if (log.type === 'user' || log.speakerRole === 'user') return false;
  if (log.speakerRole === 'system' || isStructuredDisplayKind(log.displayKind)) return true;
  const kind = classifyMeetingChat(log);
  return kind !== 'system';
}

/** 流程类消息：首行标题 + 正文 */
export function splitPipelineMessage(text: string): { title: string; body: string } {
  const lines = (text || '').trim().split('\n');
  const title = (lines[0] || '').trim();
  const body = lines.slice(1).join('\n').trim();
  return { title, body };
}

/** 委派类消息：解析结构化字段 */
export function parseDelegationMessage(text: string): {
  headline: string;
  plan?: string;
  reason?: string;
  preview?: string;
} {
  const lines = (text || '').split('\n');
  const headline = (lines[0] || '').trim();
  let plan: string | undefined;
  let reason: string | undefined;
  const previewIdx = lines.findIndex((l) => l.startsWith('委派内容：'));
  for (const line of lines.slice(1)) {
    if (line.startsWith('计划项：')) plan = line.replace(/^计划项：\s*/, '').trim();
    else if (line.startsWith('原因：')) reason = line.replace(/^原因：\s*/, '').trim();
  }
  let preview: string | undefined;
  if (previewIdx >= 0) {
    preview = lines
      .slice(previewIdx)
      .join('\n')
      .replace(/^委派内容：\s*/, '')
      .trim();
  }
  return { headline, plan, reason, preview };
}

export function sopScopeKey(stageIndex: number, nodeId: string): string {
  return `${stageIndex}:${(nodeId || 'pending').trim()}`;
}

/** 按 SOP 节点精确过滤：优先只展示 nodeId 匹配的条目；无标签订阅时用截断逻辑。 */
export function filterLogsForNodeExact(logs: MeetingChatLog[], nodeId: string): MeetingChatLog[] {
  const nid = (nodeId || 'pending').trim();
  if (!nid || !logs.length) return logs;

  const hasTagged = logs.some((l) => (l.nodeId || '').trim());
  if (hasTagged) {
    const matched = logs.filter((l) => (l.nodeId || '').trim() === nid);
    if (matched.length) return matched;
    return filterLogsForSopNode(logs, nid);
  }

  return filterLogsForSopNode(logs, nid);
}

/** 合并协作流日志（按 id 去重，保留既有顺序并追加新条目） */
export function mergeChatLogs(existing: MeetingChatLog[], incoming: MeetingChatLog[]): MeetingChatLog[] {
  if (!incoming.length) return existing;
  const byId = new Map(existing.map((l) => [l.id, l]));
  const order = existing.map((l) => l.id);
  for (const l of incoming) {
    if (!byId.has(l.id)) order.push(l.id);
    byId.set(l.id, l);
  }
  return order.map((id) => byId.get(id)!);
}

/** @deprecated 使用 filterLogsForNodeExact；保留兼容旧截断逻辑 */
export function filterLogsForSopNode(logs: MeetingChatLog[], nodeId: string): MeetingChatLog[] {
  const nid = (nodeId || 'pending').trim();
  if (!nid || !logs.length) return logs;

  const tagged = logs.some((l) => l.nodeId);
  if (tagged) {
    let start = -1;
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].nodeId === nid) {
        start = i;
        break;
      }
    }
    if (start < 0) return [];
    return logs.slice(start).filter((l) => !l.nodeId || l.nodeId === nid);
  }

  // 无 nodeId：从最后一次「节点开始」类流程消息起截断
  let start = -1;
  for (let i = logs.length - 1; i >= 0; i--) {
    const first = (logs[i].text || '').split('\n')[0]?.trim() || '';
    if (first.startsWith('节点初始化') || first.includes(nid)) {
      start = i;
      break;
    }
  }
  return start >= 0 ? logs.slice(start) : [];
}

export function makeSopScopeDividerLog(
  nodeId: string,
  stageName: string,
  nodeName?: string,
): MeetingChatLog {
  const label = nodeName ? `${stageName} · ${nodeName}` : `${stageName} · ${nodeId}`;
  return {
    id: `sop-scope-${nodeId}-${Date.now()}`,
    agentId: 'system',
    speakerRole: 'system',
    displayKind: 'pipeline',
    text: `已进入 SOP 节点：${label}`,
    timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    type: 'info',
  };
}
