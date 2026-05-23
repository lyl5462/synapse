import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Drawer, Empty, Segmented, Spin, Tag, Tooltip } from 'antd';
import {
  Activity,
  Bot,
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Copy,
  Cpu,
  FileCode2,
  Hash,
  Loader2,
  MessageSquareText,
  RefreshCw,
  ScrollText,
  Sparkles,
  Terminal,
  User as UserIcon,
  Wrench,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  fetchMeetingAgentContexts,
  type MeetingAgentContextEntry,
  type MeetingAgentContextsPayload,
  type SkillExecutionEntry,
} from '../../../api/meetingRoomService';

export interface AgentContextTarget {
  profileId: string;
  name: string;
  role: string;
  isHost?: boolean;
  avatarColor?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  synapseApiBase: string;
  roomId: string;
  agent: AgentContextTarget | null;
}

type MsgRole = 'system' | 'user' | 'assistant' | 'tool' | 'unknown';

interface NormalizedMessage {
  index: number;
  role: MsgRole;
  text: string;
  toolName?: string;
  isToolResult?: boolean;
  hasToolUse?: boolean;
}

function detectRole(raw: unknown): MsgRole {
  const r = String(raw || '').toLowerCase();
  if (r === 'system' || r === 'user' || r === 'assistant' || r === 'tool') return r;
  return 'unknown';
}

function normalizeMessage(msg: Record<string, unknown>, index: number): NormalizedMessage {
  const role = detectRole(msg.role);
  const content = msg.content;
  let text = '';
  let toolName: string | undefined;
  let isToolResult = false;
  let hasToolUse = false;

  if (typeof content === 'string') {
    text = content;
  } else if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const part of content) {
      if (!part || typeof part !== 'object') {
        parts.push(String(part ?? ''));
        continue;
      }
      const p = part as Record<string, unknown>;
      const t = String(p.type || '');
      if (t === 'text' && typeof p.text === 'string') {
        parts.push(p.text);
      } else if (t === 'tool_use') {
        hasToolUse = true;
        toolName = String(p.name || toolName || '');
        try {
          parts.push(`🔧 [tool_use] ${toolName}\n${JSON.stringify(p.input ?? {}, null, 2)}`);
        } catch {
          parts.push(`🔧 [tool_use] ${toolName}`);
        }
      } else if (t === 'tool_result') {
        isToolResult = true;
        const inner = p.content;
        if (typeof inner === 'string') {
          parts.push(`📎 [tool_result]\n${inner}`);
        } else {
          try {
            parts.push(`📎 [tool_result]\n${JSON.stringify(inner, null, 2)}`);
          } catch {
            parts.push('📎 [tool_result]');
          }
        }
      } else {
        try {
          parts.push(JSON.stringify(p, null, 2));
        } catch {
          parts.push(String(p));
        }
      }
    }
    text = parts.join('\n\n');
  } else if (content != null) {
    try {
      text = JSON.stringify(content, null, 2);
    } catch {
      text = String(content);
    }
  }

  return { index, role, text, toolName, isToolResult, hasToolUse };
}

const ROLE_META: Record<
  MsgRole,
  { label: string; icon: React.ReactNode; chip: string; bar: string }
> = {
  system: {
    label: 'System',
    icon: <Sparkles className="w-3 h-3" />,
    chip: 'bg-violet-500/15 text-violet-300 border border-violet-500/30',
    bar: 'bg-violet-500/70',
  },
  user: {
    label: 'User',
    icon: <UserIcon className="w-3 h-3" />,
    chip: 'bg-blue-500/15 text-blue-300 border border-blue-500/30',
    bar: 'bg-blue-500/70',
  },
  assistant: {
    label: 'Assistant',
    icon: <Bot className="w-3 h-3" />,
    chip: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30',
    bar: 'bg-emerald-500/70',
  },
  tool: {
    label: 'Tool',
    icon: <Wrench className="w-3 h-3" />,
    chip: 'bg-amber-500/15 text-amber-300 border border-amber-500/30',
    bar: 'bg-amber-500/70',
  },
  unknown: {
    label: 'Other',
    icon: <Hash className="w-3 h-3" />,
    chip: 'bg-muted text-muted-foreground border border-border/60',
    bar: 'bg-muted',
  },
};

function copy(text: string) {
  if (!text) return;
  void navigator.clipboard
    .writeText(text)
    .then(() => toast.success('已复制'))
    .catch(() => toast.error('复制失败'));
}

function CollapsibleBlock({
  title,
  text,
  icon,
  defaultOpen = true,
  emptyHint,
  mono = true,
  maxHeight = 320,
}: {
  title: string;
  text: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  emptyHint?: string;
  mono?: boolean;
  maxHeight?: number;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const trimmed = text.trim();
  return (
    <div className="rounded-xl border border-border/60 bg-[color:var(--panel,#1c1c1f)]/60 backdrop-blur-sm overflow-hidden">
      <div
        className="px-3 py-2 border-b border-border/40 flex items-center justify-between cursor-pointer select-none hover:bg-muted/30 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center gap-2 text-xs font-medium text-foreground/90">
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          {icon}
          <span>{title}</span>
          {trimmed ? (
            <span className="font-mono text-[10px] text-muted-foreground/70">
              {trimmed.length.toLocaleString()} 字符
            </span>
          ) : null}
        </div>
        {trimmed ? (
          <Tooltip title="复制全文">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                copy(text);
              }}
              className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded hover:bg-muted/50"
            >
              <Copy className="w-3 h-3" />
            </button>
          </Tooltip>
        ) : null}
      </div>
      {open ? (
        trimmed ? (
          <pre
            className={`p-3 text-[11.5px] leading-[1.55] whitespace-pre-wrap break-words text-foreground/85 overflow-y-auto custom-scrollbar ${
              mono ? 'font-mono' : ''
            }`}
            style={{ maxHeight }}
          >
            {text}
          </pre>
        ) : (
          <p className="p-4 text-xs text-muted-foreground text-center">
            {emptyHint || '（空）'}
          </p>
        )
      ) : null}
    </div>
  );
}

function MessageCard({ msg }: { msg: NormalizedMessage }) {
  const meta = ROLE_META[msg.role];
  const [expanded, setExpanded] = useState(msg.text.length < 1500);
  const preview =
    expanded || msg.text.length < 1500
      ? msg.text
      : msg.text.slice(0, 1500) + `\n\n…（点击展开剩余 ${msg.text.length - 1500} 字符）`;

  return (
    <div className="group relative pl-3">
      <div className={`absolute left-0 top-0 bottom-0 w-[3px] rounded-full ${meta.bar}`} />
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium ${meta.chip}`}
        >
          {meta.icon}
          {meta.label}
        </span>
        <span className="text-[10px] font-mono text-muted-foreground/70">#{msg.index + 1}</span>
        {msg.toolName ? (
          <span className="text-[10px] text-amber-300/90 font-mono">tool: {msg.toolName}</span>
        ) : null}
        {msg.isToolResult ? (
          <span className="text-[10px] text-amber-300/90">tool_result</span>
        ) : null}
        <span className="ml-auto text-[10px] text-muted-foreground/70 font-mono">
          {msg.text.length.toLocaleString()}
        </span>
        <Tooltip title="复制本条">
          <button
            type="button"
            onClick={() => copy(msg.text)}
            className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground p-0.5"
          >
            <Copy className="w-3 h-3" />
          </button>
        </Tooltip>
      </div>
      <pre
        onClick={() => {
          if (!expanded && msg.text.length >= 1500) setExpanded(true);
        }}
        className={`text-[11.5px] leading-[1.55] whitespace-pre-wrap break-words font-mono text-foreground/85 rounded-lg border border-border/40 bg-muted/20 p-2.5 ${
          !expanded && msg.text.length >= 1500 ? 'cursor-pointer hover:bg-muted/30' : ''
        }`}
      >
        {preview || <span className="text-muted-foreground italic">（空消息）</span>}
      </pre>
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex-1 min-w-[88px] rounded-lg border border-border/50 bg-muted/20 px-2.5 py-2">
      <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
        {icon}
        {label}
      </div>
      <div className="text-xs font-semibold text-foreground/90 mt-0.5 truncate">{value}</div>
    </div>
  );
}

interface SkillAggRow {
  skill: string;
  count: number;
  lastTs: number;
  lastScript: string;
  tools: string[];
  scripts: string[];
}

function aggregateSkills(items: SkillExecutionEntry[]): SkillAggRow[] {
  const map = new Map<string, SkillAggRow>();
  for (const it of items || []) {
    const key = (it.skill || '').trim();
    if (!key) continue;
    const existing = map.get(key);
    const ts = Number(it.ts || 0);
    if (!existing) {
      map.set(key, {
        skill: key,
        count: 1,
        lastTs: ts,
        lastScript: (it.script || '').trim(),
        tools: it.tool ? [it.tool] : [],
        scripts: it.script ? [it.script] : [],
      });
      continue;
    }
    existing.count += 1;
    if (ts > existing.lastTs) {
      existing.lastTs = ts;
      if (it.script) existing.lastScript = it.script;
    }
    if (it.tool && !existing.tools.includes(it.tool)) existing.tools.push(it.tool);
    if (it.script && !existing.scripts.includes(it.script)) existing.scripts.push(it.script);
  }
  return Array.from(map.values()).sort((a, b) => {
    if (b.count !== a.count) return b.count - a.count;
    return b.lastTs - a.lastTs;
  });
}

function formatRelativeTime(ts: number): string {
  if (!ts) return '';
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60) return `${Math.round(diff)}s 前`;
  if (diff < 3600) return `${Math.round(diff / 60)}m 前`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h 前`;
  return `${Math.round(diff / 86400)}d 前`;
}

/** 「已使用 SKILL」聚合卡片：按 skill 分组，count desc，前 8 条 + 折叠剩余。 */
function SkillUsageCard({ entries }: { entries: SkillExecutionEntry[] }) {
  const [showAll, setShowAll] = useState(false);
  const rows = useMemo(() => aggregateSkills(entries || []), [entries]);
  const total = entries?.length || 0;

  if (!rows.length) {
    return (
      <div className="rounded-xl border border-border/60 bg-[color:var(--panel,#1c1c1f)]/60 overflow-hidden">
        <div className="px-3 py-2 border-b border-border/40 flex items-center gap-2 text-xs font-medium text-foreground/90">
          <Sparkles className="w-3 h-3 text-amber-400" />
          <span>已使用 SKILL</span>
          <span className="font-mono text-[10px] text-muted-foreground/70">0 次</span>
        </div>
        <p className="p-4 text-xs text-muted-foreground text-center">
          本任务暂未触发 SKILL 类工具（
          <span className="font-mono">get_skill_info</span>
          {' / '}
          <span className="font-mono">run_skill_script</span> 等）
        </p>
      </div>
    );
  }

  const maxCount = rows[0].count;
  const visible = showAll ? rows : rows.slice(0, 8);
  const hidden = rows.length - visible.length;

  return (
    <div className="rounded-xl border border-border/60 bg-[color:var(--panel,#1c1c1f)]/60 overflow-hidden">
      <div className="px-3 py-2 border-b border-border/40 flex items-center gap-2 text-xs font-medium text-foreground/90">
        <Sparkles className="w-3 h-3 text-amber-400" />
        <span>已使用 SKILL</span>
        <span className="font-mono text-[10px] text-muted-foreground/70">
          {rows.length} 个 · 共 {total} 次
        </span>
      </div>
      <div className="p-3 space-y-2">
        {visible.map((row) => {
          const pct = Math.max(8, Math.round((row.count / Math.max(1, maxCount)) * 100));
          return (
            <div
              key={row.skill}
              className="group relative rounded-lg border border-border/40 bg-muted/10 hover:bg-muted/20 transition-colors px-2.5 py-2"
            >
              {/* 频次背景条 */}
              <div
                className="absolute inset-y-0 left-0 rounded-lg bg-gradient-to-r from-amber-500/15 via-amber-500/8 to-transparent pointer-events-none"
                style={{ width: `${pct}%` }}
              />
              <div className="relative flex items-center gap-2 flex-wrap">
                <Terminal className="w-3 h-3 text-amber-400 shrink-0" />
                <span
                  className="font-mono text-[11.5px] text-foreground/95 truncate max-w-[260px]"
                  title={row.skill}
                >
                  {row.skill}
                </span>
                <span className="text-[10px] font-semibold text-amber-300/95 font-mono">
                  ×{row.count}
                </span>
                {row.lastTs ? (
                  <span className="text-[10px] text-muted-foreground/70 font-mono">
                    {formatRelativeTime(row.lastTs)}
                  </span>
                ) : null}
                <Tooltip title="复制 skill 名">
                  <button
                    type="button"
                    onClick={() => copy(row.skill)}
                    className="ml-auto opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground p-0.5 transition-opacity"
                  >
                    <Copy className="w-3 h-3" />
                  </button>
                </Tooltip>
              </div>
              {(row.lastScript || row.scripts.length > 1 || row.tools.length > 1) && (
                <div className="relative flex items-center gap-1.5 mt-1 text-[10px] text-muted-foreground/85 font-mono flex-wrap">
                  {row.lastScript ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-200/90 border border-amber-500/20">
                      <FileCode2 className="w-2.5 h-2.5" />
                      {row.lastScript}
                      {row.scripts.length > 1 ? (
                        <span className="opacity-70">+{row.scripts.length - 1}</span>
                      ) : null}
                    </span>
                  ) : null}
                  {row.tools.length > 0 ? (
                    <span className="text-muted-foreground/70">
                      via {row.tools.join(', ')}
                    </span>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
        {hidden > 0 && !showAll ? (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="w-full text-[11px] text-muted-foreground hover:text-foreground py-1 rounded border border-dashed border-border/40 hover:border-border transition-colors"
          >
            展开剩余 {hidden} 个 SKILL
          </button>
        ) : null}
        {showAll && rows.length > 8 ? (
          <button
            type="button"
            onClick={() => setShowAll(false)}
            className="w-full text-[11px] text-muted-foreground hover:text-foreground py-1 rounded border border-dashed border-border/40 hover:border-border transition-colors"
          >
            收起
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function MeetingAgentContextDrawer({
  open,
  onClose,
  synapseApiBase,
  roomId,
  agent,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [payload, setPayload] = useState<MeetingAgentContextsPayload | null>(null);
  const [view, setView] = useState<'all' | 'prompt' | 'messages'>('all');
  const [roleFilter, setRoleFilter] = useState<MsgRole | 'all'>('all');

  const load = useCallback(async () => {
    const base = (synapseApiBase || '').trim();
    if (!base || !roomId) return;
    setLoading(true);
    try {
      const data = await fetchMeetingAgentContexts(base, roomId);
      setPayload(data);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [synapseApiBase, roomId]);

  useEffect(() => {
    if (open && agent) void load();
    if (!open) {
      setPayload(null);
      setView('all');
      setRoleFilter('all');
    }
  }, [open, agent?.profileId, load]);

  const entry: MeetingAgentContextEntry | undefined = useMemo(() => {
    if (!payload || !agent) return undefined;
    return payload.agents?.find((a) => a.profile_id === agent.profileId);
  }, [payload, agent]);

  const subEntries = useMemo(() => {
    if (!payload || !agent) return [];
    return (payload.sub_agents || []).filter(
      (s) => String(s.profile_id || s.agent_id || '') === agent.profileId,
    );
  }, [payload, agent]);

  const messages = useMemo<NormalizedMessage[]>(() => {
    if (!entry?.messages?.length) return [];
    return entry.messages.map((m, i) => normalizeMessage(m as Record<string, unknown>, i));
  }, [entry?.messages]);

  const filteredMessages = useMemo(() => {
    if (roleFilter === 'all') return messages;
    return messages.filter((m) => m.role === roleFilter);
  }, [messages, roleFilter]);

  const roleCounts = useMemo(() => {
    const out: Partial<Record<MsgRole, number>> = {};
    for (const m of messages) out[m.role] = (out[m.role] || 0) + 1;
    return out;
  }, [messages]);

  const avatarColor = agent?.isHost ? 'bg-violet-500' : agent?.avatarColor || 'bg-sky-500';

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={620}
      destroyOnClose
      closable={false}
      headerStyle={{ display: 'none' }}
      bodyStyle={{ padding: 0, background: 'var(--panel, #0f0f12)' }}
    >
      {/* ─── Header ─────────────────────────────────────────────── */}
      <div className="sticky top-0 z-30 backdrop-blur-md bg-[color:var(--panel,#0f0f12)]/85 border-b border-border/60">
        <div className="px-5 py-4 flex items-start gap-3">
          <div
            className={`w-11 h-11 rounded-xl flex items-center justify-center text-white ${avatarColor} shadow-lg shadow-black/30 shrink-0`}
          >
            {agent?.isHost ? <Bot className="w-5 h-5" /> : <Cpu className="w-5 h-5" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-base font-semibold text-foreground truncate">
                {agent?.name || '智能体'}
              </span>
              <Tag color={agent?.isHost ? 'purple' : 'blue'} className="m-0 text-[10px]">
                {agent?.isHost ? '主控 · 小鲸' : '协作智能体'}
              </Tag>
              {entry?.task?.status ? (
                <Tag
                  color={
                    entry.task.status === 'reasoning' || entry.task.status === 'acting'
                      ? 'processing'
                      : entry.task.status === 'completed'
                        ? 'success'
                        : entry.task.status === 'failed'
                          ? 'error'
                          : 'default'
                  }
                  className="m-0 text-[10px]"
                >
                  {entry.task.status}
                </Tag>
              ) : null}
            </div>
            <div className="text-[11px] text-muted-foreground font-mono truncate mt-0.5">
              {agent?.profileId}
              {entry?.preferred_endpoint ? ` · ${entry.preferred_endpoint}` : ''}
            </div>
          </div>
          <Button
            type="text"
            size="small"
            icon={loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            onClick={() => void load()}
          >
            刷新
          </Button>
          <Button type="text" size="small" onClick={onClose}>
            关闭
          </Button>
        </div>

        {entry ? (
          <div className="px-5 pb-3 flex flex-wrap gap-2">
            <Stat
              icon={<MessageSquareText className="w-3 h-3" />}
              label="消息"
              value={entry.messages_count ?? messages.length}
            />
            <Stat
              icon={<Activity className="w-3 h-3" />}
              label="迭代"
              value={entry.task?.iteration ?? '—'}
            />
            <Stat
              icon={<Wrench className="w-3 h-3" />}
              label="工具"
              value={(entry.task?.tools_executed || []).length || '—'}
            />
            <Stat
              icon={<Sparkles className="w-3 h-3" />}
              label="SKILL"
              value={(() => {
                const arr = entry.task?.skills_executed || [];
                if (!arr.length) return '—';
                const unique = new Set(arr.map((s) => s.skill)).size;
                return `${arr.length}·${unique}`;
              })()}
            />
            <Stat
              icon={<FileCode2 className="w-3 h-3" />}
              label="System"
              value={(entry.system_prompt || '').length.toLocaleString()}
            />
          </div>
        ) : null}

        <div className="px-5 pb-3">
          <Segmented
            size="small"
            block
            value={view}
            onChange={(v) => setView(v as typeof view)}
            options={[
              { label: '全部', value: 'all' },
              { label: 'Prompt', value: 'prompt' },
              { label: `Messages (${messages.length})`, value: 'messages' },
            ]}
          />
        </div>
      </div>

      {/* ─── Body ───────────────────────────────────────────────── */}
      <div className="px-5 py-4 space-y-4">
        {loading && !payload ? (
          <div className="flex items-center justify-center py-16">
            <Spin tip="加载上下文…" />
          </div>
        ) : !entry ? (
          <Empty
            description={
              <div className="space-y-2 text-xs text-muted-foreground">
                <div className="flex items-center justify-center gap-2">
                  <BrainCircuit className="w-4 h-4 opacity-50" />
                  <span>该智能体尚未在 Agent 池中激活，或实例已被回收</span>
                </div>
                <div className="text-[11px] text-muted-foreground/70">
                  节点执行中点击「刷新」；完整 LLM 请求见 data/llm_debug/
                </div>
              </div>
            }
          >
            {subEntries.length ? (
              <div className="mt-4 mx-auto max-w-md text-left space-y-3">
                <div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-[11px] space-y-1">
                  <div className="text-xs font-medium text-foreground/90 mb-1.5 flex items-center gap-1">
                    <Activity className="w-3 h-3" /> 委派子任务历史（{subEntries.length}）
                  </div>
                  {subEntries.map((s, i) => (
                    <div key={i} className="flex items-center justify-between gap-2 font-mono">
                      <span>{s.status || 'idle'}</span>
                      <span className="text-muted-foreground">iter={s.iteration ?? 0}</span>
                      <span className="text-muted-foreground truncate flex-1 text-right">
                        {s.current_tool_summary || ''}
                      </span>
                    </div>
                  ))}
                </div>
                {(() => {
                  const merged: SkillExecutionEntry[] = [];
                  for (const s of subEntries) {
                    for (const item of s.skills_executed || []) merged.push(item);
                  }
                  return merged.length ? <SkillUsageCard entries={merged} /> : null;
                })()}
              </div>
            ) : null}
          </Empty>
        ) : (
          <>
            {(view === 'all' || view === 'prompt') && (
              <>
                <CollapsibleBlock
                  title="System Prompt"
                  icon={<Sparkles className="w-3 h-3 text-violet-400" />}
                  text={entry.system_prompt || ''}
                  emptyHint="暂无 system prompt（可能尚未触发 LLM）"
                  defaultOpen={view === 'prompt'}
                  maxHeight={view === 'prompt' ? 640 : 280}
                />
                {entry.custom_prompt_suffix ? (
                  <CollapsibleBlock
                    title="会议室 SKILL 注入"
                    icon={<Terminal className="w-3 h-3 text-emerald-400" />}
                    text={entry.custom_prompt_suffix}
                    defaultOpen={false}
                    maxHeight={260}
                  />
                ) : null}
                {entry.task?.description_preview ? (
                  <CollapsibleBlock
                    title="当前任务描述"
                    icon={<Activity className="w-3 h-3 text-blue-400" />}
                    text={entry.task.description_preview}
                    defaultOpen={false}
                    mono={false}
                    maxHeight={180}
                  />
                ) : null}
                {view === 'all' ? (
                  <SkillUsageCard entries={entry.task?.skills_executed || []} />
                ) : null}
              </>
            )}

            {(view === 'all' || view === 'messages') && (
              <div className="rounded-xl border border-border/60 bg-[color:var(--panel,#1c1c1f)]/60 overflow-hidden">
                <div className="px-3 py-2 border-b border-border/40 flex items-center gap-2 flex-wrap">
                  <MessageSquareText className="w-3.5 h-3.5 text-blue-400" />
                  <span className="text-xs font-medium">对话消息</span>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {filteredMessages.length}/{messages.length}
                  </span>
                  <div className="ml-auto flex items-center gap-1 flex-wrap">
                    {(['all', 'system', 'user', 'assistant', 'tool'] as const).map((r) => {
                      const active = roleFilter === r;
                      const count = r === 'all' ? messages.length : roleCounts[r as MsgRole] || 0;
                      if (r !== 'all' && count === 0) return null;
                      return (
                        <button
                          key={r}
                          type="button"
                          onClick={() => setRoleFilter(r)}
                          className={`text-[10px] px-1.5 py-0.5 rounded-md border transition-colors ${
                            active
                              ? 'bg-blue-500/20 border-blue-500/40 text-blue-200'
                              : 'border-border/40 text-muted-foreground hover:text-foreground hover:border-border'
                          }`}
                        >
                          {r === 'all' ? '全部' : r} · {count}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="p-3 space-y-3 max-h-[min(60vh,560px)] overflow-y-auto custom-scrollbar">
                  {filteredMessages.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-6">
                      暂无对应消息
                    </p>
                  ) : (
                    filteredMessages.map((m) => <MessageCard key={m.index} msg={m} />)
                  )}
                </div>
              </div>
            )}

            {payload?.dump_path ? (
              <div className="text-[10px] text-muted-foreground flex items-center gap-1 px-1">
                <ScrollText className="w-3 h-3" />
                服务端快照: <span className="font-mono">{payload.dump_path}</span>
              </div>
            ) : null}
          </>
        )}
      </div>
    </Drawer>
  );
}
