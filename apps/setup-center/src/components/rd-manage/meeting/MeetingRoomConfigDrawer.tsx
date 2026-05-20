import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Drawer, Input, Select, Button, Collapse, Tag, Spin } from 'antd';
import {
  Settings2,
  Users,
  Bot,
  Cpu,
  BookOpen,
  Crown,
  Layers,
  UserCheck,
  FileOutput,
  Target,
} from 'lucide-react';
import { MeetingHitlForm, type HitlFormSchema } from './MeetingHitlForm';
import type { MeetingRoomNodeBinding } from '../../../api/meetingRoomService';
import { toast } from 'sonner';
import { SOP_STAGES } from '../../../rd-sop/constants';
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

const DEFAULT_WORKER_PROFILE_IDS = [
  'whalecloud-requirement-expert',
  'whalecloud-design-expert',
  'whalecloud-rd-expert',
  'whalecloud-test-expert',
  'whalecloud-qa-expert',
] as const;

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

/** 载入后补齐默认阵容，并锁定主控为小鲸 */
function hydrateConfigWithDefaults(config: MeetingRoomConfigPayload): MeetingRoomConfigPayload {
  const overrides = { ...(config.node_overrides || {}) };
  for (const nodeId of allSopNodeIds()) {
    const ov = { ...(overrides[nodeId] ?? {}) };
    const workers = ov.worker_profile_ids;
    const hasWorkers = Array.isArray(workers) && workers.length > 0;
    overrides[nodeId] = {
      ...ov,
      host_profile_id: HOST_PROFILE_ID,
      worker_profile_ids: hasWorkers
        ? workers.filter((id) => id !== HOST_PROFILE_ID)
        : [...DEFAULT_WORKER_PROFILE_IDS],
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
    const workers = ov.worker_profile_ids;
    const hasWorkers = Array.isArray(workers) && workers.length > 0;
    const entry: MeetingRoomNodeOverride = {
      ...ov,
      host_profile_id: HOST_PROFILE_ID,
      worker_profile_ids: hasWorkers
        ? workers.filter((id) => id !== HOST_PROFILE_ID)
        : [...DEFAULT_WORKER_PROFILE_IDS],
      node_intent: effectiveNodeIntent(ov, b),
    };
    if (ov.human_confirm !== undefined) entry.human_confirm = ov.human_confirm;
    if (ov.hitl_form_schema) entry.hitl_form_schema = ov.hitl_form_schema;
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

  const binding = useMemo(
    () => config?.bindings?.find((b) => b.node_id === selectedNodeId),
    [config, selectedNodeId],
  );

  const override: MeetingRoomNodeOverride = config?.node_overrides?.[selectedNodeId] ?? {};

  const workerProfileIds = useMemo(() => {
    const raw = override.worker_profile_ids ?? binding?.worker_profile_ids;
    if (Array.isArray(raw) && raw.length > 0) {
      return raw.filter((id) => id !== HOST_PROFILE_ID);
    }
    return [...DEFAULT_WORKER_PROFILE_IDS];
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
  const hitlSchema = (binding?.hitl_form_schema ?? null) as HitlFormSchema | null;
  const nodeOutputs = binding?.node_outputs ?? [];

  const patchRoomLevel = (
    patch: Partial<
      Pick<
        MeetingRoomConfigPayload,
        'host_llm_endpoint_key' | 'worker_llm_endpoint_key' | 'meeting_skill_id'
      >
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
        meeting_skill_id: config.meeting_skill_id,
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

  const collapseItems = SOP_STAGES.filter((s) => s.id > 0).map((stage) => ({
    key: String(stage.id),
    label: (
      <span className="text-sm font-medium">
        {stage.name}{' '}
        <Tag className="ml-1 font-mono text-[10px]">{stage.nodes.length}</Tag>
      </span>
    ),
    children: (
      <div className="flex flex-col gap-1">
        {stage.nodes.map((n) => {
          const enabled = isNodeEnabled(config?.node_overrides ?? {}, n.id);
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => setSelectedNodeId(n.id)}
              className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                selectedNodeId === n.id
                  ? 'border-blue-500/50 bg-blue-500/10 text-foreground shadow-[0_0_10px_rgba(59,130,246,0.1)]'
                  : 'border-border bg-muted/20 text-muted-foreground hover:border-blue-500/30'
              } ${!enabled ? 'opacity-60' : ''}`}
            >
              <span className="font-medium text-foreground">{n.name}</span>
              <span className="ml-2 font-mono text-[10px] opacity-70">{n.id}</span>
              {!enabled ? (
                <Tag className="ml-2 m-0 border-border/60 text-[9px] text-muted-foreground">
                  已关闭
                </Tag>
              ) : null}
            </button>
          );
        })}
      </div>
    ),
  }));

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
      width={780}
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
          <div className="w-[280px] overflow-y-auto custom-scrollbar bg-muted/5 p-4">
            <Collapse
              defaultActiveKey={SOP_STAGES.filter((s) => s.id > 0).map((s) => String(s.id))}
              ghost
              items={collapseItems}
              className="rd-meeting-config-stages"
            />
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-background">
            <div className="max-w-xl space-y-6">
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
                        onChange={(checked) => patchOverride({ human_confirm: checked })}
                        tone="emerald"
                        ariaLabel="人工确认"
                      />
                    </div>
                    <ConfigFieldBox className={humanConfirm ? 'border-emerald-500/20' : ''}>
                      <p className="text-[11px] text-muted-foreground leading-relaxed mb-0">
                        {humanConfirm
                          ? '节点完成后需填写确认表单，小鲸收到结构化结果后再推进下一节点。'
                          : '节点完成后自动推进下一 SOP 节点。'}
                      </p>
                      {humanConfirm && hitlSchema ? (
                        <div className="mt-3 pt-3 border-t border-border/40">
                          <MeetingHitlForm schema={hitlSchema} preview />
                        </div>
                      ) : null}
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

                  <div>
                    <label className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                      <BookOpen className="w-3.5 h-3.5 text-amber-400" />
                      会议室专属 SKILL
                    </label>
                    <ConfigFieldBox>
                      <div className="text-xs">
                        <span className="font-mono text-muted-foreground">
                          {config?.meeting_skill_id ?? config?.meeting_skill?.skill_id ?? 'whalecloud-dev-tool-meeting-room'}
                        </span>
                        {config?.meeting_skill?.exists === false ? (
                          <Tag className="ml-2 m-0 border-amber-500/40 bg-amber-500/10 text-amber-500 text-[10px]">
                            未找到文件
                          </Tag>
                        ) : null}
                      </div>
                      <p className="text-[11px] leading-relaxed text-muted-foreground mt-2.5 mb-0">
                        {config?.meeting_skill?.summary ??
                          '参会智能体进入会议室后自动加载，统一协作规范与能力边界。'}
                      </p>
                    </ConfigFieldBox>
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
