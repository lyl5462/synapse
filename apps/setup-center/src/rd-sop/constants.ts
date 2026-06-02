/** 研发 SOP 流水线定义（工单管理 / 研发会议室共用，Phase 0 单源） */

/**
 * 节点处理方式（展示语义，与会议室/工单 UI 一致）：
 * - `human` / `human_start`：人工主导，AI 辅助
 * - `ai`：AI 主导，人工辅助
 * - `ai_human`：人工与 AI 协同处理
 * - `system`：由应用或脚本独立实现
 */
export type NodeType =
  | 'ai'
  | 'human'
  | 'human_start'
  | 'ai_exception'
  | 'ai_human'
  | 'system'
  | 'human_multi';

/** 节点类型短标签（导航、看板、配置抽屉共用） */
export const NODE_TYPE_LABEL: Record<NodeType, string> = {
  ai: 'AI',
  human: '人工',
  human_start: '人工',
  ai_exception: '降级',
  ai_human: '协同',
  system: '系统',
  human_multi: '会审',
};

export interface SOPNode {
  id: string;
  name: string;
  type: NodeType;
  desc: string;
}

export interface SOPStage {
  id: number;
  name: string;
  nodes: SOPNode[];
}

export const SOP_STAGES: SOPStage[] = [
  {
    id: 0,
    name: '待处理',
    nodes: [
      { id: 'pending', name: '等待调度', type: 'system', desc: '工单刚创建，等待进入智能研发流程' },
    ],
  },
  {
    id: 1,
    name: '需求分析',
    nodes: [
      { id: 'req_clarify', name: '需求澄清', type: 'human', desc: '识别需求模糊点和歧义，自动交互式推进完善' },
      { id: 'boundary', name: '边界确认', type: 'ai', desc: '识别跨产品场景，确保单个需求只处理一个产品' },
      { id: 'module_func', name: '模块功能', type: 'ai', desc: '对需求进行功能模块拆分，为设计做准备' },
      { id: 'acceptance', name: '验收标准', type: 'ai', desc: '针对拆分出的功能模块完成验收要求设定' },
      { id: 'req_risk', name: '需求风险', type: 'human', desc: '高风险需求需人工介入，评估影响和工作量' },
    ],
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
      { id: 'solution_review', name: '方案评审', type: 'ai_human', desc: '发起评审，设计助手答辩，可调用沙箱验证可行性' },
    ],
  },
  {
    id: 3,
    name: '需求研发',
    nodes: [
      { id: 'auto_split', name: '自动拆单', type: 'system', desc: '按需求单与方案自动拆分研发子单（系统脚本，无大模型）' },
      { id: 'sandbox_build', name: '沙箱构建', type: 'system', desc: '针对研发单拉取沙箱代码（git 落盘至 work/<工单>/sandbox/）' },
      { id: 'env_pregen', name: '环境预生成', type: 'system', desc: '拉取文档与控熵归档至 work/<工单>/env/（系统脚本）' },
    ],
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
      { id: 'unit_test', name: '单元自测', type: 'ai', desc: '根据验收标准生成测试用例，自测通过后自动提交试飞' },
    ],
  },
  {
    id: 5,
    name: '代码走查',
    nodes: [
      { id: 'dev_process_review', name: '开发流程评审', type: 'ai', desc: '检查开发耗时、token消耗、冲突情况等是否合规' },
      { id: 'solution_consistency', name: '方案一致性', type: 'ai', desc: '二次核对涉及的文件/模块/功能是否严遵方案' },
      { id: 'risk_review', name: '风险评审', type: 'ai', desc: '综合评定开发中的情况及测试充分率是否存在风险' },
      { id: 'entropy_review', name: '控熵评审', type: 'ai', desc: '双向校验控熵文件内容与代码改造差异点的各类结构' },
      {
        id: 'leader_review',
        name: '研发组长评审',
        type: 'ai_human',
        desc: '研发组长与 AI 协同综合评审，全员通过后转单发布',
      },
    ],
  },
];

export const ALL_NODES = SOP_STAGES.flatMap((s) => s.nodes.map((n) => ({ ...n, stageId: s.id })));

export const LAST_PIPELINE_STAGE_ID = SOP_STAGES[SOP_STAGES.length - 1]?.id ?? 5;

export const LAST_PIPELINE_NODE_ID = ALL_NODES[ALL_NODES.length - 1]?.id ?? 'leader_review';

export function resolveSopRawToNodeId(sopRaw: string): string | null {
  const sop = (sopRaw || '').trim();
  if (!sop) return null;
  return ALL_NODES.find((n) => n.name === sop || n.id === sop)?.id ?? null;
}

export function stageIdForNodeId(nodeId: string): number {
  const stage = SOP_STAGES.find((s) => s.nodes.some((n) => n.id === nodeId));
  return stage ? stage.id : 0;
}

export function stageNameForId(stageId: number): string {
  return SOP_STAGES.find((s) => s.id === stageId)?.name ?? '';
}
