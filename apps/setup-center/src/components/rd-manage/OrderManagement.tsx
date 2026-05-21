import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import { ConfigProvider, theme, Badge, Avatar, Button, Drawer, Modal, Tag, Progress, Tabs, Popover, Tooltip, Collapse } from 'antd';
import { motion, AnimatePresence } from 'motion/react';
import {
  GitBranch,
  Bot,
  User,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Play,
  TerminalSquare,
  Clock,
  Zap,
  ShieldAlert,
  MessageSquareText,
  FileCode2,
  Cpu,
  Info,
  Coins,
  FileText,
  Network,
  Code,
  TestTube,
  CheckSquare,
  Activity,
  ClipboardList,
  Flame,
  TrendingUp,
  Loader2,
  AlertCircle,
  Search,
  Banknote,
  RefreshCw,
  ExternalLink
} from 'lucide-react';
import {
  fetchRdManageDemands,
  syncRdManageDemandsFromDevCloud,
  fetchWorkOrderDbMetrics,
  fetchHumanInLoopFlags,
  type DemandListItem,
  type OwnedWorkItem,
  type RdManageDemandsPayload,
  type WorkOrderDbMetricsPayload,
} from '../../api/rdManageService';
import {
  fetchMeetingSummary,
  openMeetingRoom,
  type MeetingRoomArchiveEntry,
  type MeetingSummaryPayload,
} from '../../api/meetingRoomService';
import { setMeetingRoomFocus } from '../../rd-meeting/focus';
import { getProdInfo } from '@/api/rdUnifiedService';
import type { ProdInfoWireItem, ProdProcessDataPayload } from '@/api/rdUnifiedService';
import { IS_TAURI } from '@/platform';
import { ProductDetail } from '@/components/product/ProductDetail';
import {
  Product,
  applyProcessPayloadToProduct,
  patchProductKnowledgeSlots,
  prodInfoWireToProduct,
  prodWireMatchesWorkItemModuleName,
  type ProductKnowledgePatch,
} from '@/components/product/types';
import { ViewId } from '../../types';
import {
  SOP_STAGES,
  ALL_NODES,
  LAST_PIPELINE_STAGE_ID,
  LAST_PIPELINE_NODE_ID,
  resolveSopRawToNodeId,
  stageIdForNodeId,
  type NodeType,
  type SOPNode,
  type SOPStage,
} from '../../rd-sop/constants';

// --- Types & Data ---

export interface WorkItem {
  id: string;
  title: string;
  createdAt: string;
  tokens: number;
  branch: string;
  description: string;
  /** 该研发单对应的流水线当前节点 id（由接口 task sop_node 解析） */
  currentNode: string;
  /** 处理中且本地 sop_trajectories（order_id=task_no）存在人工介入节点时为 true */
  humanIntervention?: boolean;
}

export interface Ticket {
  id: string;
  branch: string;
  title: string;
  currentStage: number;
  currentNode: string;
  status:
    | 'processing'
    | 'full_manual'
    | 'pending'
    | 'completed'
    | 'error'
    | 'prepare';
  /** 需求单维度（无研发子单展示行）：处理中且本地库该 order 最新 sop 轨迹需人工；非工单 status */
  sopAwaitingHuman: boolean;
  owner: string;
  urgency: 'low' | 'medium' | 'high';
  tokens: number;
  runTime: string;
  description: string;
  createdAt: string;
  workItems: WorkItem[];
}

function focusNodeIdForTicket(ticket: Ticket): string {
  if (ticket.status === 'completed') return LAST_PIPELINE_NODE_ID;
  return ticket.currentNode;
}

/** 当前节点圆点中心相对 canvas 的 X（与进度条 `left-16` 同一坐标系，单位 px） */
function getNodeCenterXInCanvas(nodeEl: HTMLElement, canvasEl: HTMLElement): number {
  let x = 0;
  let el: HTMLElement | null = nodeEl;
  while (el && el !== canvasEl) {
    x += el.offsetLeft;
    el = el.offsetParent as HTMLElement | null;
  }
  if (el === canvasEl) {
    return x + nodeEl.offsetWidth / 2;
  }
  // offsetParent 链未落到 canvas（部分布局下会断链）：用视口几何 + 横向缩放还原到布局宽度坐标
  const nr = nodeEl.getBoundingClientRect();
  const cr = canvasEl.getBoundingClientRect();
  const scaleX = cr.width > 1 ? canvasEl.scrollWidth / cr.width : 1;
  return (nr.left + nr.width / 2 - cr.left) * scaleX;
}

/** 主轨道起点与 `left-16` / `px-16` 一致 */
const BUS_LINE_START_PX = 64;

/** Ant Design 与当前 data-theme 同步（避免浅色主题下仍强制暗色算法） */
function useAntThemeDark() {
  const [dark, setDark] = useState(() => {
    if (typeof document === 'undefined') return false;
    const t = document.documentElement.getAttribute('data-theme') || 'light';
    return t === 'dark' || t === 'daltonized-dark' || t === 'high-contrast';
  });
  useEffect(() => {
    const read = () => {
      const t = document.documentElement.getAttribute('data-theme') || 'light';
      setDark(t === 'dark' || t === 'daltonized-dark' || t === 'high-contrast');
    };
    read();
    const m = new MutationObserver(read);
    m.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => m.disconnect();
  }, []);
  return dark;
}

type NodeState =
  | 'completed'
  | 'processing'
  | 'error'
  | 'awaiting_human'
  | 'full_manual'
  | 'pending';

// --- Subcomponents for Outputs ---

const TerminalOutput = ({ lines }: { lines: string[] }) => (
  <div className="max-h-64 overflow-y-auto rounded-lg border border-border bg-[color-mix(in_srgb,var(--background)_88%,#0a0a12)] p-3 font-mono text-xs custom-scrollbar dark:bg-[color-mix(in_srgb,var(--background)_40%,#020617)]">
    {lines.map((line, i) => (
      <div key={i} className="mb-1">
        <span className="mr-2 text-emerald-600 dark:text-emerald-400">$</span>
        <span className={line.includes('Error') ? 'text-red-500 dark:text-red-400' : line.includes('Warning') ? 'text-amber-600 dark:text-amber-400' : 'text-foreground/85'}>
          {line}
        </span>
      </div>
    ))}
  </div>
);

const JsonOutput = ({ data }: { data: any }) => (
  <div className="max-h-64 overflow-auto rounded-lg border border-border bg-[color-mix(in_srgb,var(--background)_88%,#0a0a12)] p-4 font-mono text-xs text-blue-600 custom-scrollbar dark:bg-[color-mix(in_srgb,var(--background)_40%,#020617)] dark:text-blue-300">
    <pre>{JSON.stringify(data, null, 2)}</pre>
  </div>
);

/**

 * 仅「处理中」工单需要查轨迹人工介入；order_id 与左侧展示维度一致：
 * - 仅有需求单（无研发子单）→ 传 demand_no
 * - 有研发子单（按子单展示）→ 只传各 task_no，不传 demand_no
 */
function collectOrderIdsForHitlFlags(list: DemandListItem[]): string[] {
  const ids = new Set<string>();
  for (const d of list) {
    const base = deriveBaseTicketStatus(d);
    if (base !== "processing") continue;
    const owned = d.owned_work_items || [];
    if (owned.length === 0) {
      const dn = (d.demand_no || "").trim();
      if (dn) ids.add(dn);
    } else {
      for (const w of owned) {
        const tid = (w.task_no || "").trim();
        if (tid) ids.add(tid);
      }
    }
  }
  return Array.from(ids);
}

/**
 * 基础态（不含「人工介入」）：人工介入仍仅由「处理中 + sop_trajectories」叠加。
 * 「全人工」表示走外部人工、不进本系统智能流水线，由 local_process_state 单独标识。
 */
function deriveBaseTicketStatus(d: DemandListItem): Ticket["status"] {
  const local = effectiveLocalProcessState(d);
  const isCompleted =
    local === "已完成" ||
    (d.demand_status || "").trim() === "已完成" ||
    (d.demand_status || "").trim() === "completed";
  if (isCompleted) return "completed";
  if (local === "预备中") return "prepare";
  if (local === "待处理") return "pending";
  if (local === "处理中") return "processing";
  if (local === "全人工") return "full_manual";
  if (["需求开发", "开发中", "测试中"].some((x) => (d.demand_status || "").includes(x))) {
    return "processing";
  }
  return "pending";
}

/** 接口可能省略 local_process_state，用需求状态兜底「待处理」 */
function effectiveLocalProcessState(d: DemandListItem): string {
  const s = (d.local_process_state || "").trim();
  if (s) return s;
  if ((d.demand_status || "").trim() === "待处理") return "待处理";
  return "";
}

function mapDemandListItemToTicket(d: DemandListItem, flags: Record<string, boolean>): Ticket {
  const local = effectiveLocalProcessState(d);
  const baseStatus = deriveBaseTicketStatus(d);
  const owned = d.owned_work_items || [];
  const dn = (d.demand_no || "").trim();

  const status: Ticket["status"] = baseStatus;
  const sopAwaitingHuman =
    baseStatus === "processing" && owned.length === 0 && Boolean(dn && flags[dn]);

  let demandNodeId = "pending";
  if (status === "completed") {
    demandNodeId = LAST_PIPELINE_NODE_ID;
  } else if (local === "待处理") {
    // 契约：待处理时需求单一定在「等待调度」，与接口 sop_node 文案无关
    demandNodeId = "pending";
  } else if (local === "预备中") {
    // 契约：预备中时 sop_node 必为空，不解析接口 sop
    demandNodeId = "pending";
  } else if (status === "full_manual") {
    const sop = (d.sop_node || "").trim();
    demandNodeId = resolveSopRawToNodeId(sop) ?? "pending";
  } else if (status === "processing") {
    const sop = (d.sop_node || "").trim();
    demandNodeId = resolveSopRawToNodeId(sop) ?? "pending";
  }

  const runTime =
    (d.demand_deal_time || "").trim() ||
    (d.demand_finish_time || "").trim() ||
    "0h";

  const workItems: WorkItem[] = owned.map((w) => {
    const taskResolved = resolveSopRawToNodeId((w.sop_node || "").trim());
    const currentNode = taskResolved ?? demandNodeId;
    const tid = (w.task_no || "").trim();
    const humanIntervention = baseStatus === "processing" && Boolean(tid && flags[tid]);
    return {
      id: w.task_no,
      title: w.task_title,
      createdAt: w.created_date || new Date().toISOString(),
      tokens: w.sccb_work_hours != null ? Math.round(Number(w.sccb_work_hours) * 60) : 0,
      branch: w.product_module_name || "master",
      description: w.task_desc || "",
      currentNode,
      humanIntervention,
    };
  });

  return {
    id: d.demand_no || `TICKET-${Math.random().toString(36).slice(2, 9)}`,
    title: d.demand_title || "未知需求",
    description: d.demand_desc || "",
    createdAt: d.demand_create_time || new Date().toISOString(),
    runTime,
    tokens: d.demand_sccb_work_minutes || 0,
    status,
    sopAwaitingHuman,
    owner: d.demand_designer || "未知",
    branch: d.product_version_code || "master",
    urgency: "medium",
    currentNode: demandNodeId,
    currentStage: 0,
    workItems,
  };
}

/** demand_impact：JSON 数组时仅展示各条 impactDesc，否则原样返回 */
function formatDemandImpactDisplay(raw: string): string {
  const trimmed = (raw || '').trim();
  if (!trimmed) return '';
  if (!trimmed.startsWith('[')) return trimmed;
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!Array.isArray(parsed)) return trimmed;
    const descs = parsed
      .map((item) => {
        if (item && typeof item === 'object' && 'impactDesc' in item) {
          const desc = (item as { impactDesc?: unknown }).impactDesc;
          return typeof desc === 'string' ? desc.trim() : '';
        }
        return '';
      })
      .filter(Boolean);
    return descs.length > 0 ? descs.join('\n') : trimmed;
  } catch {
    return trimmed;
  }
}

/** 秒 → 可读时长（优先小时/分钟） */
function formatDurationSeconds(totalSec: number, tFormat: (k: string, o?: Record<string, unknown>) => string): string {
  const s = Math.max(0, Math.floor(totalSec));
  if (s < 60) return tFormat('rdManageOrder.seconds', { count: s });
  const m = Math.floor(s / 60);
  if (m < 60) return tFormat('rdManageOrder.minutes', { count: m });
  const h = Math.floor(m / 60);
  const remM = m % 60;
  if (remM === 0) return tFormat('rdManageOrder.hours', { count: h });
  return tFormat('rdManageOrder.hoursMinutes', { hours: h, minutes: remM });
}

function formatTokenCount(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return String(tokens);
}

function demandItemFallbackFromTicket(ticket: Ticket): DemandListItem {
  const items: OwnedWorkItem[] = (ticket.workItems || []).map((w) => ({
    task_no: w.id,
    task_title: w.title,
    task_desc: w.description,
    created_date: w.createdAt,
    sccb_work_hours: null,
    stage_name: '',
    product_module_id: null,
    product_module_name: w.branch,
    repo_url: '',
    sop_node: '',
  }));
  return {
    demand_no: ticket.id,
    demand_title: ticket.title,
    demand_desc: ticket.description,
    demand_create_time: ticket.createdAt,
    demand_finish_time: '',
    demand_sccb_work_minutes: ticket.tokens,
    demand_status: '',
    demand_impact: '',
    demand_designer: ticket.owner,
    product_version_id: null,
    product_version_code: ticket.branch,
    sop_node: '',
    local_process_state: '',
    owned_work_items: items,
  };
}

/** 工单弹窗内：研发子单属性区（与「处理汇总」同款大卡分栏，含仓库） */
function TaskModalWorkItemStats({
  wi,
  tm,
  dbMetricsLoading,
  t,
  onOpenProductModule,
}: {
  wi: OwnedWorkItem;
  tm: { deal_seconds: number; deal_tokens: number } | undefined;
  dbMetricsLoading: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
  onOpenProductModule: () => void;
}) {
  const repo = (wi.repo_url || '').trim();
  const isHttp = /^https?:\/\//i.test(repo);
  const stageText = (wi.stage_name || '—').trim() || '—';
  const stageDone =
    stageText.includes('完成') ||
    stageText.includes('走查') ||
    stageText.toLowerCase().includes('done');

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
          <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
            {t('rdManageOrder.taskDealTime')}
          </div>
          <div className="relative z-10 mt-1 font-mono text-xl font-bold text-foreground sm:text-2xl">
            {dbMetricsLoading && !tm ? '…' : formatDurationSeconds(tm?.deal_seconds ?? 0, t)}
          </div>
          <Clock className="absolute -bottom-2 -right-2 h-14 w-14 text-primary/5 sm:h-16 sm:w-16" />
        </div>
        <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
          <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
            {t('rdManageOrder.taskDealToken')}
          </div>
          <div className="relative z-10 mt-1 font-mono text-xl font-bold text-foreground sm:text-2xl">
            {dbMetricsLoading && !tm ? '…' : (tm?.deal_tokens ?? 0).toLocaleString()}
          </div>
          <Coins className="absolute -bottom-2 -right-2 h-14 w-14 text-primary/5 sm:h-16 sm:w-16" />
        </div>
        <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
          <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
            {t('rdManageOrder.taskCreated')}
          </div>
          <div className="relative z-10 mt-1 text-xs font-medium leading-snug text-foreground sm:text-sm">
            {wi.created_date || '—'}
          </div>
          <ClipboardList className="absolute -bottom-2 -right-2 h-14 w-14 text-primary/5 sm:h-16 sm:w-16" />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
          <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
            {t('rdManageOrder.stageName')}
          </div>
          <div className="relative z-10 mt-2 flex items-center gap-2">
            <Badge status={stageDone ? 'success' : 'processing'} text={<span className="text-sm text-foreground/90">{stageText}</span>} />
          </div>
          <Code className="absolute -bottom-3 -right-2 h-16 w-16 text-primary/5" />
        </div>
        <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
          <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
            {t('rdManageOrder.productModule')}
          </div>
          <div className="relative z-10 mt-2">
            {(wi.product_module_name || '').trim() ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 text-left text-sm font-medium text-primary underline decoration-primary/40 underline-offset-2 transition-colors hover:text-primary/90"
                title={t('rdManageOrder.openProductModule')}
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenProductModule();
                }}
              >
                {wi.product_module_name}
                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
              </button>
            ) : (
              <span className="text-sm text-foreground/80">—</span>
            )}
          </div>
          <Network className="absolute -bottom-3 -right-2 h-16 w-16 text-primary/5" />
        </div>
      </div>
      <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
        <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
          {t('rdManageOrder.repoUrl')}
        </div>
        <div className="relative z-10 mt-2 break-all font-mono text-xs leading-relaxed text-foreground/90">
          {!repo ? (
            <span className="text-muted-foreground">—</span>
          ) : isHttp ? (
            <a href={repo} target="_blank" rel="noopener noreferrer" className="text-primary underline">
              {repo}
            </a>
          ) : (
            repo
          )}
        </div>
        <Network className="absolute -bottom-4 -right-2 h-20 w-20 text-primary/5" />
      </div>
    </div>
  );
}

// --- Main Components ---

export const OrderManagement: React.FC<{
  synapseApiBase?: string;
  onViewChange?: (view: ViewId) => void;
}> = ({ synapseApiBase = "http://127.0.0.1:18900", onViewChange }) => {
  const { t } = useTranslation();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [demandListRaw, setDemandListRaw] = useState<DemandListItem[]>([]);
  const [activeTicketId, setActiveTicketId] = useState<string>('');
  const [activeWorkItemId, setActiveWorkItemId] = useState<string>('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<SOPNode | null>(null);
  const [ticketModalOpen, setTicketModalOpen] = useState(false);
  const [selectedTicketForModal, setSelectedTicketForModal] = useState<Ticket | null>(null);
  const [selectedWorkItemIdForModal, setSelectedWorkItemIdForModal] = useState<string | null>(null);
  const [modalDemand, setModalDemand] = useState<DemandListItem | null>(null);
  const [dbMetrics, setDbMetrics] = useState<WorkOrderDbMetricsPayload | null>(null);
  const [dbMetricsLoading, setDbMetricsLoading] = useState(false);
  const [dbMetricsErr, setDbMetricsErr] = useState<string | null>(null);
  const [detailProduct, setDetailProduct] = useState<Product | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [ticketFilter, setTicketFilter] = useState<
    'prepare' | 'pending' | 'processing' | 'full_manual' | 'all'
  >('all');
  const [searchQuery, setSearchQuery] = useState('');
  /** 看板数据是否已完成首次拉取（用于区分「加载中」与「快照为空」） */
  const [boardDataInitialized, setBoardDataInitialized] = useState(false);
  const [boardRefreshBusy, setBoardRefreshBusy] = useState(false);
  const [openingMeetingKey, setOpeningMeetingKey] = useState<string | null>(null);
  const [meetingSummary, setMeetingSummary] = useState<MeetingSummaryPayload | null>(null);
  const [meetingSummaryLoading, setMeetingSummaryLoading] = useState(false);
  const [meetingSummaryErr, setMeetingSummaryErr] = useState<string | null>(null);

  const [collapsedStages, setCollapsedStages] = useState<Record<number, boolean>>({});
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isDragging = useRef(false);
  const lastMousePos = useRef({ x: 0, y: 0 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const [activeLineWidth, setActiveLineWidth] = useState<number>(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const antDark = useAntThemeDark();

  useEffect(() => {
    if (!ticketModalOpen || !modalDemand) return;
    let cancelled = false;
    setDbMetricsLoading(true);
    setDbMetricsErr(null);
    setDbMetrics(null);
    const taskNos = (modalDemand.owned_work_items || []).map((w) => w.task_no).filter(Boolean);
    void fetchWorkOrderDbMetrics(synapseApiBase, {
      demand_no: modalDemand.demand_no,
      task_nos: taskNos,
    })
      .then((data) => {
        if (!cancelled) setDbMetrics(data);
      })
      .catch((e) => {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setDbMetricsErr(msg);
          toast.error(t("rdManageOrder.metricsLoadFailed", { message: msg }));
        }
      })
      .finally(() => {
        if (!cancelled) setDbMetricsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticketModalOpen, modalDemand, synapseApiBase, t]);

  const sopMeetingScope = useMemo(() => {
    if (!activeTicketId.trim()) return null;
    const taskId = activeWorkItemId.trim();
    if (taskId) {
      return { scopeType: 'task' as const, scopeId: taskId };
    }
    return { scopeType: 'demand' as const, scopeId: activeTicketId.trim() };
  }, [activeTicketId, activeWorkItemId]);

  useEffect(() => {
    if (!sopMeetingScope?.scopeId) {
      setMeetingSummary(null);
      setMeetingSummaryErr(null);
      return;
    }
    let cancelled = false;
    setMeetingSummaryLoading(true);
    setMeetingSummaryErr(null);
    void fetchMeetingSummary(synapseApiBase, sopMeetingScope.scopeType, sopMeetingScope.scopeId)
      .then((data) => {
        if (!cancelled) setMeetingSummary(data);
      })
      .catch((e) => {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setMeetingSummaryErr(msg);
          setMeetingSummary(null);
        }
      })
      .finally(() => {
        if (!cancelled) setMeetingSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sopMeetingScope, synapseApiBase]);

  const meetingNodeMetricsById = useMemo(() => {
    const m = new Map<string, { deal_seconds: number; tokens: number }>();
    for (const n of meetingSummary?.nodes ?? []) {
      m.set(n.node_id, n.metrics);
    }
    return m;
  }, [meetingSummary]);

  const meetingArchiveByNodeId = useMemo(() => {
    const m = new Map<string, MeetingRoomArchiveEntry['files']>();
    for (const entry of meetingSummary?.archive_index ?? []) {
      const prev = m.get(entry.node_id) ?? [];
      m.set(entry.node_id, [...prev, ...entry.files]);
    }
    return m;
  }, [meetingSummary]);

  const mergeProcessIntoProduct = useCallback((productId: string, payload: ProdProcessDataPayload) => {
    setDetailProduct((p) => (p && p.id === productId ? applyProcessPayloadToProduct(p, payload) : p));
  }, []);

  const patchProductKnowledge = useCallback((productId: string, patch: ProductKnowledgePatch) => {
    setDetailProduct((sp) =>
      sp && sp.id === productId
        ? { ...sp, knowledge: patchProductKnowledgeSlots(sp.knowledge, patch) }
        : sp,
    );
  }, []);

  const openProductDetailForWorkItem = useCallback(
    async (wi: OwnedWorkItem) => {
      if (!IS_TAURI) {
        toast.message(t("rdManageOrder.productOpenTauriOnly"));
        return;
      }
      const modName = (wi.product_module_name || "").trim();
      const repoUrl = (wi.repo_url || "").trim();
      try {
        const resp = await getProdInfo(synapseApiBase);
        const raw = Array.isArray(resp.data) ? resp.data : [];
        const rows = raw.filter((row): row is ProdInfoWireItem => row != null);
        const hit =
          (modName && rows.find((r) => prodWireMatchesWorkItemModuleName(r, modName))) ||
          (repoUrl
            ? rows.find(
                (r) =>
                  Array.isArray(r.repo_info) &&
                  r.repo_info.some((repo) => (repo?.repo_url || "").trim() === repoUrl),
              )
            : undefined);
        if (!hit) {
          toast.error(t("rdManageOrder.productNotFound"));
          return;
        }
        setDetailProduct(prodInfoWireToProduct(hit));
        setDetailOpen(true);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(`${t("rdManageOrder.productNotFound")} (${msg})`);
      }
    },
    [synapseApiBase, t],
  );

  const applyBoardPayload = useCallback(
    async (data: RdManageDemandsPayload) => {
      setDemandListRaw(data.list || []);
      const list = data.list || [];
      const orderIds = collectOrderIdsForHitlFlags(list);
      let flags: Record<string, boolean> = {};
      try {
        flags = await fetchHumanInLoopFlags(synapseApiBase, orderIds);
      } catch {
        flags = {};
      }
      const allTickets = list.map((d) => mapDemandListItemToTicket(d, flags));

      allTickets.forEach((tk) => {
        if (tk.status === "completed") {
          tk.currentNode = LAST_PIPELINE_NODE_ID;
          tk.currentStage = LAST_PIPELINE_STAGE_ID;
        } else {
          const stage = SOP_STAGES.find((s) => s.nodes.some((n) => n.id === tk.currentNode));
          tk.currentStage = stage ? stage.id : 0;
        }
      });

      setTickets(allTickets);
      if (allTickets.length > 0) {
        const first = allTickets[0];
        setActiveTicketId(first.id);
        if (first.status === "processing" && first.workItems && first.workItems.length > 0) {
          setActiveWorkItemId(first.workItems[0].id);
        } else {
          setActiveWorkItemId("");
        }
      } else {
        setActiveTicketId("");
        setActiveWorkItemId("");
      }
    },
    [synapseApiBase],
  );

  const refreshWorkOrdersFromDevCloud = useCallback(async () => {
    setBoardRefreshBusy(true);
    try {
      const data = await syncRdManageDemandsFromDevCloud(synapseApiBase);
      await applyBoardPayload(data);
      toast.success(t("rdManageOrder.refreshSuccess"));
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      const msg = raw === "owner_info_missing" ? t("rdManageOrder.userinfoMissing") : raw;
      toast.error(t("rdManageOrder.refreshFailed", { message: msg }));
    } finally {
      setBoardRefreshBusy(false);
    }
  }, [synapseApiBase, t, applyBoardPayload]);

  // Load Data：`GET owner_order_snapshot`；无快照时列表为空；异常时 rdManageService 可回退 Mock
  useEffect(() => {
    let cancelled = false;
    setBoardDataInitialized(false);
    async function loadData() {
      try {
        const data = await fetchRdManageDemands(synapseApiBase);
        if (cancelled) return;
        await applyBoardPayload(data);
      } catch (err) {
        if (!cancelled) console.error("Failed to load demands:", err);
      } finally {
        if (!cancelled) setBoardDataInitialized(true);
      }
    }
    loadData();
    return () => {
      cancelled = true;
    };
  }, [synapseApiBase, applyBoardPayload]);

  const filteredTickets = useMemo(() => {
    return tickets.filter(t => {
      const q = searchQuery.trim().toLowerCase();
      if (q && !(
        t.id.toLowerCase().includes(q) || 
        t.title.toLowerCase().includes(q) || 
        t.description.toLowerCase().includes(q) ||
        t.workItems?.some(w => w.id.toLowerCase().includes(q) || w.title.toLowerCase().includes(q) || w.description.toLowerCase().includes(q))
      )) {
        return false;
      }
      if (ticketFilter === 'pending') return t.status === 'pending';
      if (ticketFilter === 'processing') return t.status === 'processing' || t.status === 'error';
      if (ticketFilter === 'full_manual') return t.status === 'full_manual';
      if (ticketFilter === 'prepare') return t.status === 'prepare';
      return true;
    });
  }, [tickets, ticketFilter, searchQuery]);

  const pendingCount = useMemo(() => tickets.filter(t => t.status === 'pending').length, [tickets]);
  const processingCount = useMemo(() => tickets.filter(t => t.status === 'processing' || t.status === 'error').length, [tickets]);
  const prepareCount = useMemo(() => tickets.filter(t => t.status === 'prepare').length, [tickets]);
  const fullManualCount = useMemo(() => tickets.filter((t) => t.status === 'full_manual').length, [tickets]);

  const activeTicket = useMemo(() => tickets.find(t => t.id === activeTicketId) || tickets[0] || null, [activeTicketId, tickets]);
  const activeWorkItem = useMemo(() => activeTicket?.workItems?.find(w => w.id === activeWorkItemId) || null, [activeTicket, activeWorkItemId]);

  const displayTicket = useMemo(() => {
    if (!activeTicket) return null;
    if (activeWorkItem) {
      const merge: Partial<Ticket> = {
        id: activeWorkItem.id,
        title: activeWorkItem.title,
        createdAt: activeWorkItem.createdAt,
        tokens: activeWorkItem.tokens,
        branch: activeWorkItem.branch,
        description: activeWorkItem.description,
        sopAwaitingHuman: activeWorkItem.humanIntervention,
      };
      if (
        activeTicket.status === "processing" ||
        activeTicket.status === "full_manual"
      ) {
        merge.currentNode = activeWorkItem.currentNode;
        merge.currentStage = stageIdForNodeId(activeWorkItem.currentNode);
      }
      return { ...activeTicket, ...merge };
    }
    return activeTicket;
  }, [activeTicket, activeWorkItem]);

  /** 工单弹窗：从子单 id 解析出要展示的研发单子集（必须在任意提前 return 之前调用，遵守 Hooks 规则） */
  const ticketModalWorkItemsResolved = useMemo(() => {
    const allOwned = modalDemand?.owned_work_items ?? [];
    const workItemIdTrim = (selectedWorkItemIdForModal || '').trim();
    const matched =
      workItemIdTrim.length > 0
        ? allOwned.filter((wi) => (wi.task_no || '').trim() === workItemIdTrim)
        : [];
    const singleTaskMode = Boolean(workItemIdTrim && matched.length > 0);
    const displayWorkItems = singleTaskMode ? matched : allOwned;
    return { workItemIdTrim, matched, singleTaskMode, displayWorkItems };
  }, [modalDemand, selectedWorkItemIdForModal]);

  const getNodeStateGlobal = (ticket: Ticket | null, nodeId: string): NodeState => {
    if (!ticket) return 'pending';
    
    const targetNode = ALL_NODES.find(n => n.id === nodeId);
    if (!targetNode) return 'pending';

    // Fallback Mock Logic
    if (ticket.status === 'completed') return 'completed';
    if (ticket.status === 'prepare') return 'pending';
    if (ticket.status === 'full_manual') return 'pending';
    if (ticket.status === 'pending') {
      if (nodeId === 'pending') return 'processing';
      return 'pending';
    }

    const targetIndex = ALL_NODES.findIndex(n => n.id === nodeId);
    const currentIndex = ALL_NODES.findIndex(n => n.id === ticket.currentNode);

    if (targetIndex < currentIndex) return 'completed';
    if (targetIndex > currentIndex) return 'pending';

    // Target is the current node
    if (ticket.status === 'processing') {
      if (ticket.sopAwaitingHuman) {
        const node = ALL_NODES[targetIndex];
        if (node && node.type.includes('human')) return 'awaiting_human';
        return 'error';
      }
      return 'processing';
    }
    if (ticket.status === 'error') return 'error';
    return 'pending';
  };

  // Simulate real-time token consumption for processing tickets
  useEffect(() => {
    const interval = setInterval(() => {
      setTickets(prev => prev.map(t => {
        if (t.status === 'processing') {
          return {
            ...t,
            tokens: t.tokens + Math.floor(Math.random() * 80) + 20,
            workItems: t.workItems?.map(w => ({
              ...w,
              tokens: w.tokens + Math.floor(Math.random() * 40) + 10
            }))
          };
        }
        return t;
      }));
    }, 1500);
    return () => clearInterval(interval);
  }, []);

  // Handle auto-scroll to current / 已完成时最后一个 SOP 节点
  useEffect(() => {
    if (!displayTicket || !canvasRef.current || !containerRef.current) return;
    if (
      displayTicket.status === 'prepare' ||
      displayTicket.status === 'full_manual'
    )
      return;
    const timeoutId = setTimeout(() => {
      const focusId = focusNodeIdForTicket(displayTicket);
      const activeNodeElement = document.getElementById(`node-${focusId}`);
      if (activeNodeElement) {
        const nodeRect = activeNodeElement.getBoundingClientRect();
        const canvasRect = canvasRef.current!.getBoundingClientRect();
        const containerRect = containerRef.current!.getBoundingClientRect();
        
        // Calculate node center relative to canvas (unscaled)
        const nodeCenterX = (nodeRect.left - canvasRect.left + nodeRect.width / 2) / transform.scale;
        
        const targetX = containerRect.width / 2 - nodeCenterX * transform.scale;
        
        setTransform(prev => ({
          ...prev,
          x: targetX,
          y: 0 // keep Y at 0 for horizontal pipeline
        }));
      }
    }, 150);
    return () => clearTimeout(timeoutId);
  }, [displayTicket?.id, displayTicket?.currentNode, displayTicket?.status]);

  // Auto-collapse completed stages（最后一阶段「代码走查」不折叠，避免与进度/节点展示错位）
  useEffect(() => {
    if (!displayTicket) return;
    const newCollapsed: Record<number, boolean> = {};
    SOP_STAGES.forEach(stage => {
      if (stage.id === LAST_PIPELINE_STAGE_ID) return;
      const isStageCompleted = stage.nodes.every(n => getNodeStateGlobal(displayTicket, n.id) === 'completed');
      if (isStageCompleted) {
        newCollapsed[stage.id] = true;
      }
    });
    setCollapsedStages(newCollapsed);
  }, [displayTicket?.id, displayTicket?.currentNode]);

  // Calculate Active Line Width based on DOM elements
  const measureActiveLineWidth = useCallback(() => {
    const canvas = canvasRef.current;
    if (!displayTicket || !canvas) return;

    if (displayTicket.status === 'completed') {
      const nodeEl = document.getElementById(`node-${LAST_PIPELINE_NODE_ID}`);
      if (nodeEl) {
        const centerX = getNodeCenterXInCanvas(nodeEl, canvas);
        const maxW = Math.max(0, canvas.scrollWidth - BUS_LINE_START_PX * 2);
        setActiveLineWidth(Math.min(Math.max(0, centerX - BUS_LINE_START_PX), maxW));
      } else {
        setActiveLineWidth(Math.max(0, canvas.scrollWidth - BUS_LINE_START_PX * 2));
      }
      return;
    }
    if (displayTicket.status === 'prepare') {
      setActiveLineWidth(0);
      return;
    }
    if (displayTicket.status === 'full_manual') {
      setActiveLineWidth(0);
      return;
    }
    if (displayTicket.status === 'pending') {
      const nodeEl = document.getElementById('node-pending');
      if (nodeEl) {
        const centerX = getNodeCenterXInCanvas(nodeEl, canvas);
        const maxW = Math.max(0, canvas.scrollWidth - BUS_LINE_START_PX * 2);
        setActiveLineWidth(Math.min(Math.max(0, centerX - BUS_LINE_START_PX), maxW));
      } else {
        setActiveLineWidth(0);
      }
      return;
    }

    const nodeEl = document.getElementById(`node-${displayTicket.currentNode}`);
    if (!nodeEl) return;

    const centerX = getNodeCenterXInCanvas(nodeEl, canvas);
    const maxW = Math.max(0, canvas.scrollWidth - BUS_LINE_START_PX * 2);
    setActiveLineWidth(Math.min(Math.max(0, centerX - BUS_LINE_START_PX), maxW));
  }, [displayTicket]);

  useEffect(() => {
    let raf = 0;
    const run = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        requestAnimationFrame(measureActiveLineWidth);
      });
    };
    run();
    const t = window.setTimeout(run, 80);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(t);
    };
  }, [displayTicket, collapsedStages, measureActiveLineWidth]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => measureActiveLineWidth());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [measureActiveLineWidth]);

  // Canvas Pan & Zoom
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        const zoomSensitivity = 0.002;
        const delta = -e.deltaY * zoomSensitivity;
        setTransform(prev => {
          const newScale = Math.min(Math.max(0.2, prev.scale * (1 + delta)), 3);
          const rect = container.getBoundingClientRect();
          const mouseX = e.clientX - rect.left;
          const mouseY = e.clientY - rect.top;
          const canvasX = (mouseX - prev.x) / prev.scale;
          const canvasY = (mouseY - prev.y) / prev.scale;
          return { x: mouseX - canvasX * newScale, y: 0, scale: newScale };
        });
      } else {
        setTransform(prev => ({
          ...prev,
          x: prev.x - e.deltaX - e.deltaY,
          y: 0
        }));
      }
    };
    
    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, []);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button === 0 || e.button === 1 || e.button === 2) {
      if ((e.target as HTMLElement).closest('.node-card') || (e.target as HTMLElement).closest('.stage-collapse-btn')) return;
      isDragging.current = true;
      lastMousePos.current = { x: e.clientX, y: e.clientY };
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dx = e.clientX - lastMousePos.current.x;
    setTransform(prev => ({
      ...prev,
      x: prev.x + dx,
      y: 0
    }));
    lastMousePos.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  const handleNodeClick = (node: SOPNode) => {
    setSelectedNode(node);
    setDrawerOpen(true);
  };

  const handleShowTicketDetails = (e: React.MouseEvent, ticket: Ticket, workItemId?: string) => {
    e.stopPropagation();
    const raw = demandListRaw.find((d) => (d.demand_no || "").trim() === ticket.id.trim());
    setModalDemand(raw ?? demandItemFallbackFromTicket(ticket));
    setSelectedTicketForModal(ticket);
    setSelectedWorkItemIdForModal(workItemId || null);
    setTicketModalOpen(true);
  };

  const handleJumpToMeeting = (roomId?: string, scopeType?: 'demand' | 'task', scopeId?: string) => {
    if (roomId) {
      setMeetingRoomFocus({ roomId, scopeType, scopeId });
    }
    if (onViewChange) {
      onViewChange("workbench_meeting");
    } else {
      window.dispatchEvent(new CustomEvent('changeView', { detail: 'workbench_meeting' }));
    }
  };

  const handleOneClickOpenMeeting = useCallback(
    async (e: React.MouseEvent, ticket: Ticket, workItemId?: string) => {
      e.stopPropagation();
      const scopeType = workItemId ? ('task' as const) : ('demand' as const);
      const scopeId = (workItemId || ticket.id).trim();
      if (!scopeId) return;
      const busyKey = `${scopeType}:${scopeId}`;
      setOpeningMeetingKey(busyKey);
      try {
        const detail = await openMeetingRoom(synapseApiBase, scopeType, scopeId, {
          promoteToProcessing: true,
          autoRunFirstNode: false,
        });
        setMeetingRoomFocus({
          roomId: detail.room_id,
          scopeType,
          scopeId,
        });
        setActiveTicketId(ticket.id);
        setActiveWorkItemId(workItemId || '');
        toast.success(t('rdManageOrder.openMeetingSuccess'));
        if (onViewChange) {
          onViewChange('workbench_meeting');
        } else {
          window.dispatchEvent(new CustomEvent('changeView', { detail: 'workbench_meeting' }));
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error(t('rdManageOrder.openMeetingFailed', { message: msg }));
      } finally {
        setOpeningMeetingKey(null);
      }
    },
    [synapseApiBase, t, onViewChange],
  );

  const renderMeetingArchiveOutput = (nodeId: string) => {
    const files = meetingArchiveByNodeId.get(nodeId);
    if (!files?.length) return null;
    return (
      <div className="space-y-3">
        <h4 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <FileText className="h-4 w-4" />
          {t('rdManageOrder.nodeArchiveTitle', { defaultValue: '归档产物' })}
        </h4>
        <motion.div className="grid grid-cols-1 gap-2">
          {files.map((f) => (
            <div
              key={`${f.relative_path}-${f.name}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 p-3"
            >
              <div className="flex min-w-0 items-center gap-3">
                <FileCode2 className="h-5 w-5 shrink-0 text-primary" />
                <span className="truncate font-mono text-sm text-foreground">{f.name}</span>
              </div>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                {(f.size / 1024).toFixed(1)} KB
              </span>
            </div>
          ))}
        </motion.div>
        <p className="font-mono text-[10px] text-muted-foreground">{files[0]?.relative_path}</p>
      </div>
    );
  };

  // Render varied output based on node type/id
  const renderNodeOutput = (node: SOPNode, ticket: Ticket) => {
    const state = getNodeStateGlobal(ticket, node.id);
    if (state === 'pending') {
      return (
        <div className="flex h-40 flex-col items-center justify-center text-muted-foreground">
          <CircleDashed className="mb-3 h-10 w-10 opacity-50" />
          <p>节点未开始执行，暂无输出产物</p>
        </div>
      );
    }

    const archiveUi = renderMeetingArchiveOutput(node.id);
    if (archiveUi) return archiveUi;

    switch (node.id) {
      case 'req_clarify':
        return (
          <div className="flex flex-col border border-slate-800 rounded-xl overflow-hidden h-[300px]">
            <div className="bg-slate-900 p-3 border-b border-slate-800 text-sm font-medium text-slate-300 flex items-center gap-2">
              <MessageSquareText className="w-4 h-4" /> AI 澄清会话记录
            </div>
            <div className="flex-1 bg-[#0a0a0a] p-4 flex flex-col gap-4 overflow-y-auto">
              <div className="self-start bg-slate-800 text-slate-200 p-3 rounded-2xl rounded-tl-sm max-w-[85%] text-sm">
                发现需求中关于“实时同步”的具体延迟要求不明确，请问期望的同步延迟是在毫秒级还是秒级？
              </div>
              <div className="self-end bg-blue-600 text-white p-3 rounded-2xl rounded-tr-sm max-w-[85%] text-sm">
                期望在500ms以内完成双向同步。
              </div>
            </div>
          </div>
        );
      case 'boundary':
        return (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-slate-400">领域边界分析图谱</h4>
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 flex flex-col items-center gap-4">
              <div className="px-4 py-2 bg-indigo-900/40 border border-indigo-500/50 rounded-lg text-indigo-300 text-sm">
                知识库同步模块 (Core)
              </div>
              <div className="h-6 w-0.5 bg-slate-700" />
              <div className="flex gap-4">
                <div className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-400 text-xs">文档解析服务</div>
                <div className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-400 text-xs">向量检索引擎</div>
              </div>
            </div>
            <p className="text-xs text-green-400 mt-2 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> 已确认边界独立，无跨产品影响</p>
          </div>
        );
      case 'module_func':
      case 'func_assign':
      case 'auto_split':
        return (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-slate-400 flex items-center gap-2"><Network className="w-4 h-4" /> 结构拆分结果</h4>
            <JsonOutput data={{
              modules: [
                { id: "mod_1", name: "Sync Listener", agent: "Agent-Alpha", status: "assigned" },
                { id: "mod_2", name: "Vector Indexer", agent: "Agent-Beta", status: "assigned" }
              ]
            }} />
          </div>
        );
      case 'entropy_gen':
        return (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-slate-400">生成的控熵文件</h4>
            <div className="grid grid-cols-2 gap-3">
              {['agent.md', 'rule.md', 'skills.md', 'tools.md'].map(file => (
                <div key={file} className="flex items-center gap-3 p-3 bg-slate-900 border border-slate-800 rounded-lg hover:border-blue-500/50 cursor-pointer transition-colors">
                  <FileCode2 className="w-5 h-5 text-blue-400" />
                  <span className="text-sm text-slate-300 font-mono">{file}</span>
                </div>
              ))}
            </div>
          </div>
        );
      case 'exception_check':
        if (state === 'awaiting_human') {
          return (
            <div className="space-y-4">
              <div className="bg-red-950/30 border border-red-900/50 rounded-xl p-4 flex items-start gap-3">
                <ShieldAlert className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-red-400 font-medium mb-1">沙箱执行异常中断</h4>
                  <p className="text-sm text-slate-300 font-mono bg-black/40 p-2 rounded mt-2">
                    Error: Agent lock deadlocked in module 'sync_service'. Timeout waiting for mutex release.
                  </p>
                </div>
              </div>
              <Button type="primary" block size="large" className="bg-amber-600 hover:bg-amber-500 border-none" onClick={handleJumpToMeeting}>
                跳转研发会议室 (预置 TODO)
              </Button>
            </div>
          );
        }
        return <TerminalOutput lines={["[INFO] Check passed. No anomalies detected in execution logs."]} />;
      case 'sandbox_build':
      case 'env_pregen':
      case 'env_start':
        return (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-slate-400 flex items-center gap-2"><TerminalSquare className="w-4 h-4" /> 环境执行日志</h4>
            <TerminalOutput lines={[
              "Downloading base image ubuntu:22.04...",
              "Extracting layer 1/5...",
              "Extracting layer 5/5...",
              "Cloning repository branch " + ticket.branch + "...",
              "Applying entropy rules: agent.md, rule.md...",
              "Environment setup completed successfully in 12s."
            ]} />
          </div>
        );
      case 'task_exec':
        if (state === 'awaiting_human') {
          return (
            <div className="flex flex-col items-center justify-center h-48 bg-blue-950/20 border border-blue-900/50 rounded-xl border-dashed">
              <Play className="w-12 h-12 text-blue-500 mb-4 ml-1" />
              <p className="text-sm text-slate-300 mb-5">环境就绪，等待人工确认启动智能研发任务</p>
              <Button type="primary" size="large" className="bg-blue-600 hover:bg-blue-500 border-none px-8" onClick={handleJumpToMeeting}>
                进入研发会议室确认启动
              </Button>
            </div>
          );
        }
        return <div className="text-sm text-slate-400 bg-slate-900 p-4 rounded-lg">任务已启动并由系统接管。</div>;
      case 'unit_test':
        return (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-slate-400 flex items-center gap-2"><TestTube className="w-4 h-4" /> 单元测试结果</h4>
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm text-slate-300">测试覆盖率</span>
                <span className="text-green-400 font-mono">94.2%</span>
              </div>
              <Progress percent={94.2} strokeColor="#4ade80" trailColor="#1e293b" showInfo={false} />
              <div className="mt-4 space-y-2">
                <div className="flex items-center gap-2 text-sm text-slate-400"><CheckCircle2 className="w-4 h-4 text-green-500" /> test_vector_sync.py (Passed)</div>
                <div className="flex items-center gap-2 text-sm text-slate-400"><CheckCircle2 className="w-4 h-4 text-green-500" /> test_db_listener.py (Passed)</div>
              </div>
            </div>
          </div>
        );
      case 'leader_review':
        return (
          <div className="space-y-4">
            <h4 className="text-sm font-medium text-slate-400">审批人列表</h4>
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between bg-slate-900 p-3 rounded-lg border border-slate-800">
                <div className="flex items-center gap-3">
                  <Avatar className="bg-blue-500">张</Avatar>
                  <div>
                    <div className="text-sm text-slate-200">张三 (架构师)</div>
                    <div className="text-xs text-slate-500">代码架构规范审查</div>
                  </div>
                </div>
                {state === 'awaiting_human' ? <Badge status="warning" text="审核中" /> : <Badge status="success" text="已通过" />}
              </div>
              <div className="flex items-center justify-between bg-slate-900 p-3 rounded-lg border border-slate-800">
                <div className="flex items-center gap-3">
                  <Avatar className="bg-purple-500">李</Avatar>
                  <div>
                    <div className="text-sm text-slate-200">李四 (研发组长)</div>
                    <div className="text-xs text-slate-500">业务逻辑综合审查</div>
                  </div>
                </div>
                {state === 'awaiting_human' ? (
                   <Button type="primary" size="small" className="bg-blue-600 text-xs border-none" onClick={handleJumpToMeeting}>
                     去研发会议室审批
                   </Button>
                ) : (
                   <Badge status="success" text="已通过" />
                )}
              </div>
            </div>
          </div>
        );
      default:
        // Generic fallback for AI nodes
        if (node.type === 'ai') {
          return (
            <div className="space-y-3">
              <h4 className="text-sm font-medium text-slate-400 flex items-center gap-2"><Activity className="w-4 h-4" /> AI 处理分析报告</h4>
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 text-sm text-slate-300 leading-relaxed">
                <p>模块 [{node.name}] 处理完成。</p>
                <p className="mt-2 text-slate-500">该环节由智能体自动分析完成，已生成标准结构化输出并传递给下游节点。详细日志已归档至系统存储区。</p>
              </div>
            </div>
          );
        }
        return (
          <div className="text-sm text-slate-400 bg-slate-900 p-4 rounded-lg">
            人工或系统节点已处理完成。
          </div>
        );
    }
  };

  if (!displayTicket) {
    if (!boardDataInitialized) {
      return (
        <div className="flex h-full min-h-0 flex-1 items-center justify-center text-muted-foreground">
          {t("rdManageOrder.loadingBoard")}
        </div>
      );
    }
    return (
      <div className="flex h-full min-h-0 flex-1 flex-col items-center justify-center gap-4 bg-background px-6 text-center text-muted-foreground">
        <FileText className="h-10 w-10 opacity-40" />
        <p className="max-w-md text-sm leading-relaxed">{t("rdManageOrder.emptySnapshot")}</p>
        <Button
          type="primary"
          onClick={() => void refreshWorkOrdersFromDevCloud()}
          disabled={boardRefreshBusy}
          icon={
            boardRefreshBusy ? (
              <Loader2 className="h-4 w-4 animate-spin app-loading-spin" aria-hidden />
            ) : undefined
          }
        >
          {t("rdManageOrder.refresh")}
        </Button>
      </div>
    );
  }

  const showTicketModalPipelineLayers =
    !!selectedTicketForModal &&
    !['prepare', 'pending', 'full_manual'].includes(selectedTicketForModal.status);
  const modalDemandMetrics = dbMetrics?.demand_metrics;
  const modalSummaryMetrics = dbMetrics?.summary;

  return (
    <ConfigProvider theme={{ algorithm: antDark ? theme.darkAlgorithm : theme.defaultAlgorithm }}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-1 overflow-hidden bg-background font-sans text-foreground">
        
        {/* Left Panel: 与会话列表同宽 */}
        <div className="z-20 flex w-[340px] min-w-[340px] shrink-0 flex-col border-r border-border bg-[color:var(--panel)]">
          <div className="convSidebarHeader">
            <div className="flex items-start justify-between gap-2">
              <h2 className="flex min-w-0 flex-1 items-center gap-2 text-sm font-semibold text-foreground">
              <FileText className="h-4 w-4 shrink-0 text-primary" />
              智能任务看板
              <Tooltip
                title="研发云工单请先进入需求设计环节，才能使用智能研发助手进行处理！"
                placement="topLeft"
                overlayStyle={{ maxWidth: 280 }}
              >
                <span className="inline-flex shrink-0 cursor-help text-muted-foreground transition-colors hover:text-foreground">
                  <Info className="h-3.5 w-3.5" aria-hidden />
                </span>
              </Tooltip>
              </h2>
              <Button
                type="text"
                size="small"
                className="shrink-0 !text-muted-foreground hover:!text-foreground"
                disabled={boardRefreshBusy}
                icon={
                  boardRefreshBusy ? (
                    <Loader2 className="h-4 w-4 animate-spin app-loading-spin" aria-hidden />
                  ) : (
                    <RefreshCw className="h-4 w-4" aria-hidden />
                  )
                }
                onClick={() => void refreshWorkOrdersFromDevCloud()}
                aria-label={t("rdManageOrder.refresh")}
                title={t("rdManageOrder.refresh")}
              />
            </div>
            
            <div className="mt-2 flex items-center rounded-lg border border-border bg-background px-2.5 py-1.5 focus-within:ring-1 focus-within:ring-primary/50">
              <Search className="h-3.5 w-3.5 opacity-70 text-muted-foreground" />
              <input 
                type="text" 
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="搜索工单ID、名称或描述..." 
                className="ml-2 flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
              />
            </div>

            <div className="mt-2 flex w-full min-w-0 flex-wrap items-center justify-between gap-1">
              {([
                { id: 'prepare' as const, label: '预备中', count: prepareCount, color: 'text-blue-400' },
                { id: 'pending' as const, label: '待处理', count: pendingCount, color: 'text-muted-foreground' },
                { id: 'processing' as const, label: '处理中', count: processingCount, color: 'text-primary' },
                {
                  id: 'full_manual' as const,
                  label: t('rdManageOrder.boardFilterFullManual'),
                  count: fullManualCount,
                  color: 'text-violet-500 dark:text-violet-400',
                },
              ]).map((filter) => (
                <button
                  key={filter.id}
                  onClick={() => setTicketFilter(prev => (prev === filter.id ? 'all' : filter.id))}
                  className={`group relative flex min-w-0 flex-1 shrink items-center justify-center gap-0.5 rounded-full px-1.5 py-1 transition-all duration-200 ${
                    ticketFilter === filter.id 
                      ? 'bg-muted/50 shadow-sm ring-1 ring-border/50' 
                      : 'hover:bg-muted/30'
                  }`}
                >
                  <span className={`whitespace-nowrap text-xs font-medium transition-colors ${ticketFilter === filter.id ? filter.color : 'text-muted-foreground group-hover:text-foreground/80'}`}>
                    {filter.label}
                  </span>
                  <span className={`rounded-full px-1.5 py-0.5 font-mono text-[10px] transition-colors ${
                    ticketFilter === filter.id 
                      ? 'bg-background text-foreground shadow-sm' 
                      : 'bg-muted/40 text-muted-foreground/70'
                  }`}>
                    {filter.count}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="convSidebarList flex flex-1 flex-col gap-1 overflow-y-auto p-1">
            {filteredTickets.map(ticket => {
              const renderCard = (item: Ticket | WorkItem, isWorkItem: boolean) => {
                const isDone = ticket.status === 'completed';
                const nodeIdForRow = isWorkItem ? (item as WorkItem).currentNode : ticket.currentNode;
                const currentNodeObj = ALL_NODES.find(n => n.id === nodeIdForRow);
                const rowStageId = isWorkItem
                  ? stageIdForNodeId((item as WorkItem).currentNode)
                  : ticket.currentStage;
                const progressPercent = Math.round((rowStageId / (SOP_STAGES.length - 1)) * 100);

                const rowHitl = !isWorkItem
                  ? ticket.sopAwaitingHuman
                  : Boolean((item as WorkItem).humanIntervention);
                /** 待处理：一键开会；需人工介入：立即处理 */
                const rowPendingOpen = !isWorkItem && ticket.status === 'pending';
                const rowActionOverlay = rowPendingOpen || rowHitl;
                const openMeetingBusyKey = `${isWorkItem ? 'task' : 'demand'}:${item.id}`;
                const rowFullManual = !isWorkItem && ticket.status === 'full_manual';
                /** 预备中 / 全人工不参与本流水线，卡片上不应展示「等待调度」等节点名 */
                const hidePipelineNodeLabel =
                  !isWorkItem && (ticket.status === 'prepare' || ticket.status === 'full_manual');

                const statusBorderColor = rowHitl
                  ? 'bg-destructive'
                  : rowFullManual
                    ? 'bg-violet-500 dark:bg-violet-400'
                    : ticket.status === 'processing'
                      ? 'bg-primary'
                      : ticket.status === 'completed'
                        ? 'bg-green-600 dark:bg-green-500'
                        : 'bg-muted-foreground/40';

                const isActive = isWorkItem ? activeWorkItemId === item.id : activeTicketId === item.id && !activeWorkItemId;

                const onTicketDetailsClick = (e: React.MouseEvent) => {
                  e.stopPropagation();
                  handleShowTicketDetails(e, {
                    ...ticket,
                    title: item.title,
                    description: item.description,
                    branch: item.branch,
                    tokens: item.tokens,
                    createdAt: item.createdAt,
                    currentNode: isWorkItem ? (item as WorkItem).currentNode : ticket.currentNode,
                    currentStage: isWorkItem
                      ? stageIdForNodeId((item as WorkItem).currentNode)
                      : ticket.currentStage,
                    sopAwaitingHuman: isWorkItem
                      ? Boolean((item as WorkItem).humanIntervention)
                      : ticket.sopAwaitingHuman,
                  }, isWorkItem ? item.id : undefined);
                };

                const ticketInfoButton = (
                  <Button
                    type="text"
                    size="small"
                    icon={<Info className="h-3.5 w-3.5" />}
                    className="z-10 flex h-6 w-6 items-center justify-center p-0 text-muted-foreground hover:text-primary"
                    title="工单信息"
                    onClick={onTicketDetailsClick}
                  />
                );

                return (
                  <motion.div
                    key={item.id}
                    whileHover={{ scale: 1.01 }}
                    whileTap={{ scale: 0.99 }}
                    onClick={() => {
                      setActiveTicketId(ticket.id);
                      setActiveWorkItemId(isWorkItem ? item.id : '');
                    }}
                    className={`group relative mb-1 cursor-pointer overflow-hidden rounded-[10px] px-2.5 py-3 transition-[background,box-shadow] duration-150 ${
                      isActive 
                        ? 'bg-[rgba(37,99,235,0.09)] ring-1 ring-border' 
                        : 'hover:bg-[rgba(37,99,235,0.05)]'
                    }`}
                  >
                    {/* Left Status Line */}
                    <div className={`absolute bottom-0 left-0 top-0 w-1 ${statusBorderColor}`} />

                    {rowActionOverlay && (
                      <div className="absolute inset-0 z-30 flex items-center justify-center bg-background/40 opacity-0 backdrop-blur-[2px] transition-opacity duration-300 group-hover:opacity-100">
                        <Button
                          type="primary"
                          size="small"
                          loading={openingMeetingKey === openMeetingBusyKey}
                          className={`h-8 rounded-full border-none px-5 font-medium shadow-lg ${
                            rowPendingOpen
                              ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                              : 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
                          }`}
                          onClick={(e) => {
                            void handleOneClickOpenMeeting(e, ticket, isWorkItem ? item.id : undefined);
                          }}
                        >
                          {rowPendingOpen ? t('rdManageOrder.oneClickOpenMeeting') : t('rdManageOrder.actNow')}
                        </Button>
                      </div>
                    )}

                    <div
                      className={`absolute right-2 top-2 flex items-center gap-2 ${rowActionOverlay ? 'z-40' : 'z-20'}`}
                    >
                      {ticketInfoButton}
                    </div>

                    {/* Top: Created At */}
                    <div className="mb-2 flex items-center pl-2 pr-10">
                      <span className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground/80">
                        <Clock className="h-3 w-3 opacity-70" />
                        {item.createdAt.replace('T', ' ').substring(0, 16)}
                      </span>
                    </div>
                    
                    {/* Middle: Title */}
                    <h3 className={`mb-3 line-clamp-2 pl-2 pr-10 text-sm font-medium flex items-start gap-1.5 ${isActive ? 'text-primary' : 'text-foreground'}`}>
                      {!isWorkItem && ticket.urgency === 'high' && (
                        <Flame className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-pulse text-destructive" />
                      )}
                      {isWorkItem && <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary/70" />}
                      {item.title}
                    </h3>

                    {/* Bottom: Node Info & Meta */}
                    <div className="flex items-center justify-between pl-2 pr-2 text-xs text-muted-foreground">
                      <div className="flex min-w-0 items-center gap-1.5">
                        {isDone ? (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600 dark:text-green-400" />
                        ) : currentNodeObj?.type.includes('human') ? (
                          <User className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                        ) : currentNodeObj?.type.includes('system') ? (
                          <TerminalSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <Bot className="h-3.5 w-3.5 shrink-0 text-primary" />
                        )}
                        <span className={`truncate ${isDone ? 'text-green-700 dark:text-green-400' : 'text-foreground/90'}`}>
                          {isDone
                            ? '研发完成'
                            : hidePipelineNodeLabel
                              ? '待处理'
                              : (currentNodeObj?.name || '未知节点')}
                        </span>
                      </div>
                      
                      <div className="flex shrink-0 items-center gap-2 font-mono text-[10px]">
                        <span className="relative flex items-center gap-1">
                          <Coins className={`h-3 w-3 ${ticket.status === 'processing' || rowHitl ? 'text-amber-500' : 'text-amber-500/70'}`} />
                          <span className={ticket.status === 'processing' || rowHitl ? 'text-amber-500' : 'text-amber-600/70 dark:text-amber-400/70'}>
                            {item.tokens >= 1000 ? (item.tokens/1000).toFixed(1) + 'k' : item.tokens}
                          </span>
                          {(ticket.status === 'processing' || rowHitl) && (
                            <motion.div
                              initial={{ y: 5, opacity: 0 }}
                              animate={{ y: -10, opacity: [0, 1, 0] }}
                              transition={{ repeat: Infinity, duration: 1.5 }}
                              className="absolute -right-3 -top-1 text-green-500"
                            >
                              <TrendingUp className="h-2.5 w-2.5" />
                            </motion.div>
                          )}
                        </span>
                      </div>
                    </div>

                    {/* Background Progress Bar */}
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-border/40">
                      <motion.div 
                        className={`h-full ${ticket.status === 'completed' ? 'bg-green-500' : 'bg-gradient-to-r from-primary via-primary/70 to-primary bg-[length:200%_100%]'}`}
                        style={{ width: ticket.status === 'completed' ? '100%' : ticket.status === 'pending' || ticket.status === 'prepare' || ticket.status === 'full_manual' ? '0%' : `${progressPercent}%` }} 
                        animate={(ticket.status === 'processing' || rowHitl) ? { backgroundPosition: ['100% 0', '-100% 0'] } : {}}
                        transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
                      />
                    </div>
                  </motion.div>
                );
              };

              if (ticket.status === 'processing' && ticket.workItems && ticket.workItems.length > 0) {
                return (
                  <div key={ticket.id} className="relative mb-2 mt-3 rounded-[10px] border border-dashed border-primary/40 p-1.5 pt-3">
                    <div className="absolute -top-2.5 left-2 right-2 min-w-0 truncate bg-[color:var(--panel)] px-1 text-[10px] font-medium text-primary">
                      {ticket.title}
                    </div>
                    {ticket.workItems.map(workItem => renderCard(workItem, true))}
                  </div>
                );
              }

              return renderCard(ticket, false);
            })}
          </div>
        </div>

        {/* Right: 流水线（背景与主内容区一致，仅轨道区略提亮） */}
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
          
          <div className="chatTopBar z-20 min-h-[4.25rem] flex-wrap gap-y-2">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <h1 className="max-w-[min(100%,52rem)] truncate text-base font-semibold tracking-tight text-foreground md:text-lg">
                  {displayTicket.title}
                </h1>
                <span className="shrink-0 rounded border border-border bg-muted/40 px-2 py-0.5 font-mono text-[10px] text-primary">
                  {displayTicket.id}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5"><Clock className="h-3.5 w-3.5 shrink-0" /> 持续运行: <span className="font-mono text-foreground/90">{displayTicket.runTime}</span></span>
                <span className="flex items-center gap-1.5">
                  <Coins className="h-3.5 w-3.5 shrink-0 text-amber-500/80" /> 消耗 Token:{' '}
                  <span className="font-mono text-foreground/90">
                    {meetingSummaryLoading
                      ? '…'
                      : (meetingSummary?.summary_metrics?.tokens ?? displayTicket.tokens).toLocaleString()}
                  </span>
                </span>
                {meetingSummaryErr && (
                  <span className="text-[10px] text-destructive/80" title={meetingSummaryErr}>
                    {t('rdManageOrder.meetingMetricsUnavailable', { defaultValue: '会议室指标暂不可用' })}
                  </span>
                )}
              </div>
            </div>
            
            <motion.div className="flex shrink-0 flex-wrap items-center gap-2">
              {displayTicket.status === 'full_manual' && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-1.5 text-xs font-medium text-violet-700 shadow-sm dark:text-violet-200"
                >
                  <User className="h-4 w-4 shrink-0" />
                  {t('rdManageOrder.badgeFullManual')}
                </motion.div>
              )}
              {displayTicket.sopAwaitingHuman && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive shadow-sm"
                >
                  <ShieldAlert className="h-4 w-4 shrink-0" />
                  {t('rdManageOrder.badgeHitl')}
                </motion.div>
              )}
            </motion.div>
          </div>

          <div 
            ref={containerRef}
            className="relative min-h-0 flex-1 overflow-hidden bg-muted/10 cursor-grab active:cursor-grabbing"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            
            {displayTicket.status === 'prepare' ? (
              <div className="flex h-full items-center justify-center p-8">
                <div className="max-w-md rounded-xl border border-blue-500/25 bg-blue-500/5 p-6 text-center shadow-sm">
                  <Info className="mx-auto mb-4 h-12 w-12 text-blue-500/90" />
                  <h3 className="mb-2 text-lg font-medium text-foreground">预备中</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    请先将工单手动处理至需求设计阶段，才能开始智能研发助手自动化处理。
                  </p>
                </div>
              </div>
            ) : displayTicket.status === 'full_manual' ? (
              <div className="flex h-full items-center justify-center p-8">
                <div className="max-w-md rounded-xl border border-violet-500/25 bg-violet-500/5 p-6 text-center shadow-sm">
                  <User className="mx-auto mb-4 h-12 w-12 text-violet-600 dark:text-violet-400" />
                  <h3 className="mb-2 text-lg font-medium text-foreground">{t('rdManageOrder.panelFullManualTitle')}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">{t('rdManageOrder.panelFullManualBody')}</p>
                </div>
              </div>
            ) : (
            <div 
              ref={canvasRef}
              className="absolute flex h-full min-h-0 min-w-max items-center px-16 origin-left"
              style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})` }}
            >
              {/* Background Central Data Bus Line */}
              <div className="absolute left-0 right-0 top-1/2 z-0 mx-16 h-1.5 -translate-y-1/2 rounded-full bg-border shadow-inner" />
              
              {/* Active Central Data Bus Line */}
              <motion.div 
                className="absolute left-16 top-1/2 z-0 h-1.5 -translate-y-1/2 rounded-full bg-primary shadow-[0_0_15px_color-mix(in_srgb,var(--primary)_55%,transparent)]"
                initial={{ width: 0 }}
                animate={{ width: activeLineWidth }}
                transition={{ duration: 0.8, ease: "easeOut" }}
              />

              {SOP_STAGES.map((stage, sIdx) => {
                const isStagePast = displayTicket.currentStage > stage.id;
                const isStageActive = displayTicket.currentStage === stage.id;
                const isStageFuture = displayTicket.currentStage < stage.id;
                const isCollapsed = collapsedStages[stage.id];

                if (isCollapsed) {
                  return (
                    <div key={stage.id} className="relative z-20 flex h-full min-h-0 border-l border-dashed border-border/60 px-6">
                      {/* 折叠合并标签抬到「画布顶 ↔ 中央进度线」的中段，避免与蓝色进度条重叠 */}
                      <motion.div 
                        whileHover={{ scale: 1.05 }}
                        onClick={() => setCollapsedStages(prev => ({ ...prev, [stage.id]: false }))}
                        className="stage-collapse-btn absolute left-1/2 top-[25%] z-20 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-3 rounded-full border border-green-500/30 bg-green-500/10 px-2 py-6 shadow-sm transition-colors hover:bg-green-500/20 cursor-pointer"
                      >
                        <CheckCircle2 className="w-5 h-5 text-green-500" />
                        <div className="text-xs text-green-600 dark:text-green-400 font-medium tracking-widest" style={{ writingMode: 'vertical-rl' }}>{stage.name}</div>
                        <div className="text-[10px] text-green-500/70 font-mono">{stage.nodes.length}</div>
                      </motion.div>
                    </div>
                  );
                }

                return (
                  <div key={stage.id} className="relative z-10 flex h-full min-h-0 border-l border-dashed border-border/60 px-6">
                    
                    {/* Stage Label on the Line — 最后一阶段不折叠 */}
                    <div 
                      className={`stage-collapse-btn absolute left-0 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center transition-transform ${
                        stage.id === LAST_PIPELINE_STAGE_ID
                          ? 'cursor-default'
                          : 'cursor-pointer hover:scale-110'
                      }`}
                      onClick={
                        stage.id === LAST_PIPELINE_STAGE_ID
                          ? undefined
                          : () => setCollapsedStages(prev => ({ ...prev, [stage.id]: true }))
                      }
                      title={stage.id === LAST_PIPELINE_STAGE_ID ? undefined : '点击折叠该阶段'}
                    >
                       <div className={`z-10 flex h-8 w-8 items-center justify-center rounded-full border-[3px] bg-background text-xs font-bold ${
                         isStagePast || displayTicket.status === 'completed' ? 'border-green-500 text-green-500 shadow-[0_0_10px_color-mix(in_srgb,var(--success)_30%,transparent)]' :
                         isStageActive && displayTicket.status !== 'prepare' ? 'border-primary text-primary shadow-[0_0_14px_color-mix(in_srgb,var(--primary)_30%,transparent)]' :
                         'border-muted text-muted-foreground'
                       }`}>
                         {isStagePast || displayTicket.status === 'completed' ? <CheckCircle2 className="h-5 w-5" /> : stage.id}
                       </div>
                       <div className={`absolute top-10 whitespace-nowrap text-xs font-medium tracking-widest ${isStageActive && displayTicket.status !== 'prepare' ? 'text-primary' : isStagePast || displayTicket.status === 'completed' ? 'text-muted-foreground' : 'text-muted-foreground/50'}`}>
                         {stage.name}
                       </div>
                    </div>

                    {/* Nodes Array */}
                    <div className="ml-16 flex h-full min-h-0 items-center">
                      {stage.nodes.map((node, nIdx) => {
                        const globalIndex = ALL_NODES.findIndex(n => n.id === node.id);
                        const isTop = globalIndex % 2 === 0;
                        const state = getNodeStateGlobal(displayTicket, node.id);
                        
                        const isHuman = node.type.includes('human') || node.type === 'ai_exception';
                        const nextNode = stage.nodes[nIdx + 1];
                        const isNextHuman = nextNode && (nextNode.type.includes('human') || nextNode.type === 'ai_exception');
                        
                        // Group AI nodes highly compressed (-mr-12 for horizontal overlapping), separate human intervention/wait nodes heavily (mr-32)
                        const marginClass = nIdx === stage.nodes.length - 1 ? 'mr-16' : (isHuman || isNextHuman ? 'mr-32' : '-mr-12');
                        
                        const nodeHash = node.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                        const liveMetrics = meetingNodeMetricsById.get(node.id);
                        const useLiveMetrics =
                          liveMetrics != null &&
                          (state === 'completed' || state === 'processing') &&
                          (liveMetrics.deal_seconds > 0 || liveMetrics.tokens > 0);
                        const timeStr = useLiveMetrics
                          ? formatDurationSeconds(liveMetrics.deal_seconds, t)
                          : isHuman
                            ? `${(nodeHash % 4) + 1}h ${nodeHash % 60}m`
                            : `${((nodeHash % 50) / 10 + 0.5).toFixed(1)}s`;
                        const modelStr = isHuman ? '人工处理' : ['Claude-3.5', 'GPT-4o', 'Gemini-1.5'][nodeHash % 3];
                        const tokenStr =
                          useLiveMetrics && !isHuman
                            ? formatTokenCount(liveMetrics.tokens)
                            : isHuman
                              ? '--'
                              : `${((nodeHash % 50 + 10) / 10).toFixed(1)}k`;
                        
                        let cardClass = "min-h-[7.5rem] border-border bg-card/60 text-muted-foreground";
                        let iconClass = "text-muted-foreground";
                        let dotClass = "bg-border border-background";
                        let lineClass = "bg-border";
                        let hoverClass = "hover:border-primary/35 hover:bg-muted/30";

                        if (state === 'completed') {
                          cardClass = "min-h-[8.5rem] border-green-500/35 bg-card/90 text-foreground";
                          iconClass = "text-green-500";
                          dotClass = "bg-green-500 border-background";
                          lineClass = "bg-green-500/50";
                          hoverClass = "hover:border-green-500/50 hover:bg-muted/25";
                        } else if (state === 'processing') {
                          cardClass = "min-h-[7.5rem] border-primary/45 bg-primary/10 text-foreground shadow-[0_0_18px_color-mix(in_srgb,var(--primary)_12%,transparent)]";
                          iconClass = "text-primary";
                          dotClass = "bg-primary border-background shadow-[0_0_10px_color-mix(in_srgb,var(--primary)_55%,transparent)]";
                          lineClass = "bg-primary/75";
                          hoverClass = "hover:border-primary hover:bg-primary/15";
                        } else if (state === 'error') {
                          cardClass = "min-h-[7.5rem] border-destructive/55 bg-destructive/10 text-destructive-foreground shadow-[0_0_16px_color-mix(in_srgb,var(--destructive)_14%,transparent)]";
                          iconClass = "text-destructive";
                          dotClass = "bg-destructive border-background shadow-[0_0_10px_color-mix(in_srgb,var(--destructive)_45%,transparent)] animate-pulse";
                          lineClass = "bg-destructive/75";
                          hoverClass = "hover:border-destructive hover:bg-destructive/15";
                        } else if (state === 'awaiting_human') {
                          cardClass = "min-h-[7.5rem] border-amber-500/55 bg-amber-500/10 text-amber-950 shadow-[0_0_16px_rgba(245,158,11,0.12)] dark:text-amber-50";
                          iconClass = "text-amber-600 dark:text-amber-400";
                          dotClass = "bg-amber-500 border-background shadow-[0_0_10px_rgba(245,158,11,0.45)] animate-pulse";
                          lineClass = "bg-amber-500/75";
                          hoverClass = "hover:border-amber-500 hover:bg-amber-500/15";
                        }

                        const renderPopoverContent = () => {
                          // Calculate duration in minutes (mock based on nodeHash)
                          const durationMinutes = isHuman ? (nodeHash % 60) + 30 : (nodeHash % 15) + 2;
                          
                          // Determine number of points (max 10, min 1 per minute)
                          const numPoints = Math.min(10, durationMinutes);
                          const interval = durationMinutes / numPoints;
                          
                          // Generate monotonically increasing token data
                          const totalTokensMock = (nodeHash % 50 + 10) * 1000;
                          const tokenData = Array.from({ length: numPoints }).map((_, i) => {
                            const timeMark = Math.round((i + 1) * interval);
                            // Use a curve that grows faster at the end to make it look realistic
                            const progress = (i + 1) / numPoints;
                            const tokensAtPoint = Math.round(totalTokensMock * Math.pow(progress, 1.5));
                            return { 
                              time: `${timeMark}m`, 
                              tokens: tokensAtPoint 
                            };
                          });
                          
                          const maxTokens = Math.max(...tokenData.map(d => d.tokens), 1);
                          const totalTokens = tokenData[tokenData.length - 1]?.tokens || 0;
                          
                          // Mock pricing
                          const pricingMap: Record<string, number> = {
                            'Claude-3.5': 0.003, // $0.003 per 1k tokens
                            'GPT-4o': 0.005,
                            'Gemini-1.5': 0.0015
                          };
                          const pricePer1k = pricingMap[modelStr] || 0.002;
                          const totalCost = (totalTokens / 1000) * pricePer1k;

                          // SVG Line Chart coordinates
                          const chartWidth = 280;
                          const chartHeight = 60;
                          const points = tokenData.map((d, i) => {
                            const x = (i / (Math.max(1, tokenData.length - 1))) * chartWidth;
                            const y = chartHeight - (d.tokens / maxTokens) * chartHeight;
                            return `${x},${y}`;
                          }).join(' ');

                          return (
                            <div className="w-80 p-2">
                              <div className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
                                <TerminalSquare className="w-3.5 h-3.5" /> 节点微览
                              </div>
                              <div className="bg-black/40 rounded p-3 text-[10px] font-mono text-green-400 h-36 overflow-y-auto custom-scrollbar relative">
                                <div>&gt; [INFO] Initializing node environment...</div>
                                <div>&gt; [INFO] Loading dependencies for {node.name}...</div>
                                <div>&gt; [INFO] Executing {node.name}...</div>
                                {state === 'completed' && (
                                  <>
                                    <div>&gt; [INFO] Processing data chunks...</div>
                                    <div>&gt; [INFO] Validating output format...</div>
                                    <div>&gt; [SUCCESS] Output generated successfully.</div>
                                    <div className="text-blue-400 mt-1">&gt; [METRICS] Time: {timeStr}, Tokens: {tokenStr}</div>
                                  </>
                                )}
                                {state === 'processing' && (
                                  <>
                                    <div>&gt; [RUNNING] Analyzing data structure...</div>
                                    <div>&gt; [RUNNING] Generating abstract syntax tree...</div>
                                    <div className="animate-pulse text-amber-400 mt-1">&gt; [RUNNING] Awaiting model response...</div>
                                  </>
                                )}
                                {state === 'error' && (
                                  <>
                                    <div>&gt; [RUNNING] Analyzing data...</div>
                                    <div className="text-red-400 mt-1">&gt; [ERROR] Execution failed at line 42.</div>
                                    <div className="text-red-400">&gt; [ERROR] Timeout waiting for model response.</div>
                                  </>
                                )}
                                {state === 'awaiting_human' && (
                                  <>
                                    <div>&gt; [RUNNING] Analyzing data...</div>
                                    <div className="text-amber-400 mt-1">&gt; [WARN] Ambiguous requirements detected.</div>
                                    <div className="text-amber-400">&gt; [WARN] Waiting for human clarification.</div>
                                  </>
                                )}
                              </div>
                              {!isHuman && (
                                <div className="mt-4">
                                  <div className="flex items-center justify-between text-[10px] mb-2">
                                    <span className="text-muted-foreground flex items-center gap-1">
                                      <TrendingUp className="w-3 h-3"/> Token 消耗总量趋势
                                    </span>
                                    <div className="flex items-center gap-3">
                                      <span className="text-amber-500 flex items-center gap-1" title="当前总消耗">
                                        <Coins className="w-3 h-3"/>
                                        {totalTokens >= 1000 ? (totalTokens/1000).toFixed(1) + 'k' : totalTokens}
                                      </span>
                                      <span className="text-emerald-500 flex items-center gap-1" title={`模型定价: $${pricePer1k}/1k tk`}>
                                        <Banknote className="w-3 h-3"/>
                                        {totalCost.toFixed(4)} 元
                                      </span>
                                    </div>
                                  </div>
                                  <div className="relative w-full h-[60px] mt-2 text-primary">
                                    <svg width="100%" height="100%" viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none">
                                      <defs>
                                        <linearGradient id="lineGradient" x1="0" y1="0" x2="0" y2="1">
                                          <stop offset="0%" stopColor="currentColor" stopOpacity="0.3" />
                                          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
                                        </linearGradient>
                                      </defs>
                                      <polygon 
                                        points={`0,${chartHeight} ${points} ${chartWidth},${chartHeight}`} 
                                        fill="url(#lineGradient)" 
                                      />
                                      <polyline 
                                        points={points} 
                                        fill="none" 
                                        stroke="currentColor" 
                                        strokeWidth="2" 
                                        strokeLinecap="round" 
                                        strokeLinejoin="round" 
                                      />
                                      {tokenData.map((d, i) => {
                                        const x = (i / (Math.max(1, tokenData.length - 1))) * chartWidth;
                                        const y = chartHeight - (d.tokens / maxTokens) * chartHeight;
                                        return (
                                          <circle key={i} cx={x} cy={y} r="3" fill="#0f172a" stroke="currentColor" strokeWidth="1.5" />
                                        );
                                      })}
                                    </svg>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        };

                        return (
                          <div id={`node-${node.id}`} key={node.id} className={`relative flex h-full min-h-0 w-56 flex-col items-center justify-center self-stretch ${marginClass}`}>
                            {/* Stem connecting card to central bus */}
                            <div className={`absolute left-1/2 w-0.5 -translate-x-1/2 ${lineClass} z-0 ${
                              isTop ? 'bottom-[calc(50%+3px)] h-[37px]' : 'top-[calc(50%+3px)] h-[37px]'
                            }`} />

                            {/* Node Point on Data Bus */}
                            <div className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border-[3px] z-10 ${dotClass}`} />

                            {/* Node Card */}
                            <Popover 
                              content={renderPopoverContent()} 
                              placement={isTop ? "top" : "bottom"} 
                              mouseEnterDelay={0.6}
                              overlayInnerStyle={{ 
                                background: 'rgba(15, 23, 42, 0.75)', 
                                backdropFilter: 'blur(16px)', 
                                border: '1px solid rgba(255,255,255,0.1)',
                                boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                                borderRadius: '12px'
                              }}
                            >
                              <motion.div
                                whileHover={{ scale: 1.05, y: isTop ? -5 : 5 }}
                                onClick={() => handleNodeClick(node)}
                                className={`node-card absolute left-0 z-20 flex w-full cursor-pointer flex-col rounded-xl border p-4 backdrop-blur-sm transition-all duration-300 ${cardClass} ${hoverClass} ${isTop ? 'bottom-[calc(50%+40px)]' : 'top-[calc(50%+40px)]'}`}
                              >
                                <div className="mb-2 flex items-start justify-between">
                                  <div className="rounded-lg bg-muted/40 p-1.5">
                                    {state === 'completed' ? <CheckCircle2 className={`w-4 h-4 ${iconClass}`} /> :
                                     state === 'processing' ? <Loader2 className={`w-4 h-4 ${iconClass} animate-spin`} /> :
                                     state === 'error' ? <AlertCircle className={`w-4 h-4 ${iconClass} animate-pulse`} /> :
                                     state === 'awaiting_human' ? <AlertTriangle className={`w-4 h-4 ${iconClass} animate-pulse`} /> :
                                     <CircleDashed className={`w-4 h-4 ${iconClass}`} />}
                                  </div>
                                  <div className="rounded-full border border-border bg-muted/50 px-2 py-0.5 font-mono text-[10px]">
                                    {isHuman ? (
                                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400"><User className="h-3 w-3" /> 人工</span>
                                    ) : node.type.includes('ai') ? (
                                      <span className="flex items-center gap-1 text-primary"><Bot className="h-3 w-3" /> AI</span>
                                    ) : (
                                      <span className="flex items-center gap-1 text-muted-foreground"><TerminalSquare className="h-3 w-3" /> 系统</span>
                                    )}
                                  </div>
                                </div>
                                <h4 className="mb-1 text-sm font-medium">{node.name}</h4>
                                <p className="line-clamp-2 flex-1 text-[10px] leading-relaxed opacity-80">{node.desc}</p>
                                
                                {state === 'completed' && (
                                  <div className="mt-2 flex w-full items-center justify-between gap-2 border-t border-border/60 pt-2 font-mono text-[10px] text-muted-foreground">
                                    {!isHuman && (
                                      <div className="flex items-center gap-1 opacity-80" title="执行模型">
                                        <Cpu className="h-3 w-3 text-primary/70" />
                                        <span>{modelStr}</span>
                                      </div>
                                    )}
                                    <div className="ml-auto flex items-center gap-1 opacity-80" title="节点耗时">
                                      <Clock className="h-3 w-3 text-muted-foreground" />
                                      <span>{timeStr}</span>
                                    </div>
                                    {!isHuman && (
                                      <div className="flex items-center gap-1 opacity-80" title="Token消耗">
                                        <Coins className="h-3 w-3 text-amber-500/80" />
                                        <span>{tokenStr}</span>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </motion.div>
                            </Popover>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
            )}
          </div>
        </div>
      </div>

      {/* Node Details Drawer */}
      <Drawer
        title={
          <div className="flex items-center gap-3 text-foreground">
            {selectedNode?.type.includes('ai') ? (
               <div className="rounded-lg bg-primary/15 p-1.5"><Bot className="h-5 w-5 text-primary" /></div>
            ) : (
               <div className="rounded-lg bg-amber-500/15 p-1.5"><User className="h-5 w-5 text-amber-600 dark:text-amber-400" /></div>
            )}
            <span className="text-base font-semibold">{selectedNode?.name}</span>
          </div>
        }
        placement="right"
        onClose={() => setDrawerOpen(false)}
        open={drawerOpen}
        width={500}
        styles={{
          header: { background: 'var(--panel2)', borderBottom: '1px solid var(--line)', padding: '16px 24px' },
          body: { background: 'var(--bg-app)', padding: '24px' },
          mask: { backdropFilter: 'blur(3px)', background: 'rgba(0,0,0,0.45)' }
        }}
        closeIcon={<span className="text-muted-foreground transition-colors hover:text-foreground">✕</span>}
      >
        {selectedNode && (
          <div className="flex h-full flex-col">
            <div className="mb-6 rounded-xl border border-border bg-muted/30 p-4 shadow-inner">
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">节点说明</h4>
              <p className="text-sm leading-relaxed text-foreground/90">
                {selectedNode.desc}
              </p>
            </div>

            <div className="min-h-0 flex-1">
              <h4 className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">执行产物 / 交互区</h4>
              {renderNodeOutput(selectedNode, displayTicket)}
            </div>
          </div>
        )}
      </Drawer>

      {/* Ticket Details Modal */}
      <Modal
        closable={false}
        title={
          modalDemand ? (
            <div className="flex min-w-0 items-center gap-3 border-b border-border pb-3 text-foreground">
              <div className="flex min-w-0 flex-1 items-center gap-2 text-base font-semibold leading-snug">
                <FileText className="h-5 w-5 shrink-0 text-primary" />
                <span className="line-clamp-1" title={modalDemand.demand_title}>
                  {modalDemand.demand_title}
                </span>
              </div>
              <Tag color="blue" bordered={false} className="m-0 shrink-0 font-mono text-xs">
                #{modalDemand.demand_no}
              </Tag>
            </div>
          ) : (
            <div className="flex items-center gap-2 border-b border-border pb-3 text-foreground">
              <FileText className="h-5 w-5 text-primary" />
              <span className="text-lg">—</span>
            </div>
          )
        }
        open={ticketModalOpen}
        onCancel={() => {
          setTicketModalOpen(false);
          setSelectedTicketForModal(null);
          setSelectedWorkItemIdForModal(null);
          setModalDemand(null);
          setDbMetrics(null);
          setDbMetricsErr(null);
        }}
        footer={null}
        width={720}
        styles={{
          root: { background: 'var(--panel2)', border: '1px solid var(--line)', color: 'var(--text)' },
          body: { paddingTop: 0, paddingBottom: 16, maxHeight: 'min(85vh, 860px)', overflowY: 'auto' },
          header: { background: 'transparent' },
          mask: { backdropFilter: 'blur(4px)' },
        }}
      >
        {selectedTicketForModal && modalDemand && (
          <Tabs
            key={`ticket-modal-${modalDemand.demand_no}-${ticketModalWorkItemsResolved.singleTaskMode ? ticketModalWorkItemsResolved.workItemIdTrim : 'all'}`}
            defaultActiveKey={ticketModalWorkItemsResolved.singleTaskMode ? 'tasks' : 'overview'}
            items={[
              {
                key: 'overview',
                label: t('rdManageOrder.tabOverview'),
                children: (
                  <div className="space-y-5 pt-2">
                    {showTicketModalPipelineLayers && (
                      <section>
                        <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          <Activity className="h-4 w-4 text-primary" />
                          {t('rdManageOrder.sectionSummary')}
                        </h3>
                        {dbMetricsLoading ? (
                          <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            {t('rdManageOrder.loadingMetrics')}
                          </div>
                        ) : (
                          <div className="grid grid-cols-3 gap-3">
                            <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
                              <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
                                {t('rdManageOrder.processDuration')}
                              </div>
                              <div className="relative z-10 mt-1 font-mono text-2xl font-bold text-foreground">
                                {formatDurationSeconds(modalSummaryMetrics?.process_seconds ?? 0, t)}
                              </div>
                              <Clock className="absolute -bottom-2 -right-2 h-16 w-16 text-primary/5" />
                            </div>
                            <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
                              <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
                                {t('rdManageOrder.totalTokens')}
                              </div>
                              <div className="relative z-10 mt-1 font-mono text-2xl font-bold text-foreground">
                                {(modalSummaryMetrics?.total_tokens ?? 0).toLocaleString()}
                              </div>
                              <Coins className="absolute -bottom-2 -right-2 h-16 w-16 text-primary/5" />
                            </div>
                            <div className="relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
                              <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
                                {t('rdManageOrder.humanInterventions')}
                              </div>
                              <div className="relative z-10 mt-1 font-mono text-2xl font-bold text-foreground">
                                {modalSummaryMetrics?.human_interventions ?? 0}
                              </div>
                              <User className="absolute -bottom-2 -right-2 h-16 w-16 text-primary/5" />
                            </div>
                            <div className="col-span-3 relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br from-background/60 to-muted/20 p-4">
                              <div className="relative z-10 text-[10px] font-medium uppercase text-muted-foreground">
                                {t('rdManageOrder.artifacts')}
                              </div>
                              <div className="relative z-10 mt-2 flex flex-wrap gap-1.5">
                                {(modalSummaryMetrics?.artifacts?.length ?? 0) === 0 ? (
                                  <span className="text-xs text-muted-foreground">{t('rdManageOrder.noArtifacts')}</span>
                                ) : (
                                  (modalSummaryMetrics?.artifacts ?? []).map((a, i) => (
                                    <Tag color="purple" bordered={false} key={`${a}-${i}`} className="m-0 max-w-full truncate text-xs">
                                      {a}
                                    </Tag>
                                  ))
                                )}
                              </div>
                              <FileCode2 className="absolute -bottom-4 -right-2 h-20 w-20 text-primary/5" />
                            </div>
                          </div>
                        )}
                        {dbMetricsErr && !dbMetricsLoading ? (
                          <p className="mt-2 text-xs text-destructive/90">{dbMetricsErr}</p>
                        ) : null}
                      </section>
                    )}

                    <section>
                      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        <ClipboardList className="h-4 w-4 text-primary" />
                        {t('rdManageOrder.sectionDemand')}
                      </h3>
                      <div className="mb-4 grid grid-cols-1 gap-x-4 gap-y-3 rounded-xl border border-border/50 bg-muted/10 p-4 sm:grid-cols-2">
                        <div className="flex items-center justify-between text-sm sm:block">
                          <span className="text-xs text-muted-foreground">
                            {t('rdManageOrder.labelColon', { label: t('rdManageOrder.demandCreateTime') })}
                          </span>
                          <span className="font-mono text-foreground/90">{modalDemand.demand_create_time || '—'}</span>
                        </div>
                        <div className="flex items-center justify-between text-sm sm:block">
                          <span className="text-xs text-muted-foreground">
                            {t('rdManageOrder.labelColon', { label: t('rdManageOrder.demandStatus') })}
                          </span>
                          <Badge 
                            status={modalDemand.demand_status?.includes('完成') || modalDemand.demand_status?.includes('Done') ? 'success' : 'processing'} 
                            text={
                              <span className="font-medium text-foreground/90">{(modalDemand.demand_status || '—').trim() || '—'}</span>
                            } 
                          />
                        </div>
                        <div className="flex items-center justify-between text-sm sm:block">
                          <span className="text-xs text-muted-foreground">
                            {t('rdManageOrder.labelColon', { label: t('rdManageOrder.demandImpact') })}
                          </span>
                          <span className="whitespace-pre-line text-foreground/90">
                            {formatDemandImpactDisplay(modalDemand.demand_impact || '') || '—'}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-sm sm:block">
                          <span className="text-xs text-muted-foreground">
                            {t('rdManageOrder.labelColon', { label: t('rdManageOrder.productVersion') })}
                          </span>
                          <Tag bordered={false} className="m-0 font-mono">
                            {(modalDemand.product_version_code || '—').trim() || '—'}
                          </Tag>
                        </div>
                        <div className="flex items-center justify-between text-sm sm:block">
                          <span className="text-xs text-muted-foreground">
                            {t('rdManageOrder.labelColon', { label: t('rdManageOrder.demandDealTime') })}
                          </span>
                          <span className="font-mono text-foreground/90">
                            {dbMetricsLoading && !modalDemandMetrics
                              ? '…'
                              : formatDurationSeconds(modalDemandMetrics?.deal_seconds ?? 0, t)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-sm sm:block">
                          <span className="text-xs text-muted-foreground">
                            {t('rdManageOrder.labelColon', { label: t('rdManageOrder.demandDealToken') })}
                          </span>
                          <span className="font-mono text-foreground/90">
                            {dbMetricsLoading && !modalDemandMetrics
                              ? '…'
                              : (modalDemandMetrics?.deal_tokens ?? 0).toLocaleString()}
                          </span>
                        </div>
                      </div>
                      
                      <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">
                        {t('rdManageOrder.demandDesc')}
                      </div>
                      <div className="rounded-lg border border-border/60 bg-background/50 p-4 text-sm">
                        {(modalDemand.demand_desc || '').trim() ? (
                          <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/90 prose-pre:border prose-pre:border-border/50 prose-pre:bg-muted/30 prose-a:text-primary">
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                a: ({ ...props }) => (
                                  <a {...props} className="underline" target="_blank" rel="noopener noreferrer" />
                                ),
                              }}
                            >
                              {modalDemand.demand_desc || ''}
                            </ReactMarkdown>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">{t('rdManageOrder.markdownEmpty')}</span>
                        )}
                      </div>
                    </section>
                    
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-4 text-xs text-muted-foreground">
                      <div className="flex items-center gap-1.5">
                        <span>{t('rdManageOrder.labelColon', { label: t('rdManageOrder.designer') })}</span>
                        <Avatar size={18} className="bg-primary/20 text-xs font-semibold text-primary">
                          {(modalDemand.demand_designer || selectedTicketForModal.owner || '?').charAt(0)}
                        </Avatar>
                        <span className="font-medium text-foreground/80">
                          {(modalDemand.demand_designer || selectedTicketForModal.owner || '—').trim()}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              },
              ...(showTicketModalPipelineLayers && ticketModalWorkItemsResolved.displayWorkItems.length > 0
                ? [
                    {
                      key: 'tasks',
                      label: ticketModalWorkItemsResolved.singleTaskMode
                        ? t('rdManageOrder.sectionTaskDetails')
                        : t('rdManageOrder.tabTasksWithCount', {
                            count: ticketModalWorkItemsResolved.displayWorkItems.length,
                          }),
                      children: (
                        <div className="space-y-4 pt-2">
                          {ticketModalWorkItemsResolved.singleTaskMode ? (
                            ticketModalWorkItemsResolved.displayWorkItems.map((wi) => {
                              const tm = dbMetrics?.task_metrics?.[wi.task_no];
                              return (
                                <div key={wi.task_no} className="rounded-xl border border-border/60 bg-muted/10 p-5">
                                  <div className="mb-5 flex min-w-0 items-center gap-2 border-b border-border/50 pb-4">
                                    <Tag color="processing" bordered={false} className="m-0 shrink-0 font-mono text-xs">
                                      {wi.task_no}
                                    </Tag>
                                    <h4
                                      className="min-w-0 flex-1 text-base font-medium leading-snug text-foreground line-clamp-2"
                                      title={wi.task_title}
                                    >
                                      {wi.task_title}
                                    </h4>
                                  </div>
                                  <TaskModalWorkItemStats
                                    wi={wi}
                                    tm={tm}
                                    dbMetricsLoading={dbMetricsLoading}
                                    t={t}
                                    onOpenProductModule={() => void openProductDetailForWorkItem(wi)}
                                  />
                                  <div className="mt-6 rounded-lg border border-border/50 bg-background/40 p-4 text-sm">
                                    <div className="mb-3 border-b border-border/40 pb-2 text-[10px] font-semibold uppercase text-muted-foreground">
                                      {t('rdManageOrder.taskDescription')}
                                    </div>
                                    {(wi.task_desc || '').trim() ? (
                                      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/85 prose-pre:border prose-pre:border-border/50 prose-pre:bg-muted/30 prose-a:text-primary">
                                        <ReactMarkdown
                                          remarkPlugins={[remarkGfm]}
                                          components={{
                                            a: ({ ...props }) => (
                                              <a {...props} className="underline" target="_blank" rel="noopener noreferrer" />
                                            ),
                                          }}
                                        >
                                          {wi.task_desc}
                                        </ReactMarkdown>
                                      </div>
                                    ) : (
                                      <span className="text-muted-foreground">{t('rdManageOrder.markdownEmpty')}</span>
                                    )}
                                  </div>
                                </div>
                              );
                            })
                          ) : (
                            <Collapse
                              className="bg-transparent"
                              bordered={false}
                              expandIconPosition="end"
                              items={ticketModalWorkItemsResolved.displayWorkItems.map((wi) => {
                                const tm = dbMetrics?.task_metrics?.[wi.task_no];
                                return {
                                  key: wi.task_no,
                                  style: {
                                    marginBottom: 12,
                                    background: 'var(--panel2)',
                                    borderRadius: 8,
                                    border: '1px solid var(--line)',
                                    overflow: 'hidden',
                                  },
                                  label: (
                                    <div className="flex flex-col gap-1.5 pr-2">
                                      <div className="flex min-w-0 items-center gap-2">
                                        <Tag color="processing" bordered={false} className="m-0 shrink-0 font-mono text-[10px]">
                                          {wi.task_no}
                                        </Tag>
                                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground" title={wi.task_title}>
                                          {wi.task_title}
                                        </span>
                                      </div>
                                      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                                        <Badge
                                          status={
                                            wi.stage_name?.includes('完成') || wi.stage_name?.includes('走查')
                                              ? 'success'
                                              : 'processing'
                                          }
                                          text={
                                            <span className="text-muted-foreground">
                                              {(wi.stage_name || '—').trim() || '—'}
                                            </span>
                                          }
                                        />
                                        <div className="flex items-center gap-1">
                                          <Clock className="h-3 w-3" />
                                          <span>
                                            {dbMetricsLoading && !tm
                                              ? '…'
                                              : formatDurationSeconds(tm?.deal_seconds ?? 0, t)}
                                          </span>
                                        </div>
                                      </div>
                                    </div>
                                  ),
                                  children: (
                                    <div className="border-t border-border/50 pt-4">
                                      <TaskModalWorkItemStats
                                        wi={wi}
                                        tm={tm}
                                        dbMetricsLoading={dbMetricsLoading}
                                        t={t}
                                        onOpenProductModule={() => void openProductDetailForWorkItem(wi)}
                                      />
                                      <div className="mt-6 rounded-lg border border-border/50 bg-muted/10 p-3 text-xs">
                                        <div className="mb-3 border-b border-border/40 pb-2 text-[10px] font-semibold uppercase text-muted-foreground">
                                          {t('rdManageOrder.taskDescription')}
                                        </div>
                                        {(wi.task_desc || '').trim() ? (
                                          <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/85 prose-pre:border prose-pre:border-border/50 prose-pre:bg-muted/30 prose-a:text-primary">
                                            <ReactMarkdown
                                              remarkPlugins={[remarkGfm]}
                                              components={{
                                                a: ({ ...props }) => (
                                                  <a
                                                    {...props}
                                                    className="underline"
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                  />
                                                ),
                                              }}
                                            >
                                              {wi.task_desc}
                                            </ReactMarkdown>
                                          </div>
                                        ) : (
                                          <span className="text-muted-foreground">{t('rdManageOrder.markdownEmpty')}</span>
                                        )}
                                      </div>
                                    </div>
                                  ),
                                };
                              })}
                            />
                          )}
                        </div>
                      ),
                    },
                  ]
                : [])
            ]}
          />
        )}
      </Modal>

      <ProductDetail
        product={detailProduct}
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setDetailProduct(null);
        }}
        synapseApiBase={synapseApiBase}
        onProcessPayload={mergeProcessIntoProduct}
        onPatchProductKnowledge={patchProductKnowledge}
      />

    </ConfigProvider>
  );
};
