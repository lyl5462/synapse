import { SOP_NODES } from '@rd-view/constants/sopNodes';
import type { SopDialogueMessage, PersonRequirement, RequirementStatus, SopNodeRunStatus, WorkOrderComment, WorkOrderSopNode, WorkOrderTicket } from '@rd-view/types';

const MODELS = ['GPT-4o', 'Claude-3.5', 'DeepSeek-V3', 'GPT-4o-mini'];

const DIALOGUE_TEMPLATES: Record<string, { user: string; assistant: string }[]> = {
  analysis: [
    { user: '请梳理该需求的业务背景与验收标准。', assistant: '已整理需求范围：核心目标是优化分析模块响应速度，验收标准为 P95 < 200ms。' },
    { user: '补充风险点。', assistant: '识别到 2 项依赖风险：历史数据迁移、第三方接口限流。' },
  ],
  design: [
    { user: '输出技术方案与接口设计。', assistant: '方案采用分层缓存 + 异步预计算，接口变更已列出兼容策略。' },
  ],
  environment: [
    { user: '搭建联调环境并验证配置。', assistant: '测试环境已就绪，配置项 12 条全部校验通过。' },
  ],
  development: [
    { user: '实现核心逻辑并补充单元测试。', assistant: '已完成主流程开发，单元测试覆盖率 82%。' },
    { user: '有一处边界 case 需要人工确认。', assistant: '已标记人工介入点：并发写入时的幂等策略需您确认。' },
  ],
  review: [
    { user: '走查代码并输出问题清单。', assistant: '走查完成，发现 1 个中等缺陷、3 个优化建议，均已记录。' },
  ],
};

const OUTPUT_TEMPLATES: Record<string, WorkOrderSopNode['outputs']> = {
  analysis: [{ type: 'document', label: '需求分析文档 v1.2' }],
  design: [{ type: 'document', label: '技术设计说明' }, { type: 'artifact', label: '接口契约草案' }],
  environment: [{ type: 'artifact', label: '环境配置清单' }],
  development: [{ type: 'code', label: 'feature/analysis-opt 分支' }, { type: 'code', label: '单元测试用例 24 条' }],
  review: [{ type: 'document', label: '走查报告' }],
};

function resolveNodeRunStatus(
  ticketStatus: RequirementStatus,
  nodeStatus: RequirementStatus,
  nodeIndex: number,
): SopNodeRunStatus {
  if (nodeStatus === 'completed') return 'completed';
  if (nodeStatus === 'pending') return 'pending';
  if (ticketStatus !== 'inProgress') return 'completed';

  const modes: SopNodeRunStatus[] = ['running', 'running', 'manual', 'abnormal'];
  return modes[nodeIndex % modes.length];
}

function buildDialogues(nodeKey: string, runStatus: SopNodeRunStatus): SopDialogueMessage[] {
  const templates = DIALOGUE_TEMPLATES[nodeKey] ?? DIALOGUE_TEMPLATES.analysis;
  const base: SopDialogueMessage[] = templates.flatMap((item, idx) => [
    { role: 'user' as const, content: item.user, time: `10:${String(10 + idx * 5).padStart(2, '0')}` },
    { role: 'assistant' as const, content: item.assistant, time: `10:${String(12 + idx * 5).padStart(2, '0')}` },
  ]);

  if (runStatus === 'abnormal') {
    base.push({
      role: 'system',
      content: '节点执行异常：模型响应超时，已自动重试 2 次。',
      time: '10:48',
    });
  }
  if (runStatus === 'manual') {
    base.push({
      role: 'system',
      content: '已切换为人工介入模式，等待处理人确认后继续。',
      time: '10:52',
    });
  }
  return base;
}

function buildSopNodesForTicket(req: PersonRequirement): WorkOrderSopNode[] {
  return SOP_NODES.map((node, index) => {
    const baseNode = req.sopNodes[index];
    const status = baseNode?.status ?? 'pending';
    const runStatus = resolveNodeRunStatus(req.status, status, index);
    const hours = status === 'pending' ? 0 : (baseNode?.hours ?? node.defaultHours);
    const tokens = status === 'pending' ? 0 : Math.round(hours * 1200 * (1 + (index % 3) * 0.15));

    return {
      key: node.key,
      name: node.label,
      status,
      runStatus,
      hours,
      tokens,
      model: MODELS[index % MODELS.length],
      description: baseNode?.description ?? node.description,
      dialogues: status === 'pending' ? [] : buildDialogues(node.key, runStatus),
      outputs: status === 'completed' ? (OUTPUT_TEMPLATES[node.key] ?? []) : [],
    };
  });
}

function buildComments(req: PersonRequirement): WorkOrderComment[] {
  return [
    {
      author: req.assignee,
      time: req.createdAt,
      content: '已接单，计划按 SOP 推进。',
    },
    {
      author: '李四',
      time: '周四 15:20',
      content: `「${req.title}」请关注与现有模块的兼容性。`,
    },
  ];
}

function toIsoDate(daysAgo: number, hoursAgo = 0): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  date.setHours(date.getHours() - hoursAgo, 0, 0, 0);
  return date.toISOString();
}

export function buildWorkOrderTickets(requirements: PersonRequirement[]): WorkOrderTicket[] {
  const statusWeight: Record<RequirementStatus, number> = {
    inProgress: 0,
    pending: 1,
    completed: 2,
  };

  return [...requirements]
    .sort((a, b) => {
      const weightDiff = statusWeight[a.status] - statusWeight[b.status];
      if (weightDiff !== 0) return weightDiff;
      return a.startDay - b.startDay;
    })
    .map((req, idx) => {
      const daysAgo = 1 + (idx % 5);
      const hoursAgo = idx % 8;
      const createdAt = toIsoDate(daysAgo, hoursAgo);

      return {
        id: req.id,
        title: req.title,
        status: req.status,
        assignee: req.assignee,
        priority: req.priority,
        summary: `${req.title}：${req.description.slice(0, 36)}…`,
        content: req.description,
        createdAt,
        updatedAt: toIsoDate(Math.max(0, daysAgo - 1), (hoursAgo + 3) % 12),
        plannedEnd: req.plannedEnd,
        comments: buildComments(req),
        sopNodes: buildSopNodesForTicket(req),
      };
    });
}

export function getActiveSopNode(ticket: WorkOrderTicket): WorkOrderSopNode | undefined {
  if (ticket.status === 'pending') return undefined;
  if (ticket.status === 'completed') {
    return ticket.sopNodes[ticket.sopNodes.length - 1];
  }
  return ticket.sopNodes.find((node) => node.status === 'inProgress')
    ?? ticket.sopNodes.find((node) => node.runStatus === 'running' || node.runStatus === 'manual' || node.runStatus === 'abnormal');
}
