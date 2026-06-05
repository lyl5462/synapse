import { useState } from 'react';
import {
  FileTextOutlined,
  CodeOutlined,
  FolderOutlined,
  RobotOutlined,
  UserOutlined,
  RightOutlined,
  DownOutlined,
} from '@ant-design/icons';
import type { SopDialogueMessage, SopNodeRunStatus, WorkOrderSopNode } from '@rd-view/types';

const RUN_STATUS_CONFIG: Record<SopNodeRunStatus, { label: string; color: string }> = {
  running: { label: '运行中', color: 'processing' },
  abnormal: { label: '异常', color: 'error' },
  manual: { label: '人工介入', color: 'warning' },
  completed: { label: '已完成', color: 'success' },
  pending: { label: '未开始', color: 'default' },
};

function SopRunStatusBadge({ status }: { status: SopNodeRunStatus }) {
  const cfg = RUN_STATUS_CONFIG[status];
  return (
    <span className={`work-order-sop-status-tag work-order-sop-status-tag--${status}`}>
      {cfg.label}
    </span>
  );
}

type SopNodeTone = 'success' | 'error' | 'pending';

function getSopNodeTone(node: WorkOrderSopNode): SopNodeTone {
  if (node.runStatus === 'abnormal') return 'error';
  if (node.runStatus === 'completed' || node.status === 'completed') return 'success';
  return 'pending';
}

function OutputIcon({ type }: { type: WorkOrderSopNode['outputs'][0]['type'] }) {
  if (type === 'code') return <CodeOutlined />;
  if (type === 'document') return <FileTextOutlined />;
  return <FolderOutlined />;
}

function DialogueBubble({ message }: { message: SopDialogueMessage }) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  if (isSystem) {
    return (
      <div className="work-order-chat work-order-chat--system">
        <div className="work-order-chat-bubble work-order-chat-bubble--system">{message.content}</div>
      </div>
    );
  }

  return (
    <div className={`work-order-chat work-order-chat--${message.role}`}>
      <div className="work-order-chat-meta">
        {isUser ? <UserOutlined /> : <RobotOutlined />}
        <span>{isUser ? '处理人' : '智能助手'}</span>
        <span>{message.time}</span>
      </div>
      <div className={`work-order-chat-bubble work-order-chat-bubble--${message.role}`}>
        {message.content}
      </div>
    </div>
  );
}

function SopNodeBlock({ node, isLast }: { node: WorkOrderSopNode; isLast: boolean }) {
  const [dialogueOpen, setDialogueOpen] = useState(false);
  const nodeTone = getSopNodeTone(node);
  const hasDialogues = node.dialogues.length > 0;

  return (
    <div className={`work-order-sop-node work-order-sop-node--${nodeTone}${isLast ? '' : ' work-order-sop-node--connected'}`}>
      <div className={`work-order-sop-node-body work-order-sop-node-body--${nodeTone}`}>
        <div className="work-order-sop-node-header">
          <div className="work-order-sop-node-title-row">
            <span className="work-order-sop-node-name">{node.name}</span>
            <div className="work-order-sop-node-tags">
              <SopRunStatusBadge status={node.runStatus} />
            </div>
          </div>
          <div className="work-order-sop-node-stats">
            <div className="work-order-sop-stat">
              <span className="work-order-sop-stat-label">耗时</span>
              <span className="work-order-sop-stat-value">{node.hours}h</span>
            </div>
            <div className="work-order-sop-stat">
              <span className="work-order-sop-stat-label">Token</span>
              <span className="work-order-sop-stat-value">{node.tokens.toLocaleString()}</span>
            </div>
            <div className="work-order-sop-stat">
              <span className="work-order-sop-stat-label">模型</span>
              <span className="work-order-sop-stat-value">{node.model}</span>
            </div>
          </div>
        </div>

        <div className="work-order-sop-node-desc">{node.description}</div>

        {node.outputs.length > 0 && (
          <div className="work-order-sop-outputs">
            {node.outputs.map((output) => (
              <span key={output.label} className="work-order-sop-output">
                <OutputIcon type={output.type} />
                {output.label}
              </span>
            ))}
          </div>
        )}

        {hasDialogues && (
          <div className="work-order-sop-dialogues-wrap">
            <button
              type="button"
              className="work-order-sop-dialogues-toggle"
              onClick={() => setDialogueOpen((open) => !open)}
              aria-expanded={dialogueOpen}
            >
              <span className="work-order-sop-dialogues-toggle-left">
                {dialogueOpen ? <DownOutlined /> : <RightOutlined />}
                <span>交互过程</span>
              </span>
              <span className="work-order-sop-dialogues-count">{node.dialogues.length} 条</span>
            </button>
            {dialogueOpen && (
              <div className="work-order-sop-dialogues">
                {node.dialogues.map((message, idx) => (
                  <DialogueBubble key={`${node.key}-${idx}`} message={message} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface WorkOrderSopTimelineProps {
  nodes: WorkOrderSopNode[];
}

export function WorkOrderSopTimeline({ nodes }: WorkOrderSopTimelineProps) {
  const visibleNodes = nodes.filter((node) => node.status !== 'pending');

  if (visibleNodes.length === 0) {
    return (
      <div className="work-order-sop-empty">暂无已开始的 SOP 节点</div>
    );
  }

  return (
    <div className="work-order-sop-timeline">
      {visibleNodes.map((node, index) => (
        <SopNodeBlock key={node.key} node={node} isLast={index === visibleNodes.length - 1} />
      ))}
    </div>
  );
}

export { RUN_STATUS_CONFIG };
