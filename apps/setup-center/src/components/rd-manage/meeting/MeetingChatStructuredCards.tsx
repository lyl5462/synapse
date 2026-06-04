import React, { useMemo } from 'react';
import {
  Bot,
  CheckCircle2,
  ClipboardList,
  Database,
  FileText,
  FolderGit2,
  Hand,
  Server,
  Users,
  XCircle,
} from 'lucide-react';
import { ALL_NODES } from '../../../rd-sop/constants';
import { interventionKindLabel } from './meetingInterventionPanel';
import { ReviewMarkdown } from './ReviewMarkdown';
import {
  HOST_PROFILE_ID,
  MeetingAgentAvatar,
  stubWorkerAgent,
} from './MeetingAgentAvatar';
import type { RoomAgent } from './meetingChatTypes';
import type { ChatDisplayKind, MeetingChatLog } from './meetingChatUtils';

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rd-chat-card__title">
      <span className="rd-chat-card__title-icon">{icon}</span>
      <span>{children}</span>
    </div>
  );
}

export function NodeContextCard({ payload }: { payload: Record<string, unknown> }) {
  const order = (payload.order || {}) as Record<string, unknown>;
  const product = (payload.product || {}) as Record<string, unknown>;
  const system = (payload.system || {}) as Record<string, unknown>;
  const repos = Array.isArray(product.repos) ? product.repos : [];
  const docs = Array.isArray(product.docs) ? product.docs : [];

  return (
    <div className="rd-chat-card rd-chat-card--context">
      <SectionTitle icon={<FileText className="w-4 h-4" />}>节点基础信息</SectionTitle>
      <div className="rd-chat-card__section">
        <div className="rd-chat-card__label">工单</div>
        <div className="rd-chat-card__mono">{String(order.id || '—')}</div>
        <div className="rd-chat-card__emph">{String(order.title || '—')}</div>
        {order.prod ? (
          <div className="rd-chat-card__tag">产品：{String(order.prod)}</div>
        ) : null}
        {order.description ? (
          <p className="rd-chat-card__desc">
            {String(order.description).length > 360
              ? `${String(order.description).slice(0, 360)}…`
              : String(order.description)}
          </p>
        ) : null}
      </div>
      <div className="rd-chat-card__section">
        <div className="rd-chat-card__label">产品定位</div>
        <div className="rd-chat-card__emph">{String(product.prod || product.locator_message || '—')}</div>
        <div className="rd-chat-card__meta-row">
          <span>版本 {String(product.version || '—')}</span>
          <span>模块 {String(product.module || '—')}</span>
        </div>
        <div className="rd-chat-card__meta-row">
          <span>
            <FolderGit2 className="w-3 h-3 inline mr-1" />
            代码库 {repos.length}
          </span>
          <span>
            <Database className="w-3 h-3 inline mr-1" />
            文档 {docs.length}
          </span>
        </div>
      </div>
      {Object.keys(system).length > 0 ? (
        <div className="rd-chat-card__section">
          <div className="rd-chat-card__label">系统路径</div>
          <dl className="rd-chat-card__kv">
            {Object.entries(system)
              .slice(0, 6)
              .map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt>{k}</dt>
                  <dd className="truncate" title={String(v)}>
                    {String(v)}
                  </dd>
                </React.Fragment>
              ))}
          </dl>
        </div>
      ) : null}
    </div>
  );
}

const HOST_ROSTER_AGENT: RoomAgent = {
  id: HOST_PROFILE_ID,
  name: '小鲸',
  role: '会议主持',
  avatarColor: 'bg-violet-500',
  icon: <Bot className="w-3.5 h-3.5" />,
  status: 'idle',
  currentAction: '主持',
};

function resolveWorkerRoster(
  payload: Record<string, unknown>,
): { hostId: string; workers: RoomAgent[] } {
  const hostId = String(payload.host_profile_id || HOST_PROFILE_ID);
  const rawParts =
    (payload.participants as { profile_id?: string; display_name?: string; role?: string }[]) || [];
  const workerIds = (payload.worker_profile_ids as string[]) || [];

  const seen = new Set<string>();
  const workers: RoomAgent[] = [];

  const addWorker = (profileId: string, displayName?: string) => {
    const pid = profileId.trim();
    if (!pid || pid === hostId || seen.has(pid)) return;
    seen.add(pid);
    const label = (displayName || '').trim();
    workers.push(
      stubWorkerAgent(
        pid,
        label && label !== pid ? label : undefined,
      ),
    );
  };

  for (const p of rawParts) {
    const pid = String(p.profile_id || '');
    const role = String(p.role || '').toLowerCase();
    if (role === 'host' || pid === hostId) continue;
    addWorker(pid, p.display_name);
  }
  for (const id of workerIds) {
    addWorker(String(id));
  }

  return { hostId, workers };
}

export function ParticipantsCard({ payload }: { payload: Record<string, unknown> }) {
  const { workers } = useMemo(() => resolveWorkerRoster(payload), [payload]);
  if (payload.system_node) {
    return <SystemRosterCard payload={payload} />;
  }

  return (
    <div className="rd-chat-card rd-chat-card--roster">
      <SectionTitle icon={<Users className="w-4 h-4" />}>参会人员名单</SectionTitle>
      <div className="rd-chat-card__meta-row rd-roster-meta">
        <span className="font-mono text-[11px]">节点 {String(payload.node_id || '—')}</span>
      </div>
      <ul className="rd-roster-list">
        <li className="rd-roster-item rd-roster-item--host">
          <MeetingAgentAvatar agent={HOST_ROSTER_AGENT} size="small" showStatusBadge={false} />
          <div className="rd-roster-item__text">
            <span className="rd-roster-item__name">小鲸</span>
            <span className="rd-roster-item__role">会议主持</span>
          </div>
          <span className="rd-roster-item__badge rd-roster-item__badge--host">主持</span>
        </li>
        {workers.map((agent) => (
          <li key={agent.id} className="rd-roster-item">
            <MeetingAgentAvatar agent={agent} size="small" showStatusBadge={false} />
            <div className="rd-roster-item__text">
              <span className="rd-roster-item__name">{agent.name}</span>
              <span className="rd-roster-item__role font-mono text-[10px]">{agent.id}</span>
            </div>
            <span className={`rd-roster-item__dot ${agent.avatarColor}`} title={agent.id} />
          </li>
        ))}
      </ul>
      {workers.length === 0 ? (
        <p className="rd-chat-card__desc mt-2">暂无协作智能体，仅小鲸主持本节点。</p>
      ) : null}
    </div>
  );
}

export function SystemRosterCard({ payload }: { payload: Record<string, unknown> }) {
  return (
    <div className="rd-chat-card rd-chat-card--roster">
      <SectionTitle icon={<Server className="w-4 h-4" />}>系统执行方</SectionTitle>
      <div className="rd-chat-card__meta-row rd-roster-meta">
        <span className="font-mono text-[11px]">节点 {String(payload.node_id || '—')}</span>
      </div>
      <ul className="rd-roster-list">
        <li className="rd-roster-item">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-500/40 bg-slate-500/15 text-slate-300">
            <Server className="h-4 w-4" />
          </span>
          <div className="rd-roster-item__text">
            <span className="rd-roster-item__name">系统</span>
            <span className="rd-roster-item__role">脚本执行 · 无大模型</span>
          </div>
          <span className="rd-roster-item__badge">system</span>
        </li>
      </ul>
      <p className="rd-chat-card__desc mt-2">本节点由 Pipeline 代码 handler 执行，不调度主持/协作智能体。</p>
    </div>
  );
}

export function SystemExecCard({ payload }: { payload: Record<string, unknown> }) {
  const repos = (payload.repos as Record<string, unknown>[]) || [];
  return (
    <div className="rd-chat-card rd-chat-card--meta">
      <SectionTitle icon={<Server className="w-4 h-4" />}>系统节点执行结果</SectionTitle>
      <dl className="rd-chat-card__kv">
        <dt>状态</dt>
        <dd>{String(payload.status || '—')}</dd>
        <dt>沙箱目录</dt>
        <dd className="font-mono text-[11px] break-all">{String(payload.sandbox_root || '—')}</dd>
        {payload.prod ? (
          <>
            <dt>产品</dt>
            <dd>{String(payload.prod)}</dd>
          </>
        ) : null}
        {payload.error ? (
          <>
            <dt>错误</dt>
            <dd className="text-red-400">{String(payload.error)}</dd>
          </>
        ) : null}
      </dl>
      {repos.length > 0 ? (
        <ul className="text-[11px] text-muted-foreground space-y-1.5 mt-3 mb-0">
          {repos.map((row, idx) => (
            <li key={`${row.repo_name}-${idx}`} className="font-mono break-all">
              {String(row.repo_name || 'repo')} → {String(row.local_path || '—')} ({String(row.status || '—')})
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function unwrapMarkdownBody(text: string): string {
  const raw = (text || '').trim();
  if (!raw.startsWith('{')) return raw;
  try {
    const obj = JSON.parse(raw) as { message?: string };
    if (typeof obj.message === 'string' && obj.message.trim()) {
      return obj.message.trim();
    }
  } catch {
    /* 非 JSON，按 Markdown 原文展示 */
  }
  return raw;
}

export function WorkPlanCard({ text }: { text: string }) {
  const md = unwrapMarkdownBody(text);
  return (
    <div className="rd-chat-card rd-chat-card--plan">
      <SectionTitle icon={<ClipboardList className="w-4 h-4" />}>工作安排计划</SectionTitle>
      <ReviewMarkdown content={md} compact className="rd-meeting-chat-markdown" />
    </div>
  );
}

export function DelegationStartCard({
  text,
  payload,
}: {
  text: string;
  payload?: Record<string, unknown>;
}) {
  const headline = String(payload?.headline || text.split('\n')[0] || '');
  const task = String(payload?.task_preview || '');
  const plan = String(payload?.plan_item_id || '');
  const reason = String(payload?.reason || '');
  const taskLine = text.split('\n').find((l) => l.startsWith('任务：'));

  return (
    <div className="rd-chat-card rd-chat-card--delegation-start">
      <SectionTitle icon={<Bot className="w-4 h-4" />}>工作委派</SectionTitle>
      <p className="rd-chat-card__emph">{headline}</p>
      {plan ? <div className="rd-chat-card__tag">计划项 {plan}</div> : null}
      {reason ? <p className="rd-chat-card__desc">原因：{reason}</p> : null}
      <pre className="rd-chat-card__preview">{task || taskLine?.replace(/^任务：\s*/, '') || text}</pre>
    </div>
  );
}

export function DelegationDoneCard({
  text,
  payload,
}: {
  text: string;
  payload?: Record<string, unknown>;
}) {
  const ok = payload?.ok !== false;
  const headline = String(payload?.headline || text.split('\n')[0] || '');
  const summary = String(payload?.result_summary || '');

  return (
    <div className={`rd-chat-card rd-chat-card--delegation-done ${ok ? 'is-ok' : 'is-fail'}`}>
      <SectionTitle
        icon={ok ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <XCircle className="w-4 h-4 text-red-400" />}
      >
        协作完成
      </SectionTitle>
      <p className="rd-chat-card__emph">{headline}</p>
      {summary ? <pre className="rd-chat-card__preview">{summary.slice(0, 1200)}</pre> : null}
    </div>
  );
}

export function HumanReportCard({ payload, text }: { payload: Record<string, unknown>; text: string }) {
  const preview = String(payload.report_preview || text || '');
  const success = payload.success !== false;

  return (
    <div className="rd-chat-card rd-chat-card--report">
      <SectionTitle icon={<Server className="w-4 h-4" />}>人工确认 / 交付摘要</SectionTitle>
      <div className={`rd-chat-card__status ${success ? 'is-ok' : 'is-warn'}`}>
        {success ? '等待人工确认' : '需关注'}
      </div>
      <p className="rd-chat-card__desc">{preview}</p>
    </div>
  );
}

export function HitlToolCard({ text }: { text: string }) {
  return (
    <div className="rd-chat-card rd-chat-card--hitl">
      <SectionTitle icon={<Bot className="w-4 h-4" />}>问卷提交</SectionTitle>
      <p className="rd-chat-card__desc">{text}</p>
    </div>
  );
}

export function PendingConfirmCard({ payload, text }: { payload: Record<string, unknown>; text: string }) {
  return (
    <div className="rd-chat-card rd-chat-card--pending">
      <SectionTitle icon={<Bot className="w-4 h-4" />}>等待问卷反馈</SectionTitle>
      <p className="rd-chat-card__desc">{text}</p>
      <dl className="rd-chat-card__kv">
        {payload.duration_seconds != null ? (
          <>
            <dt>耗时</dt>
            <dd>{String(payload.duration_seconds)}s</dd>
          </>
        ) : null}
        {payload.dynamic_form != null ? (
          <>
            <dt>动态问卷</dt>
            <dd>{payload.dynamic_form ? '是' : '否'}</dd>
          </>
        ) : null}
        {payload.source ? (
          <>
            <dt>来源</dt>
            <dd>{String(payload.source)}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

function sopNodeLabel(nodeId: string): string {
  const nid = nodeId.trim();
  if (!nid) return '';
  return ALL_NODES.find((n) => n.id === nid)?.name || nid;
}

export function HumanGateCard({
  payload,
  title,
}: {
  payload: Record<string, unknown>;
  title: string;
}) {
  const nodeId = String(payload.node_id || '').trim();
  const nodeLabel =
    String(payload.node_label || '').trim() || sopNodeLabel(nodeId) || nodeId || '—';
  const kindLabel =
    String(payload.intervention_kind_label || '').trim() ||
    interventionKindLabel(String(payload.intervention_kind || ''));
  const reason = String(payload.reason || title || '').trim();

  return (
    <div className="rd-chat-card rd-chat-card--gate">
      <SectionTitle icon={<Hand className="w-4 h-4" />}>{title.split('\n')[0] || '人工门控'}</SectionTitle>
      {reason && reason !== title.split('\n')[0] ? (
        <p className="rd-chat-card__desc">{reason}</p>
      ) : null}
      <dl className="rd-chat-card__kv">
        {nodeId ? (
          <>
            <dt>节点</dt>
            <dd>
              {nodeLabel}
              <span className="rd-chat-card__mono"> ({nodeId})</span>
            </dd>
          </>
        ) : null}
        {kindLabel ? (
          <>
            <dt>门控类型</dt>
            <dd>{kindLabel}</dd>
          </>
        ) : null}
        {payload.duration_seconds != null ? (
          <>
            <dt>已运行</dt>
            <dd>{String(payload.duration_seconds)}s</dd>
          </>
        ) : null}
        {payload.tokens_used != null ? (
          <>
            <dt>Token</dt>
            <dd>{String(payload.tokens_used)}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

export function SolutionReviewGateCard({
  payload,
  title,
}: {
  payload: Record<string, unknown>;
  title: string;
}) {
  return <HumanGateCard payload={payload} title={title || '方案评审门控'} />;
}

export function FlowMetaCard({ payload, title }: { payload: Record<string, unknown>; title: string }) {
  const keys = Object.keys(payload)
    .filter((k) => !['message', 'tokens_used', 'tokens_used_hint', 'tokens_note'].includes(k))
    .slice(0, 8);
  return (
    <div className="rd-chat-card rd-chat-card--meta">
      <SectionTitle icon={<Server className="w-4 h-4" />}>{title}</SectionTitle>
      <dl className="rd-chat-card__kv">
        {keys.map((k) => (
          <React.Fragment key={k}>
            <dt>{k}</dt>
            <dd className="truncate" title={String(payload[k])}>
              {typeof payload[k] === 'object' ? JSON.stringify(payload[k]) : String(payload[k])}
            </dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
}

export function StructuredChatBody({ log }: { log: MeetingChatLog }) {
  const kind = log.displayKind;
  const payload = log.payload || {};

  switch (kind as ChatDisplayKind) {
    case 'node_context':
      return <NodeContextCard payload={payload} />;
    case 'participants':
      return <ParticipantsCard payload={payload} />;
    case 'system_roster':
      return <SystemRosterCard payload={payload} />;
    case 'system_exec':
      return <SystemExecCard payload={payload} />;
    case 'work_plan':
      return <WorkPlanCard text={log.text} />;
    case 'delegation_start':
      return <DelegationStartCard text={log.text} payload={payload} />;
    case 'delegation_done':
      return <DelegationDoneCard text={log.text} payload={payload} />;
    case 'human_report':
      return <HumanReportCard payload={payload} text={log.text} />;
    case 'hitl_tool':
      return <HitlToolCard text={log.text} />;
    case 'pending_confirm':
      return <PendingConfirmCard payload={payload} text={log.text} />;
    case 'human_gate':
      return <HumanGateCard payload={payload} title={log.text} />;
    case 'solution_review_gate':
      return <SolutionReviewGateCard payload={payload} title={log.text} />;
    case 'flow_meta':
      return <FlowMetaCard payload={payload} title={log.text || '流程元数据'} />;
    default:
      return null;
  }
}
