import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Drawer, Input, Select, Button, Tag, Spin } from 'antd';
import {
  Settings2,
  Users,
  Bot,
  Cpu,
  Crown,
  Layers,
  UserCheck,
  FileOutput,
  Target,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Sparkles,
  User,
  Cog,
  AlertCircle,
  type LucideIcon,
} from 'lucide-react';
import type { MeetingRoomNodeBinding } from '../../../api/meetingRoomService';
import { toast } from 'sonner';
import { NODE_TYPE_LABEL, SOP_STAGES, type NodeType, type SOPNode } from '../../../rd-sop/constants';
import {
  fetchLlmEndpointsCatalog,
  type LlmEndpointCatalogItem,
} from '@/api/rdUnifiedService';
import {
  fetchMeetingRoomConfig,
  putMeetingRoomConfig,
  type MeetingRoomConfigPayload,
  type MeetingRoomNodeOverride,
} from '../../../api/meetingRoomService';

const { TextArea } = Input;

/** 主控固定为小鲸（profile id: default） */
const HOST_PROFILE_ID = 'default';

interface AgentProfile {
  id: string;
  name: string;
  icon: string;
  color: string;
}

const FALLBACK_HOST_AGENT: AgentProfile = {
  id: HOST_PROFILE_ID,
  name: '小鲸',
  icon: '🐋',
  color: '#4A90D9',
};

function allSopNodeIds(): string[] {
  return SOP_STAGES.flatMap((s) => s.nodes.map((n) => n.id));
}

const PIPELINE_STAGES = SOP_STAGES.filter((s) => s.id > 0);

/** 各 SOP 阶段侧栏主题色 */
const STAGE_NAV_THEME: Record<
  number,
  { accent: string; badge: string; panel: string; dot: string }
> = {
  1: {
    accent: 'text-sky-400',
    badge: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    panel: 'border-sky-500/20 bg-sky-500/[0.06]',
    dot: 'bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.6)]',
  },
  2: {
    accent: 'text-violet-400',
    badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    panel: 'border-violet-500/20 bg-violet-500/[0.06]',
    dot: 'bg-violet-400 shadow-[0_0_8px_rgba(167,139,250,0.6)]',
  },
  3: {
    accent: 'text-indigo-400',
    badge: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
    panel: 'border-indigo-500/20 bg-indigo-500/[0.06]',
    dot: 'bg-indigo-400 shadow-[0_0_8px_rgba(129,140,248,0.6)]',
  },
  4: {
    accent: 'text-amber-400',
    badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    panel: 'border-amber-500/20 bg-amber-500/[0.06]',
    dot: 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]',
  },
  5: {
    accent: 'text-rose-400',
    badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    panel: 'border-rose-500/20 bg-rose-500/[0.06]',
    dot: 'bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.6)]',
  },
};

const DEFAULT_STAGE_THEME = STAGE_NAV_THEME[1];

const STAGE_PIPELINE_BAR: Record<number, string> = {
  1: 'bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.55)]',
  2: 'bg-violet-400 shadow-[0_0_8px_rgba(167,139,250,0.55)]',
  3: 'bg-indigo-400 shadow-[0_0_8px_rgba(129,140,248,0.55)]',
  4: 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.55)]',
  5: 'bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.55)]',
};

function nodeTypeNavMeta(type: NodeType): {
  label: string;
  chip: string;
  Icon: LucideIcon;
} {
  const label = NODE_TYPE_LABEL[type] ?? '节点';
  switch (type) {
    case 'ai':
      return {
        label,
        chip: 'bg-blue-500/12 text-blue-300 border-blue-500/25',
        Icon: Sparkles,
      };
    case 'human':
    case 'human_start':
      return {
        label,
        chip: 'bg-amber-500/12 text-amber-300 border-amber-500/25',
        Icon: User,
      };
    case 'ai_human':
      return {
        label,
        chip: 'bg-purple-500/12 text-purple-300 border-purple-500/25',
        Icon: Users,
      };
    case 'human_multi':
      return {
        label,
        chip: 'bg-orange-500/12 text-orange-300 border-orange-500/25',
        Icon: Users,
      };
    case 'ai_exception':
      return {
        label,
        chip: 'bg-red-500/12 text-red-300 border-red-500/25',
        Icon: AlertCircle,
      };
    case 'system':
      return {
        label,
        chip: 'bg-muted/40 text-muted-foreground border-border/50',
        Icon: Cog,
      };
    default:
      return {
        label,
        chip: 'bg-muted/40 text-muted-foreground border-border/50',
        Icon: Cog,
      };
  }
}

/** 与后端 `_coerce_enabled` 一致：未配置视为开启 */
type SwitchTone = 'blue' | 'emerald';

function MeetingConfigSwitch({
  checked,
  onChange,
  tone = 'blue',
  ariaLabel,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  tone?: SwitchTone;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      data-slot="rd-meeting-switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      className={`rd-meeting-config-switch rd-meeting-config-switch--tone-${tone} ${
        checked ? 'rd-meeting-config-switch--on' : 'rd-meeting-config-switch--off'
      }`}
      onClick={() => onChange(!checked)}
    >
      <span className="rd-meeting-config-switch__thumb" />
    </button>
  );
}

function ConfigFieldBox({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-xl border border-border/50 bg-background/60 backdrop-blur-sm p-3.5 shadow-inner ${className}`}
    >
      {children}
    </div>
  );
}

function isNodeEnabled(overrides: Record<string, MeetingRoomNodeOverride>, nodeId: string): boolean {
  const v = overrides[nodeId]?.enabled;
  if (v === undefined || v === null) return true;
  return v !== false;
}

/** 载入后补齐默认阵容（来自 API / 出厂配置），并锁定主控为小鲸 */
function hydrateConfigWithDefaults(config: MeetingRoomConfigPayload): MeetingRoomConfigPayload {
  const overrides = { ...(config.node_overrides || {}) };
  for (const nodeId of allSopNodeIds()) {
    const ov = { ...(overrides[nodeId] ?? {}) };
    const binding = bindingFor(config.bindings, nodeId);
    const workersSource = ov.worker_profile_ids ?? binding?.worker_profile_ids;
    const worker_profile_ids = Array.isArray(workersSource)
      ? workersSource.filter((id) => id !== HOST_PROFILE_ID)
      : undefined;
    overrides[nodeId] = {
      ...ov,
      host_profile_id: HOST_PROFILE_ID,
      ...(worker_profile_ids !== undefined ? { worker_profile_ids } : {}),
    };
  }
  return { ...config, node_overrides: overrides };
}

function bindingFor(
  bindings: MeetingRoomNodeBinding[] | undefined,
  nodeId: string,
): MeetingRoomNodeBinding | undefined {
  return bindings?.find((b) => b.node_id === nodeId);
}

function effectiveNodeIntent(
  ov: MeetingRoomNodeOverride,
  binding?: MeetingRoomNodeBinding,
): string {
  const custom = (ov.node_intent ?? '').trim();
  if (custom) return custom;
  return (binding?.default_node_intent ?? binding?.intent ?? '').trim();
}

function effectiveHumanConfirm(
  ov: MeetingRoomNodeOverride,
  binding?: MeetingRoomNodeBinding,
): boolean {
  if (binding?.type === 'system') return false;
  if (ov.human_confirm !== undefined && ov.human_confirm !== null) return Boolean(ov.human_confirm);
  return Boolean(binding?.human_confirm ?? binding?.default_human_confirm);
}

function normalizeOverridesForSave(
  nodeOverrides: Record<string, MeetingRoomNodeOverride>,
  bindings?: MeetingRoomNodeBinding[],
): Record<string, MeetingRoomNodeOverride> {
  const out: Record<string, MeetingRoomNodeOverride> = {};
  for (const nodeId of allSopNodeIds()) {
    const ov = nodeOverrides[nodeId] ?? {};
    const b = bindingFor(bindings, nodeId);
    const workers = ov.worker_profile_ids ?? b?.worker_profile_ids;
    const entry: MeetingRoomNodeOverride = {
      ...ov,
      host_profile_id: HOST_PROFILE_ID,
      node_intent: effectiveNodeIntent(ov, b),
    };
    if (Array.isArray(workers)) {
      entry.worker_profile_ids = workers.filter((id) => id !== HOST_PROFILE_ID);
    }
    if (ov.human_confirm !== undefined && b?.type !== 'system') entry.human_confirm = ov.human_confirm;
    if (ov.hitl_form_schema && b?.type !== 'system') entry.hitl_form_schema = ov.hitl_form_schema;
    out[nodeId] = entry;
  }
  return out;
}

export const MeetingRoomConfigDrawer: React.FC<{
  open: boolean;
  onClose: () => void;
  synapseApiBase: string;
}> = ({ open, onClose, synapseApiBase }) => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<MeetingRoomConfigPayload | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('boundary');
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [llmEndpoints, setLlmEndpoints] = useState<LlmEndpointCatalogItem[]>([]);
  const [llmEndpointsErr, setLlmEndpointsErr] = useState<string | null>(null);
  const [expandedStages, setExpandedStages] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(PIPELINE_STAGES.map((s) => [String(s.id), true])),
  );

  const workerAgents = useMemo(
    () => agents.filter((a) => a.id !== HOST_PROFILE_ID),
    [agents],
  );

  const hostAgent = useMemo(
    () => agents.find((a) => a.id === HOST_PROFILE_ID) ?? FALLBACK_HOST_AGENT,
    [agents],
  );

  const agentById = useMemo(() => {
    const map = new Map<string, AgentProfile>();
    map.set(HOST_PROFILE_ID, hostAgent);
    for (const a of agents) map.set(a.id, a);
    return map;
  }, [agents, hostAgent]);

  const load = useCallback(async () => {
    const base = synapseApiBase.trim();
    if (!base) return;
    setLoading(true);
    setLlmEndpointsErr(null);
    try {
      const [data, profilesRes, endpoints] = await Promise.all([
        fetchMeetingRoomConfig(base),
        fetch(`${base}/api/agents/profiles?include_hidden=true`).then((r) => r.json()),
        fetchLlmEndpointsCatalog(base).catch((e: unknown) => {
          setLlmEndpointsErr(e instanceof Error ? e.message : String(e));
          return [] as LlmEndpointCatalogItem[];
        }),
      ]);
      setConfig(hydrateConfigWithDefaults(data));
      setAgents(profilesRes.profiles || []);
      setLlmEndpoints(endpoints);
      if (endpoints.length > 0) setLlmEndpointsErr(null);

      const first = SOP_STAGES.find((s) => s.id > 0)?.nodes[0]?.id;
      if (first) setSelectedNodeId(first);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [synapseApiBase]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const selectedStageId = useMemo(() => {
    for (const stage of PIPELINE_STAGES) {
      if (stage.nodes.some((n) => n.id === selectedNodeId)) return stage.id;
    }
    return null;
  }, [selectedNodeId]);

  useEffect(() => {
    if (selectedStageId == null) return;
    setExpandedStages((prev) => ({ ...prev, [String(selectedStageId)]: true }));
  }, [selectedStageId]);

  const binding = useMemo(
    () => config?.bindings?.find((b) => b.node_id === selectedNodeId),
    [config, selectedNodeId],
  );

  const override: MeetingRoomNodeOverride = config?.node_overrides?.[selectedNodeId] ?? {};

  const workerProfileIds = useMemo(() => {
    const raw = override.worker_profile_ids ?? binding?.worker_profile_ids;
    if (!Array.isArray(raw)) return [];
    return raw.filter((id) => id !== HOST_PROFILE_ID);
  }, [override.worker_profile_ids, binding?.worker_profile_ids]);

  const patchOverride = (patch: MeetingRoomNodeOverride) => {
    if (!config) return;
    const next = { ...override, ...patch };
    if (next.worker_profile_ids) {
      next.worker_profile_ids = next.worker_profile_ids.filter((id) => id !== HOST_PROFILE_ID);
    }
    next.host_profile_id = HOST_PROFILE_ID;
    setConfig({
      ...config,
      node_overrides: {
        ...config.node_overrides,
        [selectedNodeId]: next,
      },
    });
  };

  const hostLlmEndpoint = config?.host_llm_endpoint_key ?? 'default';
  const workerLlmEndpoint = config?.worker_llm_endpoint_key ?? 'default';

  const nodeEnabled = isNodeEnabled(config?.node_overrides ?? {}, selectedNodeId);

  const defaultNodeIntent = binding?.default_node_intent ?? binding?.intent ?? '';
  const meetingGoal = effectiveNodeIntent(override, binding);
  const humanConfirm = effectiveHumanConfirm(override, binding);
  const isSystemNode = binding?.type === 'system';
  const nodeOutputs = binding?.node_outputs ?? [];

  const patchRoomLevel = (
    patch: Partial<
      Pick<MeetingRoomConfigPayload, 'host_llm_endpoint_key' | 'worker_llm_endpoint_key'>
    >,
  ) => {
    if (!config) return;
    setConfig({ ...config, ...patch });
  };

  const handleSave = async () => {
    const base = synapseApiBase.trim();
    if (!config || !base) return;
    for (const nodeId of allSopNodeIds()) {
      if (!isNodeEnabled(config.node_overrides ?? {}, nodeId)) continue;
      const ov = config.node_overrides?.[nodeId] ?? {};
      const goal = effectiveNodeIntent(ov, bindingFor(config.bindings, nodeId));
      if (!goal) {
        const name = bindingFor(config.bindings, nodeId)?.node_name ?? nodeId;
        toast.error(`节点「${name}」的会议目标不能为空`);
        return;
      }
    }
    setSaving(true);
    try {
      const saved = await putMeetingRoomConfig(base, {
        version: config.version || '1',
        host_llm_endpoint_key: hostLlmEndpoint,
        worker_llm_endpoint_key: workerLlmEndpoint,
        node_overrides: normalizeOverridesForSave(
          config.node_overrides || {},
          config.bindings,
        ),
      });
      setConfig(hydrateConfigWithDefaults(saved));
      toast.success('会议室配置已保存');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const renderEndpointSelect = (
    value: string,
    onChange: (next: string) => void,
    id: string,
  ) => (
    <select
      id={id}
      className="h-9 w-full rounded-lg border-0 bg-transparent px-0 text-sm text-foreground focus:outline-none focus:ring-0"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="default">默认端点 (default)</option>
      {value !== 'default' && !llmEndpoints.some((ep) => ep.name === value) ? (
        <option value={value}>{value}</option>
      ) : null}
      {llmEndpoints.map((ep) => (
        <option key={ep.name} value={ep.name}>
          {ep.model ? `${ep.name} — ${ep.model}` : ep.name}
        </option>
      ))}
    </select>
  );

  const renderAgentChip = (agent: AgentProfile, compact = false) => (
    <div className={`flex items-center gap-2 ${compact ? '' : 'min-w-0'}`}>
      <span
        className={`${compact ? 'w-4 h-4 text-[9px]' : 'w-5 h-5 text-[10px]'} shrink-0 rounded-full flex items-center justify-center text-white`}
        style={{ backgroundColor: agent.color || '#4A90D9' }}
      >
        {agent.icon}
      </span>
      <span className={`${compact ? 'text-xs' : 'text-sm'} font-medium text-foreground truncate`}>
        {agent.name}
      </span>
    </div>
  );

  const workerSelectOptions = workerAgents.map((a) => ({
    value: a.id,
    name: a.name,
    label: a.name,
  }));

  const llmEndpointValue = override.llm_endpoint_key ?? binding?.llm_endpoint_key ?? 'default';

  const llmEndpointMissingFromCatalog = useMemo(
    () =>
      llmEndpointValue !== 'default' &&
      !llmEndpoints.some((ep) => ep.name === llmEndpointValue),
    [llmEndpointValue, llmEndpoints],
  );

  const meetingSelectStyles = {
    content: { color: 'var(--text)' },
    placeholder: { color: 'var(--muted)' },
  } as const;

  const bindingByNodeId = useMemo(() => {
    const map = new Map<string, MeetingRoomNodeBinding>();
    for (const b of config?.bindings ?? []) {
      if (b?.node_id) map.set(b.node_id, b);
    }
    return map;
  }, [config?.bindings]);

  const navStats = useMemo(() => {
    const overrides = config?.node_overrides ?? {};
    let enabled = 0;
    let disabled = 0;
    for (const stage of PIPELINE_STAGES) {
      for (const n of stage.nodes) {
        if (isNodeEnabled(overrides, n.id)) enabled += 1;
        else disabled += 1;
      }
    }
    return { enabled, disabled, total: enabled + disabled };
  }, [config?.node_overrides]);

  const stageEnableStats = useMemo(() => {
    const overrides = config?.node_overrides ?? {};
    const map = new Map<number, { enabled: number; total: number }>();
    for (const stage of PIPELINE_STAGES) {
      let enabled = 0;
      for (const n of stage.nodes) {
        if (isNodeEnabled(overrides, n.id)) enabled += 1;
      }
      map.set(stage.id, { enabled, total: stage.nodes.length });
    }
    return map;
  }, [config?.node_overrides]);

  const toggleStage = (stageId: number) => {
    const key = String(stageId);
    setExpandedStages((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const renderSopNodeNavItem = (node: SOPNode, index: number, total: number) => {
    const enabled = isNodeEnabled(config?.node_overrides ?? {}, node.id);
    const selected = selectedNodeId === node.id;
    const typeMeta = nodeTypeNavMeta(node.type);
    const TypeIcon = typeMeta.Icon;
    const b = bindingByNodeId.get(node.id);
    const humanConfirm =
      config?.node_overrides?.[node.id]?.human_confirm ??
      b?.human_confirm ??
      b?.default_human_confirm ??
      false;

    return (
      <button
        key={node.id}
        type="button"
        data-slot="rd-meeting-nav-node"
        onClick={() => setSelectedNodeId(node.id)}
        className={`rd-meeting-sop-node group relative w-full text-left rounded-xl border px-3 py-2.5 transition-all duration-200 ${
          selected
            ? 'rd-meeting-sop-node--active border-emerald-500/45 bg-emerald-500/10 shadow-[0_0_16px_rgba(16,185,129,0.18)]'
            : 'border-border/45 bg-background/40 hover:border-emerald-500/25 hover:bg-emerald-500/[0.04]'
        } ${!enabled ? 'opacity-55' : ''}`}
      >
        {selected ? (
          <span
            className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full bg-gradient-to-b from-emerald-400 to-emerald-600"
            aria-hidden
          />
        ) : null}
        <div className="flex items-start gap-2.5 pl-0.5">
          <span
            className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-[10px] font-semibold ${typeMeta.chip}`}
          >
            <TypeIcon className="h-3 w-3" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className={`text-xs font-semibold ${selected ? 'text-foreground' : 'text-foreground/90'}`}>
                {node.name}
              </span>
              <span
                className={`rounded border px-1 py-0 text-[9px] font-medium ${typeMeta.chip} ${
                  selected ? 'ring-1 ring-emerald-500/35' : ''
                }`}
              >
                {typeMeta.label}
              </span>
              {selected ? (
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0 text-[9px] font-medium text-emerald-300 rd-meeting-sop-node-pill">
                  配置中
                </span>
              ) : null}
              {!enabled ? (
                <span className="rounded border border-border/50 bg-muted/40 px-1 py-0 text-[9px] text-muted-foreground">
                  已关闭
                </span>
              ) : null}
              {humanConfirm && enabled ? (
                <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1 py-0 text-[9px] text-emerald-400/90">
                  人工确认
                </span>
              ) : null}
            </div>
            <span className="font-mono text-[10px] text-muted-foreground/80">{node.id}</span>
          </div>
          <span className="text-[10px] tabular-nums text-muted-foreground/50 shrink-0">
            {index + 1}/{total}
          </span>
        </div>
      </button>
    );
  };

  return (
    <Drawer
      title={
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 shadow-[0_0_15px_rgba(59,130,246,0.2)]">
            <Settings2 className="h-4 w-4" />
          </div>
          <div>
            <div className="text-base font-semibold">会议室阵容配置</div>
            <div className="text-[10px] text-muted-foreground font-normal mt-0.5">
              配置各个议题节点的参与智能体及模型端点
            </div>
          </div>
        </div>
      }
      open={open}
      onClose={onClose}
      width={1000}
      destroyOnClose
      rootClassName="rd-meeting-config-drawer"
      className="rd-meeting-config-drawer"
      classNames={{
        header: 'border-b border-border/50 bg-muted/10',
        body: 'bg-background p-0',
        footer: 'border-t border-border/50 bg-muted/10',
      }}
      extra={
        <Button
          type="primary"
          className="bg-blue-600 hover:bg-blue-500 border-none shadow-[0_0_10px_rgba(37,99,235,0.3)]"
          loading={saving}
          onClick={() => void handleSave()}
        >
          保存配置
        </Button>
      }
    >
      {loading ? (
        <div className="flex justify-center py-24">
          <Spin size="large" />
        </div>
      ) : (
        <div className="flex h-full divide-x divide-border/50">
          <aside className="rd-meeting-sop-nav w-[380px] shrink-0 flex flex-col border-r border-border/40 bg-gradient-to-b from-muted/15 via-background to-background">
            <div className="shrink-0 px-4 pt-4 pb-3 border-b border-border/40">
              <div className="flex items-center gap-2.5 mb-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500/20 to-blue-500/10 border border-emerald-500/25">
                  <GitBranch className="h-4 w-4 text-emerald-400" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold tracking-tight text-foreground">研发会议室SOP节点</h3>
                  <p className="text-[10px] text-muted-foreground leading-snug">选择议程节点进行配置</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 mb-3">
                <span className="rounded-md border border-border/50 bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground">
                  共 {navStats.total} 节点
                </span>
                <span className="rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400/90">
                  {navStats.enabled} 启用
                </span>
                {navStats.disabled > 0 ? (
                  <span className="rounded-md border border-border/50 bg-muted/25 px-2 py-0.5 text-[10px] text-muted-foreground">
                    {navStats.disabled} 关闭
                  </span>
                ) : null}
              </div>
              <div
                className="flex gap-1.5"
                role="tablist"
                aria-label="SOP 阶段概览"
              >
                {PIPELINE_STAGES.map((stage) => {
                  const theme = STAGE_NAV_THEME[stage.id] ?? DEFAULT_STAGE_THEME;
                  const active = selectedStageId === stage.id;
                  const stats = stageEnableStats.get(stage.id);
                  const ratio =
                    stats && stats.total > 0 ? Math.round((stats.enabled / stats.total) * 100) : 0;
                  return (
                    <button
                      key={stage.id}
                      type="button"
                      data-slot="rd-meeting-nav-pipeline"
                      role="tab"
                      aria-selected={active}
                      title={`${stage.name} · ${stats?.enabled ?? 0}/${stats?.total ?? 0} 启用`}
                      onClick={() => {
                        setExpandedStages((prev) => ({ ...prev, [String(stage.id)]: true }));
                        const first = stage.nodes[0];
                        if (first) setSelectedNodeId(first.id);
                      }}
                      className={`group relative flex-1 min-w-0 rounded-lg border px-1 py-1.5 transition-all duration-300 ${
                        active
                          ? `${theme.panel} border-opacity-80 scale-[1.02] shadow-[0_4px_14px_rgba(0,0,0,0.12)]`
                          : 'border-border/40 bg-muted/20 hover:border-border/60 hover:bg-muted/35'
                      }`}
                    >
                      <span
                        className={`block text-center text-[9px] font-bold tabular-nums leading-none ${
                          active ? theme.accent : 'text-muted-foreground/80'
                        }`}
                      >
                        {stage.id}
                      </span>
                      <span
                        className={`mx-auto mt-1 block h-1 max-w-[2.25rem] rounded-full overflow-hidden bg-border/50 ${
                          active ? 'opacity-100' : 'opacity-70'
                        }`}
                      >
                        <span
                          className={`block h-full rounded-full transition-all duration-500 ${
                            STAGE_PIPELINE_BAR[stage.id] ?? 'bg-muted-foreground'
                          }`}
                          style={{ width: `${ratio}%` }}
                        />
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar px-3 py-3 space-y-2.5">
              {PIPELINE_STAGES.map((stage) => {
                const theme = STAGE_NAV_THEME[stage.id] ?? DEFAULT_STAGE_THEME;
                const expanded = expandedStages[String(stage.id)] ?? true;
                const hasSelected = stage.nodes.some((n) => n.id === selectedNodeId);
                const stats = stageEnableStats.get(stage.id);
                const enableRatio =
                  stats && stats.total > 0 ? (stats.enabled / stats.total) * 100 : 0;

                return (
                  <div
                    key={stage.id}
                    className={`rd-meeting-sop-stage rounded-xl border overflow-hidden transition-all duration-300 ${theme.panel} ${
                      hasSelected
                        ? 'rd-meeting-sop-stage--focus shadow-[0_0_22px_rgba(16,185,129,0.12)] ring-1 ring-emerald-500/20'
                        : ''
                    }`}
                  >
                    <button
                      type="button"
                      data-slot="rd-meeting-nav-stage"
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-foreground/[0.03] transition-colors"
                      onClick={() => toggleStage(stage.id)}
                    >
                      <span className="text-muted-foreground/70 shrink-0">
                        {expanded ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </span>
                      <span
                        className={`flex h-6 min-w-[1.5rem] items-center justify-center rounded-md border px-1.5 text-[10px] font-bold tabular-nums ${theme.badge}`}
                      >
                        {stage.id}
                      </span>
                      <span className={`flex-1 text-sm font-semibold truncate ${theme.accent}`}>
                        {stage.name}
                      </span>
                      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${theme.dot}`} aria-hidden />
                      <span className="text-[10px] tabular-nums text-muted-foreground/70 shrink-0">
                        {stats?.enabled ?? 0}/{stats?.total ?? stage.nodes.length}
                      </span>
                    </button>
                    <div className="px-3 pb-2 -mt-0.5">
                      <div className="h-0.5 rounded-full bg-border/35 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            STAGE_PIPELINE_BAR[stage.id] ?? 'bg-muted-foreground'
                          }`}
                          style={{ width: `${enableRatio}%` }}
                        />
                      </div>
                    </div>

                    {expanded ? (
                      <div className="px-2 pb-2.5 pt-0 space-y-1.5 rd-meeting-sop-node-list">
                        {stage.nodes.map((n, idx) => renderSopNodeNavItem(n, idx, stage.nodes.length))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </aside>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-background">
            <div className="max-w-2xl space-y-6">
              {/* 当前节点配置 */}
              <section className="relative overflow-hidden rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-500/[0.12] via-background to-background p-5 shadow-[0_12px_40px_rgba(16,185,129,0.1)]">
                <div
                  className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-emerald-400/10 blur-2xl"
                  aria-hidden
                />
                <div className="relative flex flex-wrap items-center gap-2 mb-5 pb-4 border-b border-emerald-500/15">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 border border-emerald-500/25">
                    <Layers className="w-4 h-4 text-emerald-400" />
                  </div>
                  <h3 className="text-sm font-semibold tracking-tight text-foreground">当前节点配置</h3>
                  <Tag className="m-0 border-emerald-500/35 bg-emerald-500/15 text-emerald-300 text-[10px] font-medium">
                    {binding?.node_name || selectedNodeId}
                  </Tag>
                  <Tag className="m-0 font-mono text-[10px] text-muted-foreground/90 border-border/50 bg-muted/30">
                    {selectedNodeId}
                  </Tag>
                </div>

                <div className="relative space-y-5">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm font-medium text-foreground">会议室 SOP 节点开关</span>
                    <MeetingConfigSwitch
                      checked={nodeEnabled}
                      onChange={(checked) => patchOverride({ enabled: checked })}
                      tone="blue"
                      ariaLabel="会议室 SOP 节点开关"
                    />
                  </div>
                  {!nodeEnabled ? (
                    <p className="text-[11px] text-amber-500/95 dark:text-amber-400/95 leading-relaxed -mt-2">
                      关闭后进入该节点将立即跳过并推进，不调用智能体。
                    </p>
                  ) : isSystemNode ? (
                    <p className="text-[11px] text-slate-400 leading-relaxed -mt-2">
                      系统节点由 Pipeline 代码 handler 执行（如 git 落盘至 work/&lt;工单&gt;/sandbox/），不调度大模型，且不可开启人工确认。
                    </p>
                  ) : null}

                  <div className="h-px bg-gradient-to-r from-transparent via-border/80 to-transparent" />

                  <div>
                    <label className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                      <Target className="w-3.5 h-3.5 text-sky-400" />
                      会议目标
                    </label>
                    <ConfigFieldBox>
                      <TextArea
                        rows={3}
                        value={meetingGoal}
                        onChange={(e) => patchOverride({ node_intent: e.target.value })}
                        placeholder={defaultNodeIntent || '请填写本节点会议目标'}
                        className="!bg-transparent !border-none !shadow-none text-foreground text-sm leading-relaxed resize-none p-0 focus:!ring-0"
                      />
                    </ConfigFieldBox>
                    <p className="text-[10px] text-muted-foreground mt-2">
                      可修改预设目标，保存时不可留空
                    </p>
                  </div>

                  <div>
                    <div className="mb-2.5 flex items-center justify-between gap-4">
                      <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                        <UserCheck className="w-3.5 h-3.5 text-emerald-400" />
                        人工确认
                      </label>
                      <MeetingConfigSwitch
                        checked={humanConfirm}
                        disabled={isSystemNode}
                        onChange={(checked) => patchOverride({ human_confirm: checked })}
                        tone="emerald"
                        ariaLabel="人工确认"
                      />
                    </div>
                    <ConfigFieldBox className={humanConfirm ? 'border-emerald-500/20' : ''}>
                      <p className="text-[11px] text-muted-foreground leading-relaxed mb-0">
                        {isSystemNode
                          ? '系统节点固定为自动推进，不支持人工确认。'
                          : humanConfirm
                            ? '节点完成后需填写确认表单，小鲸收到结构化结果后再推进下一节点。'
                            : '节点完成后自动推进下一 SOP 节点。'}
                      </p>
                    </ConfigFieldBox>
                  </div>

                  <div>
                    <label className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                      <FileOutput className="w-3.5 h-3.5 text-amber-400" />
                      节点产出
                    </label>
                    <ConfigFieldBox>
                      <ul className="text-[11px] text-muted-foreground space-y-2 mb-0">
                        {nodeOutputs.map((item) => (
                          <li key={item} className="flex items-start gap-2">
                            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-amber-400/80" />
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                      <p className="text-[10px] text-muted-foreground/70 mt-3 mb-0 pt-2 border-t border-border/30">
                        系统固定 · archive/&lt;stage&gt;/&lt;node&gt;/
                      </p>
                    </ConfigFieldBox>
                  </div>

                  <div className="h-px bg-gradient-to-r from-transparent via-border/80 to-transparent" />

                  {!isSystemNode ? (
                  <>
                  <div>
                    <label className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                      <Bot className="w-3.5 h-3.5 text-indigo-400" />
                      主控智能体
                    </label>
                    <ConfigFieldBox>
                      <div className="rd-meeting-host-readonly flex items-center gap-2">
                        {renderAgentChip(hostAgent)}
                        <Tag className="ml-auto m-0 border-indigo-500/25 bg-indigo-500/10 text-[10px] text-indigo-300">
                          固定小鲸
                        </Tag>
                      </div>
                    </ConfigFieldBox>
                  </div>

                  <div>
                    <label className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                      <Users className="w-3.5 h-3.5 text-emerald-400" />
                      协作智能体
                    </label>
                    <ConfigFieldBox>
                      <Select
                        mode="multiple"
                        className="w-full rd-meeting-agent-select"
                        styles={meetingSelectStyles}
                        popupClassName="rd-meeting-agent-select-dropdown"
                        placeholder="选择本节点参与的协作智能体"
                        value={workerProfileIds}
                        onChange={(v) => patchOverride({ worker_profile_ids: v })}
                        showSearch
                        optionFilterProp="name"
                        optionLabelProp="label"
                        options={workerSelectOptions}
                        optionRender={(opt) => {
                          const agent = agentById.get(String(opt.value));
                          return agent ? renderAgentChip(agent) : opt.label;
                        }}
                        tagRender={({ value, closable, onClose }) => {
                          const agent = agentById.get(String(value));
                          if (!agent) return <span className="text-foreground">{String(value)}</span>;
                          return (
                            <span className="rd-meeting-agent-tag inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/12 pl-1.5 pr-1 py-0.5 mr-1 mb-1">
                              {renderAgentChip(agent, true)}
                              {closable ? (
                                <button
                                  type="button"
                                  className="ml-0.5 rounded px-1 text-foreground/70 hover:bg-foreground/10"
                                  onClick={onClose}
                                  aria-label="移除"
                                >
                                  ×
                                </button>
                              ) : null}
                            </span>
                          );
                        }}
                      />

                      <div className="mt-4 pl-3 border-l-2 border-purple-500/35 space-y-2">
                        <label
                          htmlFor="rd-meeting-llm-ep-select"
                          className="flex items-center gap-2 text-[11px] font-medium text-foreground/85"
                        >
                          <Cpu className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                          本节点 Worker LLM 端点
                        </label>
                        <select
                          id="rd-meeting-llm-ep-select"
                          className="h-9 w-full rounded-lg border border-border/60 bg-muted/25 px-2.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-purple-500/25"
                          value={llmEndpointValue}
                          onChange={(e) => patchOverride({ llm_endpoint_key: e.target.value })}
                        >
                          <option value="default">继承会议室级 Worker 端点</option>
                          {llmEndpointMissingFromCatalog ? (
                            <option value={llmEndpointValue}>{llmEndpointValue}</option>
                          ) : null}
                          {llmEndpoints.map((ep) => (
                            <option key={ep.name} value={ep.name}>
                              {ep.model ? `${ep.name} — ${ep.model}` : ep.name}
                            </option>
                          ))}
                        </select>
                        {llmEndpointsErr ? (
                          <p className="text-[11px] text-amber-500">{llmEndpointsErr}</p>
                        ) : (
                          <p className="text-[10px] text-muted-foreground mb-0">
                            仅覆盖本节点协作智能体；小鲸端点见全局配置
                          </p>
                        )}
                      </div>
                    </ConfigFieldBox>
                  </div>
                  </>
                  ) : null}
                </div>
              </section>

              {/* 会议室全局配置 */}
              <section className="relative overflow-hidden rounded-2xl border border-blue-500/25 bg-gradient-to-br from-blue-500/[0.12] via-background to-background p-5 shadow-[0_12px_40px_rgba(59,130,246,0.1)]">
                <div
                  className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-blue-400/10 blur-2xl"
                  aria-hidden
                />
                <div className="relative flex flex-wrap items-center gap-2 mb-5 pb-4 border-b border-blue-500/15">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/15 border border-blue-500/25">
                    <Crown className="w-4 h-4 text-blue-400" />
                  </div>
                  <h3 className="text-sm font-semibold tracking-tight text-foreground">会议室全局配置</h3>
                  <Tag className="ml-auto m-0 border-blue-500/35 bg-blue-500/15 text-blue-300 text-[10px] font-medium">
                    所有节点共享
                  </Tag>
                </div>

                <div className="relative space-y-5">
                  <div>
                    <label
                      htmlFor="rd-meeting-host-llm-ep"
                      className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80"
                    >
                      <Bot className="w-3.5 h-3.5 text-indigo-400" />
                      小鲸专属 LLM 端点
                    </label>
                    <ConfigFieldBox>
                      {renderEndpointSelect(hostLlmEndpoint, (v) => patchRoomLevel({ host_llm_endpoint_key: v }), 'rd-meeting-host-llm-ep')}
                    </ConfigFieldBox>
                    <p className="text-[10px] text-muted-foreground mt-2">
                      仅小鲸（主持人）使用，建议绑定推理能力更强的端点
                    </p>
                  </div>

                  <div>
                    <label
                      htmlFor="rd-meeting-worker-llm-ep"
                      className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80"
                    >
                      <Users className="w-3.5 h-3.5 text-emerald-400" />
                      协作智能体统一 LLM 端点
                    </label>
                    <ConfigFieldBox>
                      {renderEndpointSelect(workerLlmEndpoint, (v) => patchRoomLevel({ worker_llm_endpoint_key: v }), 'rd-meeting-worker-llm-ep')}
                    </ConfigFieldBox>
                    <p className="text-[10px] text-muted-foreground mt-2">
                      所有协作智能体默认共用；单节点可在「协作智能体」下单独覆盖
                    </p>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
};
