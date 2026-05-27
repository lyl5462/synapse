/**
 * 节点参考信息 Tab 内容：历史相似工单 / 知识库检索 / 知识图谱（演示数据）
 */
import React, { useMemo, useState } from 'react';
import { Avatar, Button, Progress, Space, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import {
  AlertCircle,
  BarChart2,
  ChevronDown,
  ChevronUp,
  Clock,
  Database,
  ExternalLink,
  FileCode2,
  GitMerge,
  Layers,
  Network,
  Ticket,
  FileText,
} from 'lucide-react';

const { Text, Link } = Typography;

interface TicketRecord {
  key: string;
  id: string;
  title: string;
  description: string;
  matchRate: number;
  type: 'bug' | 'feature';
  product: string;
  modules: string[];
  effort: string;
  devTickets: number;
  complexity: 'low' | 'medium' | 'high';
  assignee: string;
}

const SIMILAR_TICKETS: TicketRecord[] = [
  {
    key: '1',
    id: 'ISSUE-2024',
    title: '购物车计算折扣时偶发的精度丢失问题',
    description:
      '用户在结算时，购物车内含有折扣商品（如 9折、满减）时，前端展示金额与后端计算金额出现 ±0.01 元的尾差。经排查，根因为 JavaScript 浮点数精度问题，折扣率与单价相乘时未做精度截断处理。需在结算模块统一使用整数分（×100）或引入 Decimal.js 进行精确计算，并在单元测试中覆盖边界场景。',
    matchRate: 94,
    type: 'bug',
    product: '电商平台',
    modules: ['购物车', '结算'],
    effort: '3人天',
    devTickets: 4,
    complexity: 'high',
    assignee: '李明',
  },
  {
    key: '2',
    id: 'ISSUE-1988',
    title: '订单金额统计报表尾差修复',
    description:
      '财务报表在汇总当日订单总金额时，与订单明细加总结果存在最高 ¥0.5 的差异。原因为数据库聚合查询使用 FLOAT 类型字段，累计误差在大数据量下被放大。需将 order_amount 字段类型由 FLOAT 改为 DECIMAL(12,2)，并对历史数据进行回刷校正。',
    matchRate: 81,
    type: 'bug',
    product: '数据报表',
    modules: ['订单', '报表'],
    effort: '2人天',
    devTickets: 2,
    complexity: 'medium',
    assignee: '张三',
  },
  {
    key: '3',
    id: 'FEAT-3012',
    title: '支持使用大数对象处理所有的资金计算逻辑',
    description:
      '当前系统在涉及资金计算的多个模块（支付、账单、风控）中混用 number 与 string 类型，存在潜在精度风险。本需求要求引入统一的 BigDecimal 工具类，封装加减乘除与格式化方法，替换全量资金计算逻辑，并编写迁移文档，确保各模块平滑过渡，回归测试通过率 100%。',
    matchRate: 67,
    type: 'feature',
    product: '基础平台',
    modules: ['支付', '账单', '风控'],
    effort: '8人天',
    devTickets: 7,
    complexity: 'high',
    assignee: '王五',
  },
  {
    key: '4',
    id: 'ISSUE-2102',
    title: 'Redis 分布式锁在高并发续约场景下的偶发失效',
    description:
      '在双十一压测期间，发现部分秒杀订单出现了超卖现象。经日志分析，当 Redis 负载极高导致网络抖动时，Redisson 的看门狗续约机制可能因为超时而未能及时续约，导致锁提前释放。需优化续约重试策略，并增加本地二级锁作为兜底保障。',
    matchRate: 89,
    type: 'bug',
    product: '中间件',
    modules: ['缓存', '分布式锁'],
    effort: '4人天',
    devTickets: 3,
    complexity: 'high',
    assignee: '赵六',
  },
  {
    key: '5',
    id: 'FEAT-3045',
    title: '自动化对账引擎性能优化与索引重建',
    description:
      '随着日订单量突破千万级，当前的对账任务耗时从 2小时增加到了 6小时，影响了次日的报表生成。本方案计划将单线程对账升级为基于分片的并行对账模式，并对核心流水表进行分区处理及覆盖索引优化，目标将耗时降低至 1.5小时以内。',
    matchRate: 78,
    type: 'feature',
    product: '支付结算',
    modules: ['对账', '性能'],
    effort: '5人天',
    devTickets: 5,
    complexity: 'medium',
    assignee: '陈七',
  },
];

function getMatchColor(rate: number) {
  if (rate >= 90) return '#34d399';
  if (rate >= 70) return '#60a5fa';
  return '#fb923c';
}

function getMatchBg(rate: number) {
  if (rate >= 90) return 'rgba(52, 211, 153, 0.12)';
  if (rate >= 70) return 'rgba(96, 165, 250, 0.12)';
  return 'rgba(251, 146, 60, 0.12)';
}

function getMatchBorder(rate: number) {
  if (rate >= 90) return 'rgba(52, 211, 153, 0.35)';
  if (rate >= 70) return 'rgba(96, 165, 250, 0.35)';
  return 'rgba(251, 146, 60, 0.35)';
}

const complexityConfig: Record<string, { label: string; color: string; bg: string; border: string }> = {
  low: { label: '低', color: '#86efac', bg: 'rgba(34, 197, 94, 0.12)', border: 'rgba(34, 197, 94, 0.3)' },
  medium: { label: '中', color: '#fde68a', bg: 'rgba(234, 179, 8, 0.12)', border: 'rgba(234, 179, 8, 0.3)' },
  high: { label: '高', color: '#fca5a5', bg: 'rgba(239, 68, 68, 0.12)', border: 'rgba(239, 68, 68, 0.3)' },
};

function ExpandedDescription({ description }: { description: string }) {
  return (
    <div
      style={{
        margin: 0,
        padding: '10px 16px 10px 44px',
        background: 'rgba(99, 102, 241, 0.05)',
        borderTop: '1px solid rgba(99, 102, 241, 0.15)',
        borderBottom: '1px solid rgba(51, 65, 85, 0.3)',
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <div
          style={{
            marginTop: 1,
            flexShrink: 0,
            width: 18,
            height: 18,
            borderRadius: 4,
            background: 'rgba(99, 102, 241, 0.18)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <FileCode2 size={11} color="#a5b4fc" />
        </div>
        <div>
          <Text style={{ fontSize: 11, color: '#64748b', display: 'block', marginBottom: 4 }}>需求描述</Text>
          <Text style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.7 }}>{description}</Text>
        </div>
      </div>
    </div>
  );
}

export function SimilarTicketsTab() {
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  const toggleExpand = (key: string) =>
    setExpandedKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const sortedTickets = useMemo(
    () => [...SIMILAR_TICKETS].sort((a, b) => b.matchRate - a.matchRate),
    [],
  );

  const total = sortedTickets.length;
  const featureCount = sortedTickets.filter((t) => t.type === 'feature').length;
  const bugCount = total - featureCount;
  const moduleCount: Record<string, number> = {};
  sortedTickets.forEach((t) => t.modules.forEach((m) => { moduleCount[m] = (moduleCount[m] || 0) + 1; }));
  const topModule = Object.entries(moduleCount).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '-';

  const summaryStats = [
    {
      icon: <BarChart2 size={12} color="#a78bfa" />,
      label: '相似工单',
      value: `${total} 条`,
      color: '#c4b5fd',
      bg: 'rgba(139,92,246,0.08)',
      border: 'rgba(139,92,246,0.2)',
    },
    {
      icon: <AlertCircle size={12} color="#f87171" />,
      label: '需求 / 故障',
      value: `${featureCount} / ${bugCount}`,
      color: '#fca5a5',
      bg: 'rgba(239,68,68,0.07)',
      border: 'rgba(239,68,68,0.18)',
    },
    {
      icon: <Layers size={12} color="#60a5fa" />,
      label: '最关联模块',
      value: topModule,
      color: '#93c5fd',
      bg: 'rgba(59,130,246,0.07)',
      border: 'rgba(59,130,246,0.18)',
    },
    {
      icon: <Clock size={12} color="#34d399" />,
      label: '工作量预估',
      value: '2 人天',
      color: '#6ee7b7',
      bg: 'rgba(52,211,153,0.07)',
      border: 'rgba(52,211,153,0.18)',
    },
  ];

  const columns: TableColumnsType<TicketRecord> = [
    {
      title: '单号',
      dataIndex: 'id',
      key: 'id',
      width: 118,
      render: (id: string, record) => (
        <Space size={5} align="center">
          {record.type === 'bug' ? (
            <AlertCircle size={11} color="#ef4444" />
          ) : (
            <GitMerge size={11} color="#3b82f6" />
          )}
          <Link style={{ color: 'var(--muted)', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{id}</Link>
        </Space>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (title: string, record) => {
        const expanded = expandedKeys.includes(record.key);
        return (
          <div
            style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', userSelect: 'none' }}
            onClick={() => toggleExpand(record.key)}
          >
            <Text
              style={{
                fontSize: 12,
                color: expanded ? 'var(--primary)' : 'var(--muted)',
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                transition: 'color 0.15s',
              }}
            >
              {title}
            </Text>
            <span
              style={{
                flexShrink: 0,
                color: expanded ? 'var(--primary)' : 'var(--muted2)',
                transition: 'color 0.15s',
              }}
            >
              {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </span>
          </div>
        );
      },
    },
    {
      title: '产品',
      dataIndex: 'product',
      key: 'product',
      width: 80,
      render: (v: string) => <Text style={{ color: 'var(--muted)', fontSize: 11 }}>{v}</Text>,
    },
    {
      title: '模块',
      dataIndex: 'modules',
      key: 'modules',
      width: 130,
      render: (mods: string[]) => (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
          {mods.map((m) => (
            <Tag
              key={m}
              style={{
                background: 'rgba(99,102,241,0.12)',
                color: '#a5b4fc',
                border: '1px solid rgba(99,102,241,0.3)',
                fontSize: 10,
                marginInlineEnd: 0,
                padding: '0 5px',
                lineHeight: '18px',
              }}
            >
              {m}
            </Tag>
          ))}
        </div>
      ),
    },
    {
      title: '匹配度',
      dataIndex: 'matchRate',
      key: 'matchRate',
      width: 108,
      render: (rate: number) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: 40,
              height: 18,
              borderRadius: 10,
              background: getMatchBg(rate),
              border: `1px solid ${getMatchBorder(rate)}`,
              padding: '0 6px',
            }}
          >
            <Text
              style={{
                color: getMatchColor(rate),
                fontSize: 11,
                fontFamily: 'ui-monospace, monospace',
                fontWeight: 600,
              }}
            >
              {rate}%
            </Text>
          </div>
          <Progress
            percent={rate}
            showInfo={false}
            size={[40, 3]}
            strokeColor={getMatchColor(rate)}
            railColor="var(--line)"
            style={{ marginBottom: 0 }}
          />
        </div>
      ),
    },
    {
      title: '工作量',
      dataIndex: 'effort',
      key: 'effort',
      width: 66,
      render: (v: string) => (
        <Text style={{ color: 'var(--text)', fontSize: 11, fontFamily: 'ui-monospace, monospace' }}>{v}</Text>
      ),
    },
    {
      title: '研发单',
      dataIndex: 'devTickets',
      key: 'devTickets',
      width: 60,
      render: (count: number) => (
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: 26,
            height: 18,
            borderRadius: 10,
            background: 'rgba(56,189,248,0.1)',
            border: '1px solid rgba(56,189,248,0.28)',
            padding: '0 7px',
          }}
        >
          <Text
            style={{
              color: '#7dd3fc',
              fontSize: 11,
              fontFamily: 'ui-monospace, monospace',
              fontWeight: 600,
            }}
          >
            {count}
          </Text>
        </div>
      ),
    },
    {
      title: '复杂度',
      dataIndex: 'complexity',
      key: 'complexity',
      width: 60,
      render: (v: string) => {
        const cfg = complexityConfig[v] ?? complexityConfig.medium;
        return (
          <Tag
            style={{
              background: cfg.bg,
              color: cfg.color,
              border: `1px solid ${cfg.border}`,
              fontSize: 10,
              marginInlineEnd: 0,
              padding: '0 7px',
            }}
          >
            {cfg.label}
          </Tag>
        );
      },
    },
    {
      title: '负责人',
      dataIndex: 'assignee',
      key: 'assignee',
      width: 82,
      render: (name: string) => (
        <Space size={6} align="center">
          <Avatar
            size={18}
            style={{
              background: 'var(--bg-subtle)',
              fontSize: 10,
              fontWeight: 600,
              border: '1px solid var(--line)',
              color: 'var(--muted)',
            }}
          >
            {name.charAt(0)}
          </Avatar>
          <Text style={{ color: 'var(--muted)', fontSize: 11 }}>{name}</Text>
        </Space>
      ),
    },
  ];

  return (
    <div className="req-analysis-similar-tickets-pane pt-3">
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 5,
          padding: '0 4px 12px',
          flexShrink: 0,
        }}
      >
        {summaryStats.map((s) => (
          <div
            key={s.label}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
              padding: '6px 9px',
              background: s.bg,
              border: `1px solid ${s.border}`,
              borderRadius: 7,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {s.icon}
              <Text style={{ fontSize: 10, color: 'var(--muted)' }}>{s.label}</Text>
            </div>
            <Text
              style={{
                fontSize: 12,
                color: s.color,
                fontWeight: 600,
                fontFamily: 'ui-monospace, monospace',
              }}
            >
              {s.value}
            </Text>
          </div>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 8,
          paddingLeft: 4,
          paddingRight: 4,
          flexShrink: 0,
        }}
      >
        <Space size={8} align="center">
          <Database size={13} color="#818cf8" />
          <Text style={{ color: 'var(--text)', fontWeight: 600, fontSize: 13 }}>历史相似工单及明细</Text>
        </Space>
        <Button
          type="link"
          size="small"
          style={{
            color: '#60a5fa',
            fontSize: 11,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: 0,
          }}
          icon={<ExternalLink size={10} />}
          iconPlacement="end"
        >
          查看完整看板
        </Button>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--panel2)',
          borderRadius: 8,
          border: '1px solid var(--line)',
        }}
        className="custom-scrollbar rdMeetingSimilarTable"
      >
        <Table<TicketRecord>
          dataSource={sortedTickets}
          columns={columns}
          rowKey="key"
          pagination={false}
          size="small"
          style={{ background: 'transparent' }}
          expandable={{
            expandedRowKeys: expandedKeys,
            expandedRowRender: (record) => <ExpandedDescription description={record.description} />,
            showExpandColumn: false,
          }}
          onRow={() => ({ style: { cursor: 'default' } })}
        />
      </div>
    </div>
  );
}

export function KnowledgeBaseTab() {
  return (
    <div className="space-y-3 pt-3">
      <div className="rounded-xl border border-emerald-900/30 bg-emerald-950/20 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="rounded-full border border-emerald-700/40 bg-emerald-900/40 px-2 py-0.5 text-[10px] text-emerald-400">
            研发规范库
          </span>
          <span className="font-mono text-xs font-semibold text-emerald-400">置信度 100%</span>
        </div>
        <div className="mb-1.5 text-sm font-medium text-foreground">Java 后端编码规范 § 4.2</div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          命中条目：严禁使用{' '}
          <code className="rounded bg-muted/60 px-1 text-muted-foreground">Double/Float</code>{' '}
          进行金额计算。所有 DTO 和 Entity 必须使用 Decimal 类型。
        </p>
      </div>
      <div className="rounded-xl border border-purple-900/30 bg-purple-950/20 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="rounded-full border border-purple-700/40 bg-purple-900/40 px-2 py-0.5 text-[10px] text-purple-400">
            产品文档 (RAG)
          </span>
          <span className="font-mono text-xs font-semibold text-purple-400">匹配度 76%</span>
        </div>
        <div className="mb-1.5 text-sm font-medium text-foreground">
          AI 工单路由系统 · 产品需求规格说明书 v2.1
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          引用章节：§ 3.2 智能分发逻辑 · 确认路由策略需支持规则引擎 + ML 双轨，延迟 SLA &lt; 200ms，吞吐量 ≥
          5000 TPS。
        </p>
      </div>
    </div>
  );
}

export function KnowledgeGraphTab() {
  return (
    <div className="pt-3">
      <div className="space-y-4 rounded-xl border border-border/50 bg-muted/30 p-4">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_6px_rgba(99,102,241,0.8)]" />
          <span className="text-sm text-foreground/90">正在构建需求实体关联拓扑...</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: '关联服务', value: 'RoutingService' },
            { label: '影响模块', value: 'TicketFlow' },
            { label: '涉及数据', value: 'PriorityQueue' },
          ].map((item) => (
            <div key={item.label} className="rounded-lg border border-border bg-muted p-3">
              <div className="mb-1 text-[10px] text-muted-foreground">{item.label}</div>
              <div className="text-sm font-semibold text-foreground">{item.value}</div>
            </div>
          ))}
        </div>
        <div className="ml-1 space-y-2 border-l-2 border-dashed border-indigo-900/40 pl-4">
          <p className="text-xs text-indigo-400">
            推理路径: Requirement → TicketEntity → PriorityType → MLRouter
          </p>
          <p className="text-xs text-muted-foreground">
            检测到隐性依赖: 分发引擎(DispatchEngine) 依赖当前路由结果，建议同步检查。
          </p>
        </div>
      </div>
    </div>
  );
}

export function similarTicketsTabLabel() {
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <Ticket className="h-3 w-3" /> 历史相似工单
    </span>
  );
}

export function knowledgeBaseTabLabel() {
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <FileText className="h-3 w-3" /> 知识库检索
    </span>
  );
}

export function knowledgeGraphTabLabel() {
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <Network className="h-3 w-3" /> 知识图谱
    </span>
  );
}
