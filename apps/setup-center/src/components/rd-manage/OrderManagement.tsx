import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { ConfigProvider, theme, Badge, Avatar, Button, Drawer, Modal, Tag, Progress, Tabs, Popover, Tooltip } from 'antd';
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
  Flame,
  TrendingUp,
  Loader2,
  AlertCircle,
  Search,
  Banknote
} from 'lucide-react';
import { fetchRdManageDemands, type DemandListItem } from '../../api/rdManageService';
import { ViewId } from '../../types';

// --- Types & Data ---

type NodeType = 'ai' | 'human' | 'human_start' | 'ai_exception' | 'ai_human' | 'system' | 'human_multi';

interface SOPNode {
  id: string;
  name: string;
  type: NodeType;
  desc: string;
  stageId?: number;
}

interface SOPStage {
  id: number;
  name: string;
  nodes: SOPNode[];
}

export interface WorkItem {
  id: string;
  title: string;
  createdAt: string;
  tokens: number;
  branch: string;
  description: string;
  /** 该研发单对应的流水线当前节点 id（由接口 task sop_node 解析） */
  currentNode: string;
}

export interface Ticket {
  id: string;
  branch: string;
  title: string;
  currentStage: number;
  currentNode: string;
  status: 'processing' | 'human_intervention' | 'pending' | 'completed' | 'error' | 'prepare';
  owner: string;
  urgency: 'low' | 'medium' | 'high';
  tokens: number;
  runTime: string;
  description: string;
  createdAt: string;
  workItems: WorkItem[];
}

const SOP_STAGES: SOPStage[] = [
  {
    id: 0,
    name: '待处理',
    nodes: [
      { id: 'pending', name: '等待调度', type: 'system', desc: '工单刚创建，等待进入智能研发流程' }
    ]
  },
  {
    id: 1,
    name: '需求分析',
    nodes: [
      { id: 'req_clarify', name: '需求澄清', type: 'human', desc: '识别需求模糊点和歧义，自动交互式推进完善' },
      { id: 'boundary', name: '边界确认', type: 'ai', desc: '识别跨产品场景，确保单个需求只处理一个产品' },
      { id: 'module_func', name: '模块功能', type: 'ai', desc: '对需求进行功能模块拆分，为设计做准备' },
      { id: 'acceptance', name: '验收标准', type: 'ai', desc: '针对拆分出的功能模块完成验收要求设定' },
      { id: 'req_risk', name: '需求风险', type: 'human', desc: '高风险需求需人工介入，评估影响和工作量' }
    ]
  },
  {
    id: 2,
    name: '需求设计',
    nodes: [
      { id: 'func_assign', name: '功能点分派', type: 'ai', desc: '按需求拆分功能点，分派给不同智能体并行处理' },
      { id: 'history_solution', name: '历史方案', type: 'ai', desc: '检索历史方案，与当前要求进行映射供参考' },
      { id: 'module_confirm', name: '模块确认', type: 'ai', desc: '确认具体改造的代码模块范围' },
      { id: 'func_solution', name: '函数级方案', type: 'ai', desc: '将功能方案定位到函数级别，严控改造范围' },
      { id: 'entropy_gen', name: '控熵生成', type: 'ai', desc: '提取并生成 agent.md, rule.md 等控熵文件' },
      { id: 'solution_review', name: '方案评审', type: 'ai_human', desc: '发起评审，设计助手答辩，可调用沙箱验证可行性' }
    ]
  },
  {
    id: 3,
    name: '需求研发',
    nodes: [
      { id: 'auto_split', name: '自动拆单', type: 'ai', desc: '根据需求单和方案完成研发子单自动拆分分配' },
      { id: 'sandbox_build', name: '沙箱构建', type: 'ai', desc: '针对研发单构造无冗余信息的基础沙箱环境' },
      { id: 'env_pregen', name: '环境预生成', type: 'ai', desc: '下载代码、控熵文件，完成开发环境预生成' }
    ]
  },
  {
    id: 4,
    name: '开发中',
    nodes: [
      { id: 'task_exec', name: '任务执行', type: 'human_start', desc: '人工确认启动，研发助手关联沙箱执行（禁改Prompt）' },
      { id: 'exception_check', name: '异常检查', type: 'ai', desc: '发现无法解决的问题时，降级为人工介入处理' },
      { id: 'task_feedback', name: '任务反馈', type: 'system', desc: '实时反馈执行情况，供人工观察智能体状态' },
      { id: 'diff_analysis', name: '差异分析', type: 'human', desc: '强制要求研发人员对完成的代码进行差异分析' },
      { id: 'env_start', name: '环境启动', type: 'system', desc: '自动进行环境启动并编译运行代码（或远端编译）' },
      { id: 'unit_test', name: '单元自测', type: 'ai', desc: '根据验收标准生成测试用例，自测通过后自动提交试飞' }
    ]
  },
  {
    id: 5,
    name: '代码走查',
    nodes: [
      { id: 'dev_process_review', name: '开发流程评审', type: 'ai', desc: '检查开发耗时、token消耗、冲突情况等是否合规' },
      { id: 'solution_consistency', name: '方案一致性', type: 'ai', desc: '二次核对涉及的文件/模块/功能是否严遵方案' },
      { id: 'risk_review', name: '风险评审', type: 'ai', desc: '综合评定开发中的情况及测试充分率是否存在风险' },
      { id: 'entropy_review', name: '控熵评审', type: 'ai', desc: '双向校验控熵文件内容与代码改造差异点的各类结构' },
      { id: 'leader_review', name: '研发组长评审', type: 'human_multi', desc: '全员线上评审通过后，方可继续转单发布' }
    ]
  }
];

// Flatten nodes for easy index calculation
const ALL_NODES = SOP_STAGES.flatMap(s => s.nodes.map(n => ({ ...n, stageId: s.id })));

/** 流水线最后一阶段（代码走查）：不参与折叠合并 */
const LAST_PIPELINE_STAGE_ID = SOP_STAGES[SOP_STAGES.length - 1]?.id ?? 5;
/** 工单已全部完成时，焦点落在最后一个 SOP 节点（研发组长评审） */
const LAST_PIPELINE_NODE_ID = ALL_NODES[ALL_NODES.length - 1]?.id ?? 'leader_review';

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

type NodeState = 'completed' | 'processing' | 'error' | 'human_intervention' | 'pending';

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

/** 将接口 sop_node 文案或 id 解析为流水线节点 id；空串无法解析时返回 null */
function resolveSopRawToNodeId(sopRaw: string): string | null {
  const sop = (sopRaw || "").trim();
  if (!sop) return null;
  return ALL_NODES.find((n) => n.name === sop || n.id === sop)?.id ?? null;
}

function stageIdForNodeId(nodeId: string): number {
  const stage = SOP_STAGES.find((s) => s.nodes.some((n) => n.id === nodeId));
  return stage ? stage.id : 0;
}

/** 接口可能省略 local_process_state，用需求状态兜底「待处理」 */
function effectiveLocalProcessState(d: DemandListItem): string {
  const s = (d.local_process_state || "").trim();
  if (s) return s;
  if ((d.demand_status || "").trim() === "待处理") return "待处理";
  return "";
}

function mapDemandListItemToTicket(d: DemandListItem): Ticket {
  const local = effectiveLocalProcessState(d);
  let status: Ticket["status"] = "pending";
  if (local === "预备中") status = "prepare";
  else if (local === "待处理") status = "pending";
  else if (local === "处理中") status = "processing";
  else if (local === "全人工") status = "human_intervention";
  else if (local === "已完成" || d.demand_status === "已完成" || d.demand_status === "completed")
    status = "completed";
  else if (["需求开发", "开发中", "测试中"].some((x) => (d.demand_status || "").includes(x)))
    status = "processing";
  else status = "pending";

  let demandNodeId = "pending";
  if (status === "completed") {
    demandNodeId = LAST_PIPELINE_NODE_ID;
  } else if (local === "待处理") {
    // 契约：待处理时需求单一定在「等待调度」，与接口 sop_node 文案无关
    demandNodeId = "pending";
  } else if (local === "预备中" || local === "全人工") {
    // 契约：预备中/全人工时 sop_node 必为空，不解析接口 sop
    demandNodeId = "pending";
  } else if (status === "processing") {
    const sop = (d.sop_node || "").trim();
    demandNodeId = resolveSopRawToNodeId(sop) ?? "pending";
  }

  const runTime =
    (d.demand_deal_time || "").trim() ||
    (d.demand_finish_time || "").trim() ||
    "0h";

  const items = d.owned_work_items || [];
  const workItems: WorkItem[] = items.map((w) => {
    const taskResolved = resolveSopRawToNodeId((w.sop_node || "").trim());
    const currentNode = taskResolved ?? demandNodeId;
    return {
      id: w.task_no,
      title: w.task_title,
      createdAt: w.created_date || new Date().toISOString(),
      tokens: w.sccb_work_hours != null ? Math.round(Number(w.sccb_work_hours) * 60) : 0,
      branch: w.product_module_name || "master",
      description: w.task_desc || "",
      currentNode,
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
    owner: d.demand_designer || "未知",
    branch: d.product_version_code || "master",
    urgency: "medium",
    currentNode: demandNodeId,
    currentStage: 0,
    workItems,
  };
}

// --- Main Components ---

export const OrderManagement: React.FC<{
  synapseApiBase?: string;
  onViewChange?: (view: ViewId) => void;
}> = ({ synapseApiBase = "http://127.0.0.1:18900", onViewChange }) => {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [activeTicketId, setActiveTicketId] = useState<string>('');
  const [activeWorkItemId, setActiveWorkItemId] = useState<string>('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<SOPNode | null>(null);
  const [ticketModalOpen, setTicketModalOpen] = useState(false);
  const [selectedTicketForModal, setSelectedTicketForModal] = useState<Ticket | null>(null);
  const [ticketFilter, setTicketFilter] = useState<'prepare' | 'pending' | 'processing' | 'human_intervention' | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  /** 看板数据是否已完成首次拉取（用于区分「加载中」与「快照为空」） */
  const [boardDataInitialized, setBoardDataInitialized] = useState(false);

  const [collapsedStages, setCollapsedStages] = useState<Record<number, boolean>>({});
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isDragging = useRef(false);
  const lastMousePos = useRef({ x: 0, y: 0 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const [activeLineWidth, setActiveLineWidth] = useState<number>(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const antDark = useAntThemeDark();

  // Load Data：`GET /api/dev/iwhalecloud/owner_order_snapshot`；无快照时列表为空；异常时 rdManageService 回退 Mock
  useEffect(() => {
    let cancelled = false;
    setBoardDataInitialized(false);
    async function loadData() {
      try {
        const data = await fetchRdManageDemands(synapseApiBase);
        if (cancelled) return;
        const allTickets = (data.list || []).map(mapDemandListItemToTicket);

        allTickets.forEach((t) => {
          if (t.status === "completed") {
            t.currentNode = LAST_PIPELINE_NODE_ID;
            t.currentStage = LAST_PIPELINE_STAGE_ID;
          } else {
            const stage = SOP_STAGES.find((s) => s.nodes.some((n) => n.id === t.currentNode));
            t.currentStage = stage ? stage.id : 0;
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
      } catch (e) {
        if (!cancelled) console.error("Failed to load demands:", e);
      } finally {
        if (!cancelled) setBoardDataInitialized(true);
      }
    }
    loadData();
    return () => {
      cancelled = true;
    };
  }, [synapseApiBase]);

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
      if (ticketFilter === 'human_intervention') return t.status === 'human_intervention';
      if (ticketFilter === 'prepare') return t.status === 'prepare';
      return true;
    });
  }, [tickets, ticketFilter, searchQuery]);

  const pendingCount = useMemo(() => tickets.filter(t => t.status === 'pending').length, [tickets]);
  const processingCount = useMemo(() => tickets.filter(t => t.status === 'processing' || t.status === 'error').length, [tickets]);
  const humanInterventionCount = useMemo(() => tickets.filter(t => t.status === 'human_intervention').length, [tickets]);
  const prepareCount = useMemo(() => tickets.filter(t => t.status === 'prepare').length, [tickets]);
  const completedCount = useMemo(() => tickets.filter(t => t.status === 'completed').length, [tickets]);

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
      };
      if (activeTicket.status === "processing") {
        merge.currentNode = activeWorkItem.currentNode;
        merge.currentStage = stageIdForNodeId(activeWorkItem.currentNode);
      }
      return { ...activeTicket, ...merge };
    }
    return activeTicket;
  }, [activeTicket, activeWorkItem]);

  const getNodeStateGlobal = (ticket: Ticket | null, nodeId: string): NodeState => {
    if (!ticket) return 'pending';
    
    const targetNode = ALL_NODES.find(n => n.id === nodeId);
    if (!targetNode) return 'pending';

    // Fallback Mock Logic
    if (ticket.status === 'completed') return 'completed';
    if (ticket.status === 'prepare') return 'pending';
    if (ticket.status === 'pending') {
      if (nodeId === 'pending') return 'processing';
      return 'pending';
    }

    const targetIndex = ALL_NODES.findIndex(n => n.id === nodeId);
    const currentIndex = ALL_NODES.findIndex(n => n.id === ticket.currentNode);

    if (targetIndex < currentIndex) return 'completed';
    if (targetIndex > currentIndex) return 'pending';

    // Target is the current node
    if (ticket.status === 'processing') return 'processing';
    if (ticket.status === 'human_intervention') {
      const node = ALL_NODES[targetIndex];
      if (node && node.type.includes('human')) return 'human_intervention';
      return 'error';
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
    if (displayTicket.status === 'prepare' || displayTicket.status === 'human_intervention') return;
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

  const handleShowTicketDetails = (e: React.MouseEvent, ticket: Ticket) => {
    e.stopPropagation();
    setSelectedTicketForModal(ticket);
    setTicketModalOpen(true);
  };

  const handleJumpToMeeting = () => {
    if (onViewChange) {
      onViewChange("workbench_meeting");
    } else {
      window.dispatchEvent(new CustomEvent('changeView', { detail: 'workbench_meeting' }));
    }
  };

  // Render varied output based on node type/id
  const renderNodeOutput = (node: SOPNode, ticket: Ticket) => {
    const state = getNodeStateGlobal(ticket, node.id);
    if (state === 'pending') {
      return (
        <div className="flex flex-col items-center justify-center h-40 text-slate-500">
          <CircleDashed className="w-10 h-10 mb-3 opacity-50" />
          <p>节点未开始执行，暂无输出产物</p>
        </div>
      );
    }

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
        if (state === 'human_intervention') {
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
        if (state === 'human_intervention') {
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
                {state === 'human_intervention' ? <Badge status="warning" text="审核中" /> : <Badge status="success" text="已通过" />}
              </div>
              <div className="flex items-center justify-between bg-slate-900 p-3 rounded-lg border border-slate-800">
                <div className="flex items-center gap-3">
                  <Avatar className="bg-purple-500">李</Avatar>
                  <div>
                    <div className="text-sm text-slate-200">李四 (研发组长)</div>
                    <div className="text-xs text-slate-500">业务逻辑综合审查</div>
                  </div>
                </div>
                {state === 'human_intervention' ? (
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
          正在加载智能任务看板…
        </div>
      );
    }
    return (
      <div className="flex h-full min-h-0 flex-1 flex-col items-center justify-center gap-3 bg-background px-6 text-center text-muted-foreground">
        <FileText className="h-10 w-10 opacity-40" />
        <p className="max-w-md text-sm leading-relaxed">
          当前没有可用的工单快照数据。请先在 Synapse 中调用研发云接口
          <span className="font-mono text-foreground/80"> POST /api/dev/iwhalecloud/get_demand_by_user </span>
          同步负责人需求列表后，本页将自动读取快照文件展示。
        </p>
      </div>
    );
  }

  return (
    <ConfigProvider theme={{ algorithm: antDark ? theme.darkAlgorithm : theme.defaultAlgorithm }}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-1 overflow-hidden bg-background font-sans text-foreground">
        
        {/* Left Panel: 与会话列表同宽 */}
        <div className="z-20 flex w-[340px] min-w-[340px] shrink-0 flex-col border-r border-border bg-[color:var(--panel)]">
          <div className="convSidebarHeader">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
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

            <div className="mt-2 flex w-full min-w-0 flex-nowrap items-center justify-between gap-1">
              {([
                { id: 'prepare' as const, label: '预备中', count: prepareCount, color: 'text-blue-400' },
                { id: 'pending' as const, label: '待处理', count: pendingCount, color: 'text-muted-foreground' },
                { id: 'processing' as const, label: '处理中', count: processingCount, color: 'text-primary' },
                { id: 'human_intervention' as const, label: '全人工', count: humanInterventionCount, color: 'text-destructive' }
              ]).map(filter => (
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
                
                const statusBorderColor = 
                  ticket.status === 'human_intervention' ? 'bg-destructive' :
                  ticket.status === 'processing' ? 'bg-primary' :
                  ticket.status === 'completed' ? 'bg-green-600 dark:bg-green-500' :
                  'bg-muted-foreground/40';

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
                  });
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

                    {/* Global Hover Mask for Immediate Action */}
                    {ticket.status === 'human_intervention' && (
                      <div className="absolute inset-0 z-30 flex items-center justify-center bg-background/40 opacity-0 backdrop-blur-[2px] transition-opacity duration-300 group-hover:opacity-100">
                        <Button 
                          type="primary" 
                          size="small" 
                          className="h-8 rounded-full border-none bg-destructive px-5 font-medium text-destructive-foreground shadow-lg hover:bg-destructive/90"
                          onClick={(e) => {
                             e.stopPropagation();
                             setActiveTicketId(ticket.id);
                             setActiveWorkItemId(isWorkItem ? item.id : '');
                          }}
                        >
                          立即处理
                        </Button>
                      </div>
                    )}

                    {/* 工单信息：全人工时 hover 遮罩 z-30 会盖住默认层，在遮罩之上再渲染一份到右上角 */}
                    {ticket.status !== 'human_intervention' && (
                      <div className="absolute right-2 top-2 z-20 flex items-center gap-2">{ticketInfoButton}</div>
                    )}
                    {ticket.status === 'human_intervention' && (
                      <div className="absolute right-2 top-2 z-40 flex items-center gap-2">{ticketInfoButton}</div>
                    )}

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
                          {isDone ? '研发完成' : (currentNodeObj?.name || '未知节点')}
                        </span>
                      </div>
                      
                      <div className="flex shrink-0 items-center gap-2 font-mono text-[10px]">
                        <span className="relative flex items-center gap-1">
                          <Coins className={`h-3 w-3 ${ticket.status === 'processing' ? 'text-amber-500' : 'text-amber-500/70'}`} />
                          <span className={ticket.status === 'processing' ? 'text-amber-500' : 'text-amber-600/70 dark:text-amber-400/70'}>
                            {item.tokens >= 1000 ? (item.tokens/1000).toFixed(1) + 'k' : item.tokens}
                          </span>
                          {ticket.status === 'processing' && (
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
                        style={{ width: ticket.status === 'completed' ? '100%' : ticket.status === 'pending' || ticket.status === 'prepare' ? '0%' : `${progressPercent}%` }} 
                        animate={ticket.status === 'processing' ? { backgroundPosition: ['100% 0', '-100% 0'] } : {}}
                        transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
                      />
                    </div>
                  </motion.div>
                );
              };

              if (ticket.status === 'processing' && ticket.workItems && ticket.workItems.length > 0) {
                return (
                  <div key={ticket.id} className="relative mb-2 mt-3 rounded-[10px] border border-dashed border-primary/40 p-1.5 pt-3">
                    <div className="absolute -top-2.5 left-2 bg-[color:var(--panel)] px-1 text-[10px] font-medium text-primary">
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
                <span className="flex items-center gap-1.5"><Coins className="h-3.5 w-3.5 shrink-0 text-amber-500/80" /> 消耗 Token: <span className="font-mono text-foreground/90">{displayTicket.tokens.toLocaleString()}</span></span>
              </div>
            </div>
            
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {displayTicket.status === 'human_intervention' && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive shadow-sm"
                >
                  <ShieldAlert className="h-4 w-4 shrink-0" />
                  需人工干预
                </motion.div>
              )}
            </div>
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
            ) : displayTicket.status === 'human_intervention' ? (
              <div className="flex h-full items-center justify-center p-8">
                <div className="max-w-md rounded-xl border border-destructive/20 bg-destructive/5 p-6 text-center shadow-sm">
                  <User className="mx-auto mb-4 h-12 w-12 text-destructive/80" />
                  <h3 className="mb-2 text-lg font-medium text-foreground">全人工处理中</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    该工单由人工负责处理，小鲸暂时无法帮忙，请同学们把需要我帮忙处理的工单推进到需求设计环节，再启用全自动处理流程。
                  </p>
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
                        
                        // Generate processing stats based on node type
                        const nodeHash = node.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                        const timeStr = isHuman ? `${(nodeHash % 4) + 1}h ${nodeHash % 60}m` : `${((nodeHash % 50) / 10 + 0.5).toFixed(1)}s`;
                        const modelStr = isHuman ? '人工处理' : ['Claude-3.5', 'GPT-4o', 'Gemini-1.5'][nodeHash % 3];
                        const tokenStr = isHuman ? '--' : `${((nodeHash % 50 + 10) / 10).toFixed(1)}k`;
                        
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
                        } else if (state === 'human_intervention') {
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
                                {state === 'human_intervention' && (
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
                                     state === 'human_intervention' ? <AlertTriangle className={`w-4 h-4 ${iconClass} animate-pulse`} /> :
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
        title={
          <div className="mb-2 flex items-center gap-2 border-b border-border pb-4 text-lg text-foreground">
            <FileText className="h-5 w-5 text-primary" />
            工单详情
          </div>
        }
        open={ticketModalOpen}
        onCancel={() => setTicketModalOpen(false)}
        footer={null}
        width={600}
        styles={{
          root: { background: 'var(--panel2)', border: '1px solid var(--line)', color: 'var(--text)' },
          body: { paddingTop: 8 },
          header: { background: 'transparent' },
          mask: { backdropFilter: 'blur(4px)' }
        }}
        closeIcon={<span className="text-muted-foreground hover:text-foreground">✕</span>}
      >
        {selectedTicketForModal && (
          <div className="space-y-6 pt-2">
            <div>
              <h2 className="mb-2 text-xl font-bold text-foreground">{selectedTicketForModal.title}</h2>
              <div className="flex w-max items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 font-mono text-sm text-muted-foreground">
                <GitBranch className="h-4 w-4 text-primary" />
                {selectedTicketForModal.branch}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl border border-border bg-muted/25 p-4">
                <div className="mb-1 text-xs text-muted-foreground">当前阶段</div>
                <div className="font-medium text-primary">{SOP_STAGES[selectedTicketForModal.currentStage]?.name || '未知'}</div>
              </div>
              <div className="rounded-xl border border-border bg-muted/25 p-4">
                <div className="mb-1 text-xs text-muted-foreground">状态</div>
                <div className="font-medium">
                  {selectedTicketForModal.status === 'human_intervention' ? <span className="text-destructive">需人工干预</span> :
                   selectedTicketForModal.status === 'processing' ? <span className="text-primary">处理中</span> : 
                   selectedTicketForModal.status === 'error' ? <span className="text-destructive">异常</span> : 
                   selectedTicketForModal.status === 'completed' ? <span className="text-green-600 dark:text-green-400">已完成</span> : 
                   <span className="text-muted-foreground">待处理</span>}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-muted/25 p-4">
                <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground"><Clock className="h-3.5 w-3.5"/> 运行时长</div>
                <div className="font-medium text-foreground">{selectedTicketForModal.runTime}</div>
              </div>
              <div className="rounded-xl border border-border bg-muted/25 p-4">
                <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground"><Coins className="h-3.5 w-3.5"/> 消耗 Token</div>
                <div className="font-medium text-foreground">{selectedTicketForModal.tokens.toLocaleString()}</div>
              </div>
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">需求描述</div>
              <div className="min-h-[100px] rounded-xl border border-border bg-background p-4 text-sm leading-relaxed text-foreground/90">
                {selectedTicketForModal.description}
              </div>
            </div>

            <div className="flex items-center justify-between border-t border-border pt-4 text-xs text-muted-foreground">
              <div>创建时间: {selectedTicketForModal.createdAt}</div>
              <div className="flex items-center gap-1.5">负责人: <Avatar size={16} className="bg-muted text-[10px] text-foreground">{selectedTicketForModal.owner.charAt(0)}</Avatar> {selectedTicketForModal.owner}</div>
            </div>
          </div>
        )}
      </Modal>

    </ConfigProvider>
  );
};
