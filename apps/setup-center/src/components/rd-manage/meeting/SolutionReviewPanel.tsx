/**
 * 方案评审面板：一次性完成评审（补丁选择 + 小鲸评分 + 产出物预览 + 拆单预览 + 人工意见）
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Collapse,
  Input,
  Progress,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { TableColumnsType } from 'antd';
import {
  ArrowRight,
  CheckCircle2,
  FileText,
  GitBranch,
  Layers,
  Loader2,
  Package,
  Shield,
  Sparkles,
  XCircle,
} from 'lucide-react';

import {
  fetchArtifactFile,
  fetchPatchVersions,
  fetchSolutionReview,
  submitSolutionReviewDecision,
  type PatchVersionItem,
  type SolutionReviewPayload,
  type SplitTaskDraft,
  type SolutionReviewRepoRow,
} from '../../../api/meetingRoomService';
import {
  SearchableVirtualSelect,
  type SearchableOption,
} from '@/components/product/SearchableVirtualSelect';
import { ReviewMarkdown } from './ReviewMarkdown';

const { TextArea } = Input;
const { Text } = Typography;

interface Props {
  synapseApiBase: string;
  roomId: string;
  scopeId?: string;
  initialPayload?: SolutionReviewPayload | null;
  blocked?: boolean;
  onDecided?: () => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
  info: 'default',
};

const SCORE_DIMENSION_LABEL: Record<string, string> = {
  reliability: '可靠性',
  security: '安全性',
  consistency: '需求一致性',
  entropy_compliance: '控熵合规',
};

const SEVERITY_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
  info: '信息',
};

const VERDICT_LABEL: Record<string, string> = {
  pass: '通过',
  conditional_pass: '有条件通过',
  fail: '不通过',
  reject: '不通过',
};

function scoreDimensionLabel(key: string): string {
  const k = key.trim();
  return SCORE_DIMENSION_LABEL[k] ?? k.replace(/_/g, ' ');
}

function formatScoreBreakdownValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `${Math.round(value)} 分`;
  }
  return String(value ?? '—');
}

function impactTableColumns(headers: string[]): TableColumnsType<Record<string, string>> {
  return headers.map((h) => ({ title: h, dataIndex: h, key: h, ellipsis: true }));
}

function tableFromRows(rows: Record<string, string>[] | undefined, headers: string[]) {
  if (!rows?.length) return null;
  const cols = impactTableColumns(headers);
  const data = rows.map((r, i) => ({ ...r, key: String(i) }));
  return <Table size="small" columns={cols} dataSource={data} pagination={false} scroll={{ x: true }} />;
}

function repoBranchId(row: SolutionReviewRepoRow): string {
  return (row.branch_version_id || '').trim();
}

function repoDisplayLabel(row: SolutionReviewRepoRow): string {
  const mod = (row.product_module_name || '').trim();
  const branch = (row.branch_version_name || '').trim();
  if (mod && branch) return `${mod} · ${branch}`;
  return mod || branch || '未命名分支';
}

function patchItemToSearchableOption(p: PatchVersionItem): SearchableOption | null {
  const name = (p.patchName || '').trim();
  if (!name) return null;
  const meta: string[] = [];
  const state = (p.state || '').trim();
  if (state) meta.push(state);
  const close = (p.closingDate || '').trim();
  if (close) meta.push(close);
  return {
    value: name,
    label: meta.length ? `${name} · ${meta.join(' · ')}` : name,
  };
}

function patchOptionsToSearchable(
  patches: PatchVersionItem[],
  selected?: string,
): SearchableOption[] {
  const opts = patches
    .map(patchItemToSearchableOption)
    .filter((o): o is SearchableOption => o != null);
  const cur = (selected || '').trim();
  if (!cur || opts.some((o) => o.value === cur)) return opts;
  return [{ value: cur, label: cur }, ...opts];
}

/** 按仓库行与 split_tasks_draft 合并，供拆单预览 1:1 展示 */
function buildSplitPreviewForRepo(
  repo: SolutionReviewRepoRow,
  tasks: SplitTaskDraft[],
  patchByBranch: Record<string, string>,
  demandNo: string,
  requirementName: string,
): SplitTaskDraft {
  const bid = repoBranchId(repo);
  const matched =
    tasks.find((t) => (t.branch_version_id || '').trim() === bid && bid) ??
    tasks.find(
      (t) =>
        (t.productModuleName || '').trim() === (repo.product_module_name || '').trim() &&
        (t.branchVersionName || '').trim() === (repo.branch_version_name || '').trim(),
    );
  const patch = bid ? patchByBranch[bid] : '';
  const titleBase = (requirementName || demandNo || '研发子单').trim();
  const mod = (repo.product_module_name || '').trim();

  return {
    taskNo: matched?.taskNo || demandNo,
    taskTitle: matched?.taskTitle || `${titleBase}${mod ? ` — ${mod}` : ''}`,
    comments: matched?.comments || repo.change_summary || '',
    productModuleName: repo.product_module_name || matched?.productModuleName,
    branchVersionName: repo.branch_version_name || matched?.branchVersionName,
    patchName: patch || matched?.patchName || '',
    taskImpactDesc: matched?.taskImpactDesc,
    performanceImpact: matched?.performanceImpact,
    functionalImpact: matched?.functionalImpact,
    cfgChangeDescription: matched?.cfgChangeDescription,
    upgradeRisk: matched?.upgradeRisk,
    securityImpact: matched?.securityImpact,
    compatibilityImpact: matched?.compatibilityImpact,
    branch_version_id: bid,
  };
}

// ─── 子组件：渐变章节头 ───────────────────────────────────────────────

const SectionHeader: React.FC<{
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  accent?: 'violet' | 'amber' | 'cyan' | 'emerald' | 'blue';
}> = ({ icon, title, subtitle, accent = 'violet' }) => {
  const ring: Record<string, string> = {
    violet: 'from-violet-500/20 to-fuchsia-500/10 border-violet-500/30 text-violet-300',
    amber: 'from-amber-500/20 to-orange-500/10 border-amber-500/30 text-amber-300',
    cyan: 'from-cyan-500/20 to-blue-500/10 border-cyan-500/30 text-cyan-300',
    emerald: 'from-emerald-500/20 to-teal-500/10 border-emerald-500/30 text-emerald-300',
    blue: 'from-blue-500/20 to-indigo-500/10 border-blue-500/30 text-blue-300',
  };
  return (
    <div className="flex items-start gap-3">
      <div
        className={`shrink-0 rounded-xl border bg-gradient-to-br p-2.5 shadow-lg shadow-black/20 ${ring[accent]}`}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <h3 className="text-base font-semibold text-foreground tracking-tight">{title}</h3>
        {subtitle ? <p className="text-[12px] text-muted-foreground mt-0.5">{subtitle}</p> : null}
      </div>
    </div>
  );
};

// ─── 仓库 + 补丁卡片 ─────────────────────────────────────────────────

const RepoPatchCard: React.FC<{
  index: number;
  row: SolutionReviewRepoRow;
  patchOptions: PatchVersionItem[];
  patchLoading: boolean;
  patchFetched: boolean;
  selectedPatch?: string;
  readOnly: boolean;
  onPatchChange: (branchId: string, patch: string) => void;
}> = ({
  index,
  row,
  patchOptions,
  patchLoading,
  patchFetched,
  selectedPatch,
  readOnly,
  onPatchChange,
}) => {
  const bid = repoBranchId(row);
  const opts = patchOptionsToSearchable(patchOptions, selectedPatch);
  const empty = patchFetched && !patchLoading && opts.length === 0;
  const selectDisabled = readOnly || empty || !bid;

  return (
    <div
      className="group relative overflow-visible rounded-2xl border border-border/50 bg-gradient-to-br from-[#0c1018] via-[color:var(--panel,#0f0f12)] to-[#0a0e14] shadow-lg shadow-black/25 transition-all duration-300 hover:border-cyan-500/35 hover:shadow-[0_8px_32px_rgba(34,211,238,0.08)]"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent opacity-60" />
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border/40 bg-gradient-to-r from-cyan-500/[0.06] to-transparent">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-cyan-500/15 text-[11px] font-bold text-cyan-300 border border-cyan-500/25">
            {index + 1}
          </span>
          <div className="min-w-0">
            <div className="font-medium text-foreground truncate">{repoDisplayLabel(row)}</div>
            {row.product_module_name ? (
              <div className="text-[11px] text-muted-foreground flex items-center gap-1 mt-0.5">
                <Package className="h-3 w-3 shrink-0" />
                {row.product_module_name}
              </div>
            ) : null}
          </div>
        </div>
        <Tag bordered={false} className="shrink-0 m-0 bg-violet-500/15 text-violet-200 border-violet-500/30">
          <GitBranch className="inline h-3 w-3 mr-1 -mt-px" />
          {row.branch_version_name || '—'}
        </Tag>
      </div>
      <div className="p-4 space-y-3">
        {row.repo_url ? (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">仓库地址</div>
            <Tooltip title={row.repo_url}>
              <div className="font-mono text-[12px] text-cyan-200/90 truncate rounded-lg bg-black/30 px-2.5 py-1.5 border border-border/30">
                {row.repo_url}
              </div>
            </Tooltip>
          </div>
        ) : null}
        {row.change_summary ? (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">改造内容</div>
            <p className="text-[13px] leading-relaxed text-foreground/90 line-clamp-4">{row.change_summary}</p>
          </div>
        ) : null}
        <div className="relative z-10">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">补丁计划</div>
          {bid ? (
            <SearchableVirtualSelect
              value={selectedPatch || ''}
              onValueChange={(v) => onPatchChange(bid, v)}
              options={opts}
              placeholder="选择补丁计划"
              searchPlaceholder="搜索补丁名称或状态…"
              emptyText={empty ? '暂无可用补丁计划' : patchLoading ? '' : '无匹配补丁'}
              disabled={selectDisabled}
              isLoading={patchLoading}
              itemHeight={40}
              className="patch-plan-select-trigger"
              popoverClassName="min-w-[min(100%,320px)]"
            />
          ) : (
            <Text type="secondary" className="text-xs">
              未关联产品分支，无法选择补丁
            </Text>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── 拆单预览卡片（与仓库卡片一一对应）────────────────────────────────

const SplitPreviewCard: React.FC<{
  index: number;
  task: SplitTaskDraft;
  repoLabel: string;
}> = ({ index, task, repoLabel }) => {
  const impactFields = [
    { label: '研发单影响', value: task.taskImpactDesc },
    { label: '性能', value: task.performanceImpact },
    { label: '功能', value: task.functionalImpact },
    { label: '配置', value: task.cfgChangeDescription },
    { label: '升级风险', value: task.upgradeRisk },
    { label: '安全', value: task.securityImpact },
    { label: '兼容', value: task.compatibilityImpact },
  ].filter((f) => (f.value || '').trim());

  return (
    <div className="relative overflow-hidden rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-500/[0.04] via-[color:var(--panel,#0f0f12)] to-[#0a1018] shadow-lg shadow-black/20">
      <div className="absolute left-0 top-4 bottom-4 w-1 rounded-r-full bg-gradient-to-b from-emerald-400/80 to-teal-500/40" />
      <div className="pl-5 pr-4 py-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-[11px] font-bold text-emerald-300 border border-emerald-500/25">
              {index + 1}
            </span>
            <div className="min-w-0">
              <div className="text-[11px] text-muted-foreground">{repoLabel}</div>
              <div className="font-medium text-foreground line-clamp-2">{task.taskTitle || '—'}</div>
            </div>
          </div>
          <ArrowRight className="h-4 w-4 text-emerald-400/60 shrink-0 mt-1" />
        </div>
        <div className="grid grid-cols-2 gap-2 text-[12px]">
          <div className="rounded-lg bg-black/25 px-2.5 py-2 border border-border/30">
            <div className="text-[10px] text-muted-foreground">需求单号</div>
            <div className="font-mono text-foreground/90 mt-0.5">{task.taskNo || '—'}</div>
          </div>
          <div className="rounded-lg bg-black/25 px-2.5 py-2 border border-border/30">
            <div className="text-[10px] text-muted-foreground">补丁计划</div>
            <div className={`mt-0.5 font-medium ${task.patchName ? 'text-emerald-300' : 'text-amber-400/90'}`}>
              {task.patchName || '待选择'}
            </div>
          </div>
        </div>
        {task.comments ? (
          <div className="rounded-lg border border-border/30 bg-muted/5 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">研发单描述</div>
            <p className="text-[12px] leading-relaxed text-foreground/85 line-clamp-3">{task.comments}</p>
          </div>
        ) : null}
        {impactFields.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {impactFields.slice(0, 4).map((f) => (
              <Tooltip key={f.label} title={f.value}>
                <span className="inline-block max-w-[140px] truncate rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200/90 border border-emerald-500/20">
                  {f.label}
                </span>
              </Tooltip>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
};

// ─── 产出物浏览（仅已纳入）────────────────────────────────────────────

const Stage2ArtifactsPanel: React.FC<{
  artifacts: NonNullable<SolutionReviewPayload['inputs']>['stage2_artifacts'];
  synapseApiBase: string;
  roomId: string;
}> = ({ artifacts, synapseApiBase, roomId }) => {
  const included = useMemo(
    () => (artifacts ?? []).filter((a) => a.included !== false && a.relative_path),
    [artifacts],
  );
  const [activePath, setActivePath] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!included.length) {
      setActivePath(null);
      setContent('');
      return;
    }
    const first = included[0].relative_path!;
    if (!activePath || !included.some((a) => a.relative_path === activePath)) {
      setActivePath(first);
    }
  }, [included, activePath]);

  useEffect(() => {
    if (!activePath || !synapseApiBase || !roomId) return;
    let cancelled = false;
    setLoading(true);
    void fetchArtifactFile(synapseApiBase, roomId, activePath)
      .then((file) => {
        if (!cancelled) setContent(file.content);
      })
      .catch(() => {
        if (!cancelled) message.error('无法读取产出物');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePath, synapseApiBase, roomId]);

  if (!included.length) {
    return (
      <div className="rounded-xl border border-dashed border-border/50 px-6 py-10 text-center text-muted-foreground text-sm">
        暂无已纳入评审的需求设计产出物
      </div>
    );
  }

  const active = included.find((a) => a.relative_path === activePath);

  return (
    <div className="flex flex-col lg:flex-row gap-4 min-h-[240px]">
      <div className="lg:w-52 shrink-0 space-y-1">
        {included.map((a) => {
          const selected = a.relative_path === activePath;
          return (
            <button
              key={`${a.node_id}-${a.artifact}`}
              type="button"
              className={`w-full text-left rounded-xl px-3 py-2.5 text-sm transition-all duration-200 border ${
                selected
                  ? 'border-cyan-500/40 bg-cyan-500/10 text-foreground shadow-[0_0_20px_rgba(34,211,238,0.08)]'
                  : 'border-transparent hover:bg-muted/20 text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => a.relative_path && setActivePath(a.relative_path)}
            >
              <FileText className={`inline h-3.5 w-3.5 mr-1.5 ${selected ? 'text-cyan-400' : ''}`} />
              <span className="block font-medium truncate">{a.node_name || a.node_id}</span>
              <span className="block text-[11px] opacity-70 truncate mt-0.5">{a.artifact}</span>
            </button>
          );
        })}
      </div>
      <div className="flex-1 min-w-0 rounded-2xl border border-border/50 overflow-hidden bg-gradient-to-br from-[#0a0e14] via-[color:var(--panel)] to-[#0a1018] shadow-lg shadow-black/20">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/40 bg-gradient-to-r from-blue-500/[0.08] to-cyan-500/[0.04]">
          <Sparkles className="h-4 w-4 text-cyan-400" />
          <span className="text-sm font-medium truncate">
            {active ? `${active.node_name || active.node_id} / ${active.artifact}` : '预览'}
          </span>
        </div>
        <div className="p-4 overflow-auto max-h-[360px] custom-scrollbar min-h-[180px]">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin text-cyan-400" />
              正在加载…
            </div>
          ) : (
            <ReviewMarkdown content={content} />
          )}
        </div>
      </div>
    </div>
  );
};

// ─── 主面板 ───────────────────────────────────────────────────────────

export function SolutionReviewPanel({
  synapseApiBase,
  roomId,
  initialPayload,
  blocked = false,
  onDecided,
}: Props) {
  const [payload, setPayload] = useState<SolutionReviewPayload | null>(initialPayload ?? null);
  const [loading, setLoading] = useState(!initialPayload);
  const [submitting, setSubmitting] = useState(false);
  const [humanComment, setHumanComment] = useState('');
  const [patchByBranch, setPatchByBranch] = useState<Record<string, string>>({});
  const [patchOptions, setPatchOptions] = useState<Record<string, PatchVersionItem[]>>({});
  const [patchLoading, setPatchLoading] = useState<Record<string, boolean>>({});
  const patchFetchedRef = useRef<Set<string>>(new Set());
  const [projectId, setProjectId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!synapseApiBase || !roomId) return;
    setLoading(true);
    try {
      const res = await fetchSolutionReview(synapseApiBase, roomId);
      setPayload(res.payload);
      const pidRaw = (res.project_id ?? '').trim();
      const pidNum = pidRaw ? Number(pidRaw) : NaN;
      setProjectId(Number.isFinite(pidNum) ? pidNum : null);
      const hr = res.payload?.human_review;
      if (hr?.comment) setHumanComment(hr.comment);
      if (hr?.status === 'rejected') {
        message.warning('方案评审未通过，流程已阻断，请重新处理本节点');
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '加载方案评审失败');
    } finally {
      setLoading(false);
    }
  }, [synapseApiBase, roomId]);

  useEffect(() => {
    if (!initialPayload) void load();
    else setPayload(initialPayload);
  }, [initialPayload, load]);

  const repos = payload?.func_solution_parsed?.repos ?? [];
  const impact = payload?.func_solution_parsed?.impact_assessment;
  const whale = payload?.whale_review;
  const artifacts = payload?.inputs?.stage2_artifacts ?? [];
  const tasks = payload?.split_tasks_draft ?? [];
  const humanStatus = payload?.human_review?.status ?? 'pending';
  const readOnly = blocked || humanStatus !== 'pending';
  const demandNo = payload?.demand_no ?? '';
  const requirementName = payload?.requirement_name ?? '';

  const branchIds = useMemo(
    () => [...new Set(repos.map((r) => repoBranchId(r)).filter(Boolean))],
    [repos],
  );
  const branchIdsKey = branchIds.join('|');

  useEffect(() => {
    patchFetchedRef.current.clear();
  }, [projectId]);

  useEffect(() => {
    const allowed = new Set(branchIds);
    for (const id of [...patchFetchedRef.current]) {
      if (!allowed.has(id)) patchFetchedRef.current.delete(id);
    }
  }, [branchIdsKey, branchIds]);

  useEffect(() => {
    if (!synapseApiBase || !roomId || readOnly || !branchIds.length) return;

    for (const bid of branchIds) {
      if (patchFetchedRef.current.has(bid)) continue;
      patchFetchedRef.current.add(bid);
      setPatchLoading((p) => ({ ...p, [bid]: true }));
      void fetchPatchVersions(synapseApiBase, roomId, [bid], projectId ?? undefined)
        .then((res) => {
          const list = Array.isArray(res?.patches) ? res.patches : [];
          setPatchOptions((p) => ({ ...p, [bid]: list }));
        })
        .catch((e) => {
          setPatchOptions((p) => ({ ...p, [bid]: [] }));
          const msg = e instanceof Error ? e.message : '加载补丁失败';
          const repo = repos.find((r) => repoBranchId(r) === bid);
          const label = repo ? repoDisplayLabel(repo) : bid;
          message.error(`${label}：${msg}`);
        })
        .finally(() => {
          setPatchLoading((p) => ({ ...p, [bid]: false }));
        });
    }
  }, [synapseApiBase, roomId, branchIdsKey, readOnly, branchIds, projectId, repos]);

  const splitPreviews = useMemo(
    () =>
      repos.length > 0
        ? repos.map((repo) =>
            buildSplitPreviewForRepo(repo, tasks, patchByBranch, demandNo, requirementName),
          )
        : tasks.map((t) => {
            const bid = (t.branch_version_id || '').trim();
            return { ...t, patchName: bid ? patchByBranch[bid] || t.patchName : t.patchName };
          }),
    [repos, tasks, patchByBranch, demandNo, requirementName],
  );

  const submit = async (decision: 'approve' | 'reject') => {
    if (!humanComment.trim() && decision === 'reject') {
      message.warning('不通过时请填写人工评审意见');
      return;
    }
    if (decision === 'approve') {
      for (const repo of repos) {
        const bid = repoBranchId(repo);
        if (!bid) continue;
        if (!patchByBranch[bid]?.trim()) {
          message.warning(`请为「${repoDisplayLabel(repo)}」选择补丁计划`);
          return;
        }
      }
    }
    setSubmitting(true);
    try {
      const patches = branchIds.map((bid) => ({
        branch_version_id: bid,
        patch_name: patchByBranch[bid] || '',
      }));
      await submitSolutionReviewDecision(synapseApiBase, roomId, {
        decision,
        comment: humanComment.trim(),
        patches: decision === 'approve' ? patches : undefined,
      });
      message.success(decision === 'approve' ? '评审通过，已落盘拆单计划并推进流程' : '评审未通过，已阻断流程');
      await load();
      onDecided?.();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && !payload) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        加载方案评审…
      </div>
    );
  }

  if (!payload) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <Alert type="warning" showIcon message="未找到 solution_review.json，请先完成小鲸方案评审技能产出" />
      </div>
    );
  }

  const score = whale?.score ?? 0;
  const reposWithChange = repos.filter((r) => (r.change_summary || '').trim());

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
        {blocked || humanStatus === 'rejected' ? (
          <Alert
            type="error"
            showIcon
            message="方案评审未通过 — 会议室已阻断"
            description="产出物已归档。请根据意见修订方案后，对本节点执行「重新处理」。"
          />
        ) : null}

        {humanStatus === 'approved' ? (
          <Alert type="success" showIcon message="方案评审已通过，拆单计划已落盘" />
        ) : null}

        {/* 小鲸评分 */}
        <section className="rounded-2xl border border-violet-500/25 bg-gradient-to-br from-violet-500/[0.06] via-[color:var(--panel)] to-fuchsia-500/[0.03] p-5 shadow-xl shadow-black/20">
          <SectionHeader
            icon={<Shield className="h-5 w-5" />}
            title="小鲸评分与建议"
            subtitle="综合可靠性、安全性、需求一致性与控熵合规"
            accent="violet"
          />
          <div className="mt-5 flex flex-wrap gap-6 items-center">
            <Progress
              type="circle"
              percent={Math.min(100, Math.max(0, score))}
              size={80}
              strokeColor={score >= 80 ? '#22c55e' : score >= 60 ? '#eab308' : '#ef4444'}
              format={(p) => <span className="text-lg font-bold">{p}</span>}
            />
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">综合评分</div>
              <div className="text-3xl font-bold bg-gradient-to-r from-violet-200 to-fuchsia-200 bg-clip-text text-transparent">
                {score}
              </div>
              <Tag color={whale?.verdict === 'pass' ? 'green' : 'gold'} className="mt-1">
                {VERDICT_LABEL[whale?.verdict ?? ''] ?? whale?.verdict ?? '—'}
              </Tag>
            </div>
            {whale?.score_breakdown ? (
              <div className="flex flex-wrap gap-2 flex-1 min-w-[200px]">
                {Object.entries(whale.score_breakdown).map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded-full border border-violet-500/25 bg-violet-500/10 px-3 py-1 text-xs text-violet-100"
                  >
                    {scoreDimensionLabel(k)} · {formatScoreBreakdownValue(v)}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
          {whale?.summary_markdown ? (
            <div className="mt-4 rounded-xl border border-border/40 bg-black/20 p-4">
              <ReviewMarkdown content={whale.summary_markdown} />
            </div>
          ) : null}
          {(whale?.suggestions ?? []).length > 0 ? (
            <div className="mt-4 space-y-2">
              {(whale?.suggestions ?? []).map((s, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-border/35 bg-gradient-to-r from-muted/10 to-transparent px-4 py-3 text-sm"
                >
                  <Tag color={SEVERITY_COLOR[s.severity || 'info'] || 'default'}>
                    {SEVERITY_LABEL[s.severity || 'info'] ?? s.severity ?? '信息'}
                  </Tag>
                  <span className="ml-2 font-medium">{s.title}</span>
                  <p className="mt-1.5 text-muted-foreground leading-relaxed">{s.detail}</p>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        {/* 改造点概要 */}
        <section className="rounded-2xl border border-blue-500/25 bg-gradient-to-br from-blue-500/[0.05] to-indigo-500/[0.02] p-5">
          <SectionHeader
            icon={<Layers className="h-5 w-5" />}
            title="改造点概要"
            subtitle="来自函数级方案 §1.3 涉及仓库的改造内容摘要"
            accent="blue"
          />
          {reposWithChange.length > 0 ? (
            <div className="mt-4 space-y-3">
              {reposWithChange.map((repo, i) => (
                <div
                  key={`${repoBranchId(repo)}-${i}`}
                  className="relative pl-4 border-l-2 border-blue-500/30 py-1"
                >
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className="font-medium text-foreground">{repoDisplayLabel(repo)}</span>
                    {repo.repo_url ? (
                      <span className="text-[11px] font-mono text-muted-foreground truncate max-w-[280px]">
                        {repo.repo_url}
                      </span>
                    ) : null}
                  </div>
                  <p className="text-[13px] leading-relaxed text-foreground/85 whitespace-pre-wrap">
                    {repo.change_summary}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground italic">暂无改造内容摘要，请检查函数级方案 §1.3</p>
          )}
        </section>

        {/* 影响评估 */}
        <section className="rounded-2xl border border-amber-500/30 bg-gradient-to-br from-amber-500/[0.04] to-orange-500/[0.02] p-5">
          <SectionHeader
            icon={<Shield className="h-5 w-5 text-amber-400" />}
            title="影响评估"
            subtitle="函数级方案 §1.10 多维度影响分析"
            accent="amber"
          />
          <Collapse
            className="mt-4 [&_.ant-collapse-header]:text-foreground!"
            defaultActiveKey={['security', 'upgrade', 'functional']}
            items={[
              {
                key: 'security',
                label: '安全影响',
                children: tableFromRows(impact?.security, [
                  '安全维度',
                  '影响说明',
                  '影响程度',
                  '安全措施',
                  '备注',
                ]),
              },
              {
                key: 'upgrade',
                label: '升级风险',
                children: tableFromRows(impact?.upgrade_risk, [
                  '风险类型',
                  '风险描述',
                  '风险等级',
                  '规避措施',
                  '回滚预案',
                ]),
              },
              {
                key: 'functional',
                label: '功能影响',
                children: tableFromRows(impact?.functional, [
                  '影响类型',
                  '影响模块',
                  '影响说明',
                  '影响范围',
                  '备注',
                ]),
              },
              {
                key: 'performance',
                label: '性能影响',
                children: tableFromRows(impact?.performance, [
                  '变更点',
                  '性能影响类型',
                  '影响程度',
                  '无法规避原因',
                  '规避措施',
                ]),
              },
              {
                key: 'config',
                label: '配置变更',
                children: tableFromRows(impact?.config, [
                  '配置项',
                  '变更类型',
                  '配置位置',
                  '影响范围',
                  '变更说明',
                ]),
              },
              {
                key: 'compat',
                label: '兼容性',
                children: tableFromRows(impact?.compatibility, [
                  '兼容类型',
                  '兼容项',
                  '当前版本',
                  '目标版本',
                  '兼容性评估',
                  '说明',
                ]),
              },
            ]}
          />
        </section>

        {/* 需求设计产出物（仅已纳入） */}
        <section className="rounded-2xl border border-border/50 p-5 bg-[color:var(--panel)]/80">
          <SectionHeader
            icon={<FileText className="h-5 w-5" />}
            title="需求设计阶段产出物"
            subtitle="仅展示已纳入本次评审的归档文档"
            accent="cyan"
          />
          <div className="mt-4">
            <Stage2ArtifactsPanel artifacts={artifacts} synapseApiBase={synapseApiBase} roomId={roomId} />
          </div>
        </section>

        {/* 涉及仓库与补丁选择 — 紧邻拆单预览上方 */}
        <section className="space-y-4">
          <SectionHeader
            icon={<GitBranch className="h-5 w-5" />}
            title="涉及仓库与补丁选择"
            subtitle="按函数级方案仓库清单逐条确认补丁计划（不展示内部分支 ID）"
            accent="cyan"
          />
          {repos.length > 0 ? (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {repos.map((row, i) => {
                const bid = repoBranchId(row);
                return (
                  <RepoPatchCard
                    key={`repo-${bid}-${i}`}
                    index={i}
                    row={row}
                    patchOptions={patchOptions[bid] ?? []}
                    patchLoading={Boolean(patchLoading[bid])}
                    patchFetched={patchFetchedRef.current.has(bid) && !patchLoading[bid]}
                    selectedPatch={bid ? patchByBranch[bid] : undefined}
                    readOnly={readOnly}
                    onPatchChange={(branchId, patch) =>
                      setPatchByBranch((m) => ({ ...m, [branchId]: patch }))
                    }
                  />
                );
              })}
            </div>
          ) : (
            <Alert type="info" showIcon message="函数级方案中未解析到涉及仓库表" className="mt-2" />
          )}
        </section>

        {/* 拆单预览 — 与仓库卡片一一对应 */}
        <section className="space-y-4">
          <SectionHeader
            icon={<Package className="h-5 w-5" />}
            title="拆单预览"
            subtitle="与上方仓库条目一一对应，补丁选择将实时反映到研发单"
            accent="emerald"
          />
          {splitPreviews.length > 0 ? (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {splitPreviews.map((task, i) => (
                <SplitPreviewCard
                  key={`split-${task.branch_version_id}-${i}`}
                  index={i}
                  task={task}
                  repoLabel={repos[i] ? repoDisplayLabel(repos[i]) : task.branchVersionName || '研发子单'}
                />
              ))}
            </div>
          ) : (
            <Alert type="info" showIcon message="暂无拆单预览数据" />
          )}
          <p className="text-[11px] text-muted-foreground text-center">
            评审通过后将按上述预览落盘 split_plan.json 并推进自动拆单节点
          </p>
        </section>

        {/* 人工评审 */}
        <section className="rounded-2xl border border-border/50 p-5">
          <SectionHeader icon={<CheckCircle2 className="h-5 w-5" />} title="人工评审" accent="violet" />
          <div className="mt-4 mb-3 flex items-center gap-2">
            <span className="text-sm text-muted-foreground">状态</span>
            <Tag
              color={
                humanStatus === 'approved' ? 'green' : humanStatus === 'rejected' ? 'red' : 'processing'
              }
            >
              {humanStatus === 'approved' ? '通过' : humanStatus === 'rejected' ? '不通过' : '待评审'}
            </Tag>
          </div>
          <TextArea
            rows={4}
            placeholder="填写人工评审意见（不通过时必填）"
            value={humanComment}
            onChange={(e) => setHumanComment(e.target.value)}
            disabled={readOnly}
          />
        </section>
      </div>

      {!readOnly ? (
        <div className="shrink-0 border-t border-border/50 bg-[color:var(--panel)] px-6 py-4 flex justify-end gap-3">
          <Button
            danger
            icon={<XCircle className="h-4 w-4" />}
            loading={submitting}
            onClick={() => submit('reject')}
          >
            评审不通过
          </Button>
          <Button
            type="primary"
            icon={<CheckCircle2 className="h-4 w-4" />}
            loading={submitting}
            onClick={() => submit('approve')}
          >
            通过并确认拆单
          </Button>
        </div>
      ) : null}
    </div>
  );
}
