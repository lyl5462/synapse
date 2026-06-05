import { Drawer, Divider } from 'antd';
import type { WorkOrderTicket } from '@rd-view/types';
import { formatDateTime } from '@rd-view/utils/workOrder';
import { WorkOrderSopTimeline } from './WorkOrderSopTimeline';

const ORDER_STATUS_TAG: Record<WorkOrderTicket['status'], { label: string; color: string }> = {
  pending: { label: '待处理', color: 'orange' },
  inProgress: { label: '在途', color: 'blue' },
  completed: { label: '完成', color: 'green' },
};

const PRIORITY_COLOR: Record<WorkOrderTicket['priority'], string> = {
  高: '#F53F3F',
  中: '#FF7D00',
  低: '#86909C',
};

interface WorkOrderDetailDrawerProps {
  order: WorkOrderTicket | null;
  open: boolean;
  onClose: () => void;
}

const drawerSharedProps = {
  placement: 'right' as const,
  width: 640,
  destroyOnClose: true,
  className: 'work-order-drawer',
  classNames: { body: 'work-order-drawer-body' },
  styles: { body: { paddingBottom: 56, overflowY: 'auto' as const } },
  getContainer: () => document.body,
};

export function WorkOrderDetailDrawer({ order, open, onClose }: WorkOrderDetailDrawerProps) {
  if (!order) {
    return (
      <Drawer title="工单详情" open={open} onClose={onClose} {...drawerSharedProps} />
    );
  }

  const statusTag = ORDER_STATUS_TAG[order.status];

  return (
    <Drawer
      title={(
        <div className="work-order-drawer-title">
          <span>{order.title}</span>
          <span className={`work-order-drawer-status-tag work-order-drawer-status-tag--${order.status}`}>
            {statusTag.label}
          </span>
        </div>
      )}
      open={open}
      onClose={onClose}
      {...drawerSharedProps}
    >
      <div className="work-order-drawer-section">
        <div className="work-order-drawer-meta-grid">
          <div><span className="label">工单编号</span><span>{order.id}</span></div>
          <div><span className="label">处理人</span><span>{order.assignee}</span></div>
          <div><span className="label">创建时间</span><span>{formatDateTime(order.createdAt)}</span></div>
          <div><span className="label">计划完成</span><span>{order.plannedEnd}</span></div>
          <div>
            <span className="label">优先级</span>
            <span style={{ color: PRIORITY_COLOR[order.priority], fontWeight: 600 }}>{order.priority}</span>
          </div>
          <div><span className="label">更新时间</span><span>{formatDateTime(order.updatedAt)}</span></div>
        </div>
      </div>

      <div className="work-order-drawer-section">
        <div className="work-order-drawer-section-title">工单内容</div>
        <div className="work-order-drawer-content">{order.content}</div>
      </div>

      <div className="work-order-drawer-section">
        <div className="work-order-drawer-section-title">工单评论</div>
        <div className="work-order-comment-list">
          {order.comments.map((comment) => (
            <div key={`${comment.author}-${comment.time}`} className="work-order-comment-item">
              <div className="work-order-comment-head">
                <span className="author">{comment.author}</span>
                <span className="time">{comment.time}</span>
              </div>
              <div className="work-order-comment-body">{comment.content}</div>
            </div>
          ))}
        </div>
      </div>

      <Divider style={{ margin: '16px 0' }} />

      <div className="work-order-drawer-section work-order-drawer-section--sop">
        <div className="work-order-drawer-section-title">SOP 节点</div>
        <WorkOrderSopTimeline nodes={order.sopNodes} />
      </div>
    </Drawer>
  );
}
