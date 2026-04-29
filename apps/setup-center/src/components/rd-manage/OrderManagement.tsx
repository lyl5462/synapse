import React, { useState, useMemo, useEffect, useRef } from 'react';
import { ConfigProvider, theme, Badge, Avatar, Button, Drawer, Modal, Tag, Progress, Tabs } from 'antd';
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
  AlertCircle
} from 'lucide-react';
import { fetchRdManageDemands, fetchRdManageDemandNodes, DemandNodeInfo, DemandInfo } from '../../api/rdManageService';
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

export interface Ticket {
  id: string;
  branch: string;
  title: string;
  currentStage: number;
  currentNode: string;
  status: 'processing' | 'human_intervention' | 'pending' | 'completed' | 'error';
  owner: string;
  urgency: 'low' | 'medium' | 'high';
  tokens: number;
  runTime: string;
  description: string;
  createdAt: string;
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

type NodeState = 'completed' | 'processing' | 'error' | 'human_intervention' | 'pending';

// --- Subcomponents for Outputs ---

const TerminalOutput = ({ lines }: { lines: string[] }) => (
  <div className="bg-[#050505] border border-slate-800 rounded-lg p-3 font-mono text-xs overflow-y-auto max-h-64 custom-scrollbar">
    {lines.map((line, i) => (
      <div key={i} className="mb-1">
        <span className="text-emerald-500 mr-2">$</span>
        <span className={line.includes('Error') ? 'text-red-400' : line.includes('Warning') ? 'text-amber-400' : 'text-slate-300'}>
          {line}
        </span>
      </div>
    ))}
  </div>
);

const JsonOutput = ({ data }: { data: any }) => (
  <div className="bg-[#050505] border border-slate-800 rounded-lg p-4 font-mono text-xs overflow-auto max-h-64 custom-scrollbar text-blue-300">
    <pre>{JSON.stringify(data, null, 2)}</pre>
  </div>
);

// --- Main Components ---

export const OrderManagement: React.FC<{
  synapseApiBase?: string;
  onViewChange?: (view: ViewId) => void;
}> = ({ synapseApiBase = "http://127.0.0.1:18900", onViewChange }) => {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [activeTicketId, setActiveTicketId] = useState<string>('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<SOPNode | null>(null);
  const [ticketModalOpen, setTicketModalOpen] = useState(false);
  const [selectedTicketForModal, setSelectedTicketForModal] = useState<Ticket | null>(null);
  const [ticketFilter, setTicketFilter] = useState<'all' | 'pending' | 'processing' | 'completed'>('all');
  const [ticketNodes, setTicketNodes] = useState<DemandNodeInfo[]>([]);

  const containerRef = useRef<HTMLDivElement>(null);

  // Load Data from Backend
  useEffect(() => {
    async function loadData() {
      try {
        const data = await fetchRdManageDemands(synapseApiBase);
        const allTickets: Ticket[] = [];
        const mapDemands = (demands: DemandInfo[] = []) => {
          return demands.map(d => ({
            id: d.需求单号 || `TICKET-${Math.random().toString(36).substring(7)}`,
            title: d.需求单名称 || '未知需求',
            description: d.需求描述 || '',
            createdAt: d.需求开始时间 || new Date().toISOString(),
            runTime: d.需求结束时间 || "0h",
            tokens: d.需求工作量 || 0,
            status: (d.需求状态 || 'pending') as any,
            owner: d.设计人员 || '未知',
            branch: d.需求关联应用模块 || 'master',
            urgency: d.需求优先级 === '高' ? 'high' : d.需求优先级 === '中' ? 'medium' : 'low',
            currentNode: d.当前sop节点 || 'pending',
            currentStage: 0 // Will compute below
          }));
        };
        allTickets.push(...mapDemands(data.预备工单));
        allTickets.push(...mapDemands(data.可处理工单));
        allTickets.push(...mapDemands(data.在途工单));
        allTickets.push(...mapDemands(data.近三月完成工单));
        
        allTickets.forEach(t => {
          const stage = SOP_STAGES.find(s => s.nodes.some(n => n.id === t.currentNode));
          t.currentStage = stage ? stage.id : 0;
        });
        
        setTickets(allTickets);
        if (allTickets.length > 0) setActiveTicketId(allTickets[0].id);
      } catch (e) {
        console.error("Failed to load demands:", e);
      }
    }
    loadData();
  }, [synapseApiBase]);

  // Load node data when active ticket changes
  useEffect(() => {
    if (!activeTicketId) return;
    fetchRdManageDemandNodes(synapseApiBase, activeTicketId).then(res => {
      setTicketNodes(res.nodes || []);
    }).catch(console.error);
  }, [activeTicketId, synapseApiBase]);

  const filteredTickets = useMemo(() => {
    return tickets.filter(t => {
      if (ticketFilter === 'all') return true;
      if (ticketFilter === 'pending') return t.status === 'pending';
      if (ticketFilter === 'processing') return t.status === 'processing' || t.status === 'human_intervention' || t.status === 'error';
      if (ticketFilter === 'completed') return t.status === 'completed';
      return true;
    });
  }, [tickets, ticketFilter]);

  const pendingCount = useMemo(() => tickets.filter(t => t.status === 'pending').length, [tickets]);
  const processingCount = useMemo(() => tickets.filter(t => t.status === 'processing' || t.status === 'human_intervention' || t.status === 'error').length, [tickets]);
  const completedCount = useMemo(() => tickets.filter(t => t.status === 'completed').length, [tickets]);

  const activeTicket = useMemo(() => tickets.find(t => t.id === activeTicketId) || tickets[0] || null, [activeTicketId, tickets]);

  const getNodeStateGlobal = (ticket: Ticket | null, nodeId: string): NodeState => {
    if (!ticket) return 'pending';
    
    // API logic check
    const targetNode = ALL_NODES.find(n => n.id === nodeId);
    if (!targetNode) return 'pending';
    const apiNode = ticketNodes.find(n => n.node_name === targetNode.name);
    if (apiNode && apiNode.node_status) {
      return apiNode.node_status as NodeState;
    }

    // Fallback Mock Logic
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
            tokens: t.tokens + Math.floor(Math.random() * 80) + 20
          };
        }
        return t;
      }));
    }, 1500);
    return () => clearInterval(interval);
  }, []);

  // Handle auto-scroll to current node when ticket changes
  useEffect(() => {
    if (!containerRef.current || !activeTicket) return;
    const timeoutId = setTimeout(() => {
      const activeNodeElement = document.getElementById(`node-${activeTicket.currentNode}`);
      const container = containerRef.current;
      if (activeNodeElement && container) {
        const nodeRect = activeNodeElement.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        const nodeCenter = nodeRect.left + (nodeRect.width / 2);
        const containerCenter = containerRect.left + (containerRect.width / 2);
        const scrollDelta = nodeCenter - containerCenter;
        container.scrollTo({
          left: container.scrollLeft + scrollDelta,
          behavior: 'smooth'
        });
      }
    }, 150);
    return () => clearTimeout(timeoutId);
  }, [activeTicketId, activeTicket?.currentNode]);

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

    const apiNode = ticketNodes.find(n => n.node_name === node.name);

    if (apiNode && apiNode.output_artifacts) {
        // Render from API if present
        return (
            <div className="space-y-3">
                <h4 className="text-sm font-medium text-slate-400 flex items-center gap-2"><Network className="w-4 h-4" /> 节点数据</h4>
                <JsonOutput data={apiNode.output_artifacts} />
                {state === 'human_intervention' && (
                    <Button type="primary" block size="large" className="mt-4 bg-amber-600 hover:bg-amber-500 border-none" onClick={handleJumpToMeeting}>
                        跳转研发会议室 (预置 TODO)
                    </Button>
                )}
            </div>
        )
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

  if (!activeTicket) {
    return <div className="flex h-full items-center justify-center text-slate-400">Loading demands...</div>;
  }

  return (
    <ConfigProvider theme={{ algorithm: theme.darkAlgorithm }}>
      <div className="flex h-full w-full bg-[#050505] text-slate-200 overflow-hidden font-sans">
        
        {/* Left Panel: Ticket List */}
        <div className="w-80 flex-shrink-0 border-r border-slate-800/60 bg-[#0a0a0e] flex flex-col z-20">
          <div className="p-4 border-b border-slate-800/60 backdrop-blur-md flex flex-col gap-3">
            <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-400" />
              已分配工作
            </h2>
            <div className="flex items-center justify-between p-1 bg-slate-900/50 border border-slate-800 rounded-lg mt-1">
              {[
                { id: 'all', label: '全部', count: tickets.length, color: 'text-slate-200' },
                { id: 'pending', label: '未进行', count: pendingCount, color: 'text-slate-400' },
                { id: 'processing', label: '处理中', count: processingCount, color: 'text-blue-400' },
                { id: 'completed', label: '近3月份完成', count: completedCount, color: 'text-green-400' }
              ].map(filter => (
                <button
                  key={filter.id}
                  onClick={() => setTicketFilter(filter.id as any)}
                  className={`flex-1 flex items-center justify-center gap-1 py-1.5 rounded-md transition-all duration-200 ${
                    ticketFilter === filter.id 
                      ? 'bg-slate-800 shadow-sm ring-1 ring-slate-700' 
                      : 'hover:bg-slate-800/50'
                  }`}
                >
                  <span className={`text-xs font-medium whitespace-nowrap ${ticketFilter === filter.id ? filter.color : 'text-slate-500'}`}>
                    {filter.label}
                  </span>
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-full ${
                    ticketFilter === filter.id 
                      ? 'bg-black/40 text-slate-300' 
                      : 'bg-transparent text-slate-600'
                  }`}>
                    {filter.count}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-3">
            {filteredTickets.map(ticket => {
              const currentNodeObj = ALL_NODES.find(n => n.id === ticket.currentNode);
              const progressPercent = Math.round((ticket.currentStage / (SOP_STAGES.length - 1)) * 100);
              
              const statusBorderColor = 
                ticket.status === 'human_intervention' ? 'bg-red-500' :
                ticket.status === 'processing' ? 'bg-blue-500' :
                'bg-slate-600';

              return (
                <motion.div
                  key={ticket.id}
                  whileHover={{ scale: 1.01 }}
                  whileTap={{ scale: 0.99 }}
                  onClick={() => setActiveTicketId(ticket.id)}
                  className={`relative p-4 rounded-xl cursor-pointer transition-all duration-300 overflow-hidden group ${
                    activeTicketId === ticket.id 
                      ? 'bg-white/[0.08] shadow-[0_8px_24px_rgba(0,0,0,0.4)] ring-1 ring-white/10' 
                      : 'bg-white/[0.02] hover:bg-white/[0.04]'
                  }`}
                >
                  {/* Left Status Line */}
                  <div className={`absolute left-0 top-0 bottom-0 w-1 ${statusBorderColor}`} />

                  {/* Actions & Details Button */}
                  <div className="absolute top-3 right-3 flex items-center gap-2">
                    {ticket.status === 'human_intervention' && (
                      <Button 
                        type="primary" 
                        size="small" 
                        className={`${activeTicketId === ticket.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} transition-opacity duration-300 bg-red-600 hover:bg-red-500 text-[10px] h-6 px-2 border-none shadow-[0_0_10px_rgba(239,68,68,0.4)] z-20`}
                        onClick={(e) => {
                           e.stopPropagation();
                           handleShowTicketDetails(e, ticket);
                        }}
                      >
                        立即处理
                      </Button>
                    )}
                    <Button 
                      type="text" 
                      size="small" 
                      icon={<Info className="w-3.5 h-3.5" />} 
                      className="text-slate-500 hover:text-blue-400 flex items-center justify-center p-0 w-6 h-6 z-10"
                      onClick={(e) => handleShowTicketDetails(e, ticket)}
                    />
                  </div>

                  {/* Top: Ticket ID & Urgency */}
                  <div className="flex items-center gap-2 mb-2 pl-2">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-white/[0.06] text-slate-400">
                      {ticket.id}
                    </span>
                    {ticket.urgency === 'high' && (
                      <Flame className="w-3.5 h-3.5 text-red-500 animate-pulse" />
                    )}
                  </div>
                  
                  {/* Middle: Title */}
                  <h3 className={`font-medium mb-4 line-clamp-2 text-sm pr-8 pl-2 ${activeTicketId === ticket.id ? 'text-blue-50' : 'text-slate-300'}`}>
                    {ticket.title}
                  </h3>

                  {/* Bottom: Node Info & Meta */}
                  <div className="flex items-center justify-between text-xs text-slate-400 pl-2">
                    <div className="flex items-center gap-1.5">
                      {currentNodeObj?.type.includes('human') ? (
                        <User className="w-3.5 h-3.5 text-amber-400" />
                      ) : currentNodeObj?.type.includes('system') ? (
                        <TerminalSquare className="w-3.5 h-3.5 text-slate-400" />
                      ) : (
                        <Bot className="w-3.5 h-3.5 text-blue-400" />
                      )}
                      <span className="text-slate-300">
                        {currentNodeObj?.name || '未知节点'}
                      </span>
                    </div>
                    
                    <div className="flex items-center gap-2.5 font-mono text-[10px]">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3 text-slate-400" />
                        <span className="text-slate-300">{ticket.runTime}</span>
                      </span>
                      <span className="flex items-center gap-1 relative">
                        <Coins className={`w-3 h-3 ${ticket.status === 'processing' ? 'text-amber-500' : 'text-amber-500/70'}`} />
                        <span className={ticket.status === 'processing' ? 'text-amber-400' : 'text-amber-500/70'}>
                          {ticket.tokens >= 1000 ? (ticket.tokens/1000).toFixed(1) + 'k' : ticket.tokens}
                        </span>
                        {ticket.status === 'processing' && (
                          <motion.div
                            initial={{ y: 5, opacity: 0 }}
                            animate={{ y: -10, opacity: [0, 1, 0] }}
                            transition={{ repeat: Infinity, duration: 1.5 }}
                            className="absolute -right-3 -top-1 text-green-400"
                          >
                            <TrendingUp className="w-2.5 h-2.5" />
                          </motion.div>
                        )}
                      </span>
                    </div>
                  </div>

                  {/* Background Progress Bar */}
                  <div className="absolute bottom-0 left-0 right-0 h-[2px] bg-white/[0.02]">
                    <motion.div 
                      className="h-full bg-gradient-to-r from-blue-600 via-indigo-400 to-blue-600 bg-[length:200%_100%]" 
                      style={{ width: `${progressPercent}%` }} 
                      animate={ticket.status === 'processing' ? { backgroundPosition: ['100% 0', '-100% 0'] } : {}}
                      transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
                    />
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* Right Panel: Pipeline Dashboard */}
        <div className="flex-1 flex flex-col bg-[#050505] relative overflow-hidden">
          
          {/* Header */}
          <div className="h-20 border-b border-slate-800/60 px-8 flex items-center justify-between backdrop-blur-md bg-slate-950/50 z-20">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <h1 className="text-lg font-bold text-slate-100 tracking-wide">{activeTicket.title}</h1>
                <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] font-mono text-indigo-300">
                  {activeTicket.id}
                </span>
              </div>
              <div className="flex items-center gap-5 text-xs text-slate-400">
                <span className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5" /> 持续运行: <span className="text-slate-200 font-mono">{activeTicket.runTime}</span></span>
                <span className="flex items-center gap-1.5"><Coins className="w-3.5 h-3.5 text-amber-500/80" /> 消耗 Token: <span className="text-slate-200 font-mono">{activeTicket.tokens.toLocaleString()}</span></span>
              </div>
            </div>
            
            <div className="flex items-center gap-3">
              {activeTicket.status === 'human_intervention' && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="px-4 py-1.5 bg-red-950/40 border border-red-500/50 rounded-lg flex items-center gap-2 text-red-400 text-xs font-medium shadow-[0_0_15px_rgba(239,68,68,0.15)]"
                >
                  <ShieldAlert className="w-4 h-4" />
                  需人工干预
                </motion.div>
              )}
            </div>
          </div>

          {/* Neural Pipeline Board (Horizontal Data Bus Layout) */}
          <div 
            ref={containerRef}
            className="flex-1 overflow-x-auto overflow-y-hidden relative custom-scrollbar bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-900/20 via-[#050505] to-[#050505]"
          >
            
            <div className="flex items-center h-full min-w-max px-16 relative">
              {/* Background Central Data Bus Line */}
              <div className="absolute top-1/2 left-0 right-0 h-1.5 bg-slate-800 -translate-y-1/2 z-0 rounded-full mx-8 shadow-inner" />
              
              {/* Active Central Data Bus Line */}
              <motion.div 
                className="absolute top-1/2 left-8 h-1.5 bg-blue-500 -translate-y-1/2 z-0 rounded-full shadow-[0_0_15px_rgba(59,130,246,0.8)]"
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(0, (ALL_NODES.findIndex(n => n.id === activeTicket.currentNode) / Math.max(1, ALL_NODES.length - 1)) * 100)}%` }}
                transition={{ duration: 0.8, ease: "easeOut" }}
                style={{ maxWidth: 'calc(100% - 4rem)' }}
              />

              {SOP_STAGES.map((stage, sIdx) => {
                const isStagePast = activeTicket.currentStage > stage.id;
                const isStageActive = activeTicket.currentStage === stage.id;
                const isStageFuture = activeTicket.currentStage < stage.id;

                return (
                  <div key={stage.id} className="flex relative z-10 px-6 h-full border-l border-slate-800/50 border-dashed">
                    
                    {/* Stage Label on the Line */}
                    <div className="absolute top-1/2 left-0 -translate-y-1/2 -translate-x-1/2 flex flex-col items-center">
                       <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-4 border-[#050505] z-10 ${
                         isStagePast ? 'bg-green-500 text-black shadow-[0_0_10px_rgba(34,197,94,0.5)]' :
                         isStageActive ? 'bg-blue-500 text-white shadow-[0_0_15px_rgba(59,130,246,0.6)]' :
                         'bg-slate-700 text-slate-400'
                       }`}>
                         {isStagePast ? <CheckCircle2 className="w-5 h-5" /> : stage.id}
                       </div>
                       <div className={`absolute top-10 whitespace-nowrap text-xs font-medium tracking-widest ${isStageActive ? 'text-blue-400' : isStagePast ? 'text-slate-400' : 'text-slate-600'}`}>
                         {stage.name}
                       </div>
                    </div>

                    {/* Nodes Array */}
                    <div className="flex ml-16 h-full items-center">
                      {stage.nodes.map((node, nIdx) => {
                        const globalIndex = ALL_NODES.findIndex(n => n.id === node.id);
                        const isTop = globalIndex % 2 === 0;
                        const state = getNodeStateGlobal(activeTicket, node.id);
                        const apiNode = ticketNodes.find(n => n.node_name === node.name);
                        
                        const isHuman = node.type.includes('human') || node.type === 'ai_exception' || apiNode?.role === 'Human';
                        const nextNode = stage.nodes[nIdx + 1];
                        const isNextHuman = nextNode && (nextNode.type.includes('human') || nextNode.type === 'ai_exception');
                        
                        // Group AI nodes highly compressed (-mr-12 for horizontal overlapping), separate human intervention/wait nodes heavily (mr-32)
                        const marginClass = nIdx === stage.nodes.length - 1 ? 'mr-16' : (isHuman || isNextHuman ? 'mr-32' : '-mr-12');
                        
                        // Generate processing stats based on node type or apiNode
                        const nodeHash = node.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                        const timeStr = apiNode?.time_cost || (isHuman ? `${(nodeHash % 4) + 1}h ${nodeHash % 60}m` : `${((nodeHash % 50) / 10 + 0.5).toFixed(1)}s`);
                        const modelStr = apiNode?.model || (isHuman ? '人工处理' : ['Claude-3.5', 'GPT-4o', 'Gemini-1.5'][nodeHash % 3]);
                        const tokenStr = apiNode?.token_cost ? `${(apiNode.token_cost/1000).toFixed(1)}k` : (isHuman ? '--' : `${((nodeHash % 50 + 10) / 10).toFixed(1)}k`);
                        
                        let cardClass = "bg-slate-900/50 border-slate-800 text-slate-400 h-[120px]";
                        let iconClass = "text-slate-500";
                        let dotClass = "bg-slate-700 border-[#050505]";
                        let lineClass = "bg-slate-800";
                        let hoverClass = "hover:border-slate-600 hover:bg-slate-800/80";

                        if (state === 'completed') {
                          cardClass = "bg-slate-900/80 border-green-500/30 text-slate-300 h-[140px]";
                          iconClass = "text-green-500";
                          dotClass = "bg-green-500 border-[#050505]";
                          lineClass = "bg-green-500/50";
                          hoverClass = "hover:border-green-500/60 hover:bg-slate-800";
                        } else if (state === 'processing') {
                          cardClass = "bg-blue-900/20 border-blue-400/50 text-blue-100 shadow-[0_0_20px_rgba(59,130,246,0.15)] h-[120px]";
                          iconClass = "text-blue-400";
                          dotClass = "bg-blue-400 border-[#050505] shadow-[0_0_10px_rgba(59,130,246,0.8)]";
                          lineClass = "bg-blue-400/80";
                          hoverClass = "hover:border-blue-400 hover:bg-blue-900/30";
                        } else if (state === 'error') {
                          cardClass = "bg-red-950/40 border-red-500/60 text-red-100 shadow-[0_0_20px_rgba(239,68,68,0.2)] h-[120px]";
                          iconClass = "text-red-500";
                          dotClass = "bg-red-500 border-[#050505] shadow-[0_0_10px_rgba(239,68,68,0.8)] animate-pulse";
                          lineClass = "bg-red-500/80";
                          hoverClass = "hover:border-red-400 hover:bg-red-900/50";
                        } else if (state === 'human_intervention') {
                          cardClass = "bg-amber-950/40 border-amber-500/60 text-amber-100 shadow-[0_0_20px_rgba(245,158,11,0.2)] h-[120px]";
                          iconClass = "text-amber-500";
                          dotClass = "bg-amber-500 border-[#050505] shadow-[0_0_10px_rgba(245,158,11,0.8)] animate-pulse";
                          lineClass = "bg-amber-500/80";
                          hoverClass = "hover:border-amber-400 hover:bg-amber-900/50";
                        }

                        return (
                          <div id={`node-${node.id}`} key={node.id} className={`relative flex flex-col justify-center items-center w-56 h-[500px] ${marginClass}`}>
                            {/* Stem connecting card to central bus */}
                            <div className={`absolute left-1/2 w-0.5 -translate-x-1/2 ${lineClass} z-0 ${
                              isTop ? 'bottom-1/2 h-[40px]' : 'top-1/2 h-[40px]'
                            }`} />

                            {/* Node Point on Data Bus */}
                            <div className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border-[3px] z-10 ${dotClass}`} />

                            {/* Node Card */}
                            <motion.div
                              whileHover={{ scale: 1.05, y: isTop ? -5 : 5 }}
                              onClick={() => handleNodeClick(node)}
                              className={`absolute left-0 w-full p-4 rounded-xl border backdrop-blur-md cursor-pointer transition-all duration-300 z-20 flex flex-col ${cardClass} ${hoverClass} ${isTop ? 'bottom-[calc(50%+40px)]' : 'top-[calc(50%+40px)]'}`}
                            >
                              <div className="flex items-start justify-between mb-2">
                                <div className="p-1.5 rounded-lg bg-black/30">
                                  {state === 'completed' ? <CheckCircle2 className={`w-4 h-4 ${iconClass}`} /> :
                                   state === 'processing' ? <Loader2 className={`w-4 h-4 ${iconClass} animate-spin`} /> :
                                   state === 'error' ? <AlertCircle className={`w-4 h-4 ${iconClass} animate-pulse`} /> :
                                   state === 'human_intervention' ? <AlertTriangle className={`w-4 h-4 ${iconClass} animate-pulse`} /> :
                                   <CircleDashed className={`w-4 h-4 ${iconClass}`} />}
                                </div>
                                <div className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-black/40 border border-white/5">
                                  {isHuman ? (
                                    <span className="flex items-center gap-1 text-amber-400"><User className="w-3 h-3" /> 人工</span>
                                  ) : node.type.includes('ai') || apiNode?.role === 'AI' ? (
                                    <span className="flex items-center gap-1 text-blue-400"><Bot className="w-3 h-3" /> AI</span>
                                  ) : (
                                    <span className="flex items-center gap-1 text-slate-400"><TerminalSquare className="w-3 h-3" /> 系统</span>
                                  )}
                                </div>
                              </div>
                              <h4 className="font-medium text-sm mb-1">{node.name}</h4>
                              <p className="text-[10px] leading-relaxed opacity-70 line-clamp-2 flex-1">{node.desc}</p>
                              
                              {state === 'completed' && (
                                <div className="mt-2 pt-2 border-t border-slate-700/50 flex items-center justify-between text-[10px] text-slate-400 font-mono gap-2 w-full">
                                  {!isHuman && (
                                    <div className="flex items-center gap-1 opacity-80" title="执行模型">
                                      <Cpu className="w-3 h-3 text-blue-400/70" />
                                      <span>{modelStr}</span>
                                    </div>
                                  )}
                                  <div className="flex items-center gap-1 opacity-80 ml-auto" title="节点耗时">
                                    <Clock className="w-3 h-3 text-slate-400/70" />
                                    <span>{timeStr}</span>
                                  </div>
                                  {!isHuman && (
                                    <div className="flex items-center gap-1 opacity-80" title="Token消耗">
                                      <Coins className="w-3 h-3 text-amber-500/70" />
                                      <span>{tokenStr}</span>
                                    </div>
                                  )}
                                </div>
                              )}
                            </motion.div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Node Details Drawer */}
      <Drawer
        title={
          <div className="flex items-center gap-3 text-slate-200">
            {selectedNode?.type.includes('ai') ? (
               <div className="p-1.5 bg-blue-500/20 rounded-lg"><Bot className="text-blue-400 w-5 h-5" /></div>
            ) : (
               <div className="p-1.5 bg-amber-500/20 rounded-lg"><User className="text-amber-500 w-5 h-5" /></div>
            )}
            <span className="font-semibold text-base">{selectedNode?.name}</span>
          </div>
        }
        placement="right"
        onClose={() => setDrawerOpen(false)}
        open={drawerOpen}
        width={500}
        styles={{
          header: { background: '#0a0a0f', borderBottom: '1px solid #1e293b', padding: '16px 24px' },
          body: { background: '#050505', padding: '24px' },
          mask: { backdropFilter: 'blur(3px)', background: 'rgba(0,0,0,0.6)' }
        }}
        closeIcon={<span className="text-slate-500 hover:text-white transition-colors">✕</span>}
      >
        {selectedNode && (
          <div className="h-full flex flex-col">
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-4 mb-6 shadow-inner">
              <h4 className="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wider">节点说明</h4>
              <p className="text-slate-300 leading-relaxed text-sm">
                {selectedNode.desc}
              </p>
            </div>

            <div className="flex-1">
              <h4 className="text-xs font-semibold text-slate-500 mb-4 uppercase tracking-wider">执行产物 / 交互区</h4>
              {renderNodeOutput(selectedNode, activeTicket)}
            </div>
          </div>
        )}
      </Drawer>

      {/* Ticket Details Modal */}
      <Modal
        title={
          <div className="flex items-center gap-2 text-lg border-b border-slate-800 pb-4 mb-2">
            <FileText className="w-5 h-5 text-blue-400" />
            工单详情
          </div>
        }
        open={ticketModalOpen}
        onCancel={() => setTicketModalOpen(false)}
        footer={null}
        width={600}
        styles={{
          content: { background: '#0a0a0f', border: '1px solid #1e293b', color: '#f1f5f9', padding: '24px' },
          header: { background: 'transparent' },
          mask: { backdropFilter: 'blur(4px)' }
        }}
        closeIcon={<span className="text-slate-500 hover:text-white">✕</span>}
      >
        {selectedTicketForModal && (
          <div className="space-y-6 pt-2">
            <div>
              <h2 className="text-xl font-bold text-slate-100 mb-2">{selectedTicketForModal.title}</h2>
              <div className="flex items-center gap-2 text-sm text-slate-400 font-mono bg-slate-900 px-3 py-1.5 rounded-lg w-max border border-slate-800">
                <GitBranch className="w-4 h-4 text-indigo-400" />
                {selectedTicketForModal.branch}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800">
                <div className="text-xs text-slate-500 mb-1">当前阶段</div>
                <div className="font-medium text-blue-400">{SOP_STAGES[selectedTicketForModal.currentStage]?.name || '未知'}</div>
              </div>
              <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800">
                <div className="text-xs text-slate-500 mb-1">状态</div>
                <div className="font-medium">
                  {selectedTicketForModal.status === 'human_intervention' ? <span className="text-red-400">需人工干预</span> :
                   selectedTicketForModal.status === 'processing' ? <span className="text-blue-400">处理中</span> : 
                   selectedTicketForModal.status === 'error' ? <span className="text-red-400">异常</span> : 
                   selectedTicketForModal.status === 'completed' ? <span className="text-green-400">已完成</span> : 
                   <span className="text-slate-400">待处理</span>}
                </div>
              </div>
              <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800">
                <div className="text-xs text-slate-500 mb-1 flex items-center gap-1.5"><Clock className="w-3.5 h-3.5"/> 运行时长</div>
                <div className="font-medium text-slate-200">{selectedTicketForModal.runTime}</div>
              </div>
              <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800">
                <div className="text-xs text-slate-500 mb-1 flex items-center gap-1.5"><Coins className="w-3.5 h-3.5"/> 消耗 Token</div>
                <div className="font-medium text-slate-200">{selectedTicketForModal.tokens.toLocaleString()}</div>
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-slate-500 mb-2 uppercase">需求描述</div>
              <div className="bg-[#050505] p-4 rounded-xl border border-slate-800 text-sm text-slate-300 leading-relaxed min-h-[100px]">
                {selectedTicketForModal.description}
              </div>
            </div>

            <div className="flex items-center justify-between text-xs text-slate-500 border-t border-slate-800 pt-4">
              <div>创建时间: {selectedTicketForModal.createdAt}</div>
              <div className="flex items-center gap-1.5">负责人: <Avatar size={16} className="bg-slate-700 text-[10px]">{selectedTicketForModal.owner.charAt(0)}</Avatar> {selectedTicketForModal.owner}</div>
            </div>
          </div>
        )}
      </Modal>

    </ConfigProvider>
  );
};
