import { useEffect, useMemo, useRef, useState } from 'react';
import { Card, Tag } from 'antd';
import { UnorderedListOutlined } from '@ant-design/icons';
import { workOrderTicketData } from '@rd-view/data/mockData';
import { getActiveSopNode } from '@rd-view/data/buildWorkOrderTickets';
import type { RequirementStatus, WorkOrderTicket } from '@rd-view/types';
import { CURRENT_USER_NAME, PERSON_COLORS } from '@rd-view/types';
import { formatElapsedSince } from '@rd-view/utils/workOrder';
import { WorkOrderDetailDrawer } from './WorkOrderDetailDrawer';
import { RUN_STATUS_CONFIG } from './WorkOrderSopTimeline';
import { WorkOrderEmojiPicker, type EmojiReaction } from './WorkOrderEmojiPicker';
import { chartCardTitleIconStyle, chartCardTitleStyle, chartCardTitleTextStyle, dashboardCardStyle } from '@rd-view/constants/dashboardTheme';

const ORDER_STATUS_TAG: Record<RequirementStatus, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'orange' },
  inProgress: { label: '在途', color: 'blue' },
  completed: { label: '完成', color: 'green' },
};

const PRIORITY_COLOR: Record<WorkOrderTicket['priority'], string> = {
  高: '#F53F3F',
  中: '#FF7D00',
  低: '#86909C',
};

const ITEM_HEIGHT = 156;
const SCROLL_SECONDS_PER_ITEM = 3.6;
const PAUSE_HOVER_DELAY_MS = 120;

type WorkOrderCardTone = 'success' | 'error' | 'default';

function getWorkOrderCardTone(item: WorkOrderTicket): WorkOrderCardTone {
  const activeNode = getActiveSopNode(item);
  if (activeNode?.runStatus === 'abnormal') return 'error';
  if (item.status === 'completed') return 'success';
  return 'default';
}

function readTrackOffset(track: HTMLDivElement | null): number {
  if (!track) return 0;

  const transform = window.getComputedStyle(track).transform;
  if (!transform || transform === 'none') return 0;

  return Math.max(0, -new DOMMatrix(transform).m42);
}

function WorkOrderRow({
  item,
  emojiReaction,
  onOpen,
  onEmojiSelect,
  onEmojiPickerOpenChange,
}: {
  item: WorkOrderTicket;
  emojiReaction?: EmojiReaction;
  onOpen: (order: WorkOrderTicket) => void;
  onEmojiSelect: (orderId: string, emoji: string) => void;
  onEmojiPickerOpenChange: (open: boolean) => void;
}) {
  const avatarColor = PERSON_COLORS[item.assignee] ?? '#165DFF';
  const statusTag = ORDER_STATUS_TAG[item.status];
  const activeNode = getActiveSopNode(item);
  const cardTone = getWorkOrderCardTone(item);
  const elapsedLabel = item.status === 'completed' ? '总耗时' : '至今';
  const elapsedValue = formatElapsedSince(item.createdAt);

  return (
    <div className="work-scroll-item work-order-card-wrap" style={{ height: ITEM_HEIGHT }}>
      <div className={`work-order-card work-order-card--${cardTone}`}>
        <button type="button" className="work-order-card-main" onClick={() => onOpen(item)}>
          <div
            className="work-scroll-avatar"
            style={{ background: `${avatarColor}18`, color: avatarColor, borderColor: `${avatarColor}40` }}
          >
            {item.assignee.slice(-1)}
          </div>
          <div className="work-scroll-body">
            <div className="work-scroll-header">
              <span className="work-scroll-name">{item.assignee}</span>
              <Tag bordered={false} color={statusTag.color} style={{ margin: 0, fontSize: 10, lineHeight: '18px' }}>
                {statusTag.label}
              </Tag>
            </div>

            <div className="work-order-row-title">
              <span className="work-order-row-id">{item.id}</span>
              <span className="work-order-row-name">{item.title}</span>
            </div>

            <div className="work-order-row-meta">
              <span>{elapsedLabel} {elapsedValue}</span>
              <span className="work-scroll-dot">·</span>
              <span style={{ color: PRIORITY_COLOR[item.priority] }}>{item.priority}优先级</span>
            </div>

            <div className="work-order-row-summary">{item.summary}</div>

            <div className="work-order-row-status-line">
              {(item.status === 'inProgress' || item.status === 'completed') && activeNode ? (
                <>
                  <Tag bordered={false} color={statusTag.color} style={{ margin: 0, fontSize: 10 }}>
                    工单{statusTag.label}
                  </Tag>
                  <Tag bordered={false} color={RUN_STATUS_CONFIG[activeNode.runStatus].color} style={{ margin: 0, fontSize: 10 }}>
                    {RUN_STATUS_CONFIG[activeNode.runStatus].label} · {activeNode.name}
                  </Tag>
                </>
              ) : null}
            </div>
          </div>
        </button>

        <WorkOrderEmojiPicker
          value={emojiReaction}
          onSelect={(emoji) => onEmojiSelect(item.id, emoji)}
          onOpenChange={onEmojiPickerOpenChange}
        />
      </div>
    </div>
  );
}

export function ScrollChartPanel() {
  const [interactive, setInteractive] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<WorkOrderTicket | null>(null);
  const [orderEmojis, setOrderEmojis] = useState<Record<string, EmojiReaction>>({});
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const offsetRef = useRef(0);
  const pauseTimerRef = useRef<number>();
  const interactiveRef = useRef(false);
  const drawerOpenRef = useRef(false);
  const emojiPickerOpenRef = useRef(false);
  const viewportHoveredRef = useRef(false);

  const loopItems = useMemo(() => [...workOrderTicketData, ...workOrderTicketData], []);
  const durationSec = useMemo(
    () => Math.max(workOrderTicketData.length * SCROLL_SECONDS_PER_ITEM, 30),
    [],
  );
  const loopHeight = workOrderTicketData.length * ITEM_HEIGHT;

  useEffect(() => () => {
    window.clearTimeout(pauseTimerRef.current);
  }, []);

  const normalizeOffset = (offset: number) => {
    if (loopHeight <= 0) return 0;
    return ((offset % loopHeight) + loopHeight) % loopHeight;
  };

  const applyManualOffset = (offset: number) => {
    const track = trackRef.current;
    if (!track) return;

    offsetRef.current = normalizeOffset(offset);
    track.style.animation = 'none';
    track.style.animationDelay = '';
    track.style.transform = `translate3d(0, -${offsetRef.current}px, 0)`;
  };

  const resumeAnimation = () => {
    const track = trackRef.current;
    if (!track || loopHeight <= 0) return;

    offsetRef.current = normalizeOffset(offsetRef.current);
    const progress = offsetRef.current / loopHeight;

    track.style.transform = '';
    track.style.animation = '';
    track.style.animationDelay = `${-progress * durationSec}s`;
    interactiveRef.current = false;
    setInteractive(false);
  };

  const pauseAtCurrentPosition = () => {
    const currentOffset = readTrackOffset(trackRef.current);
    offsetRef.current = currentOffset;
    applyManualOffset(currentOffset);
    interactiveRef.current = true;
    setInteractive(true);
  };

  const isPointerOverViewport = () => {
    const viewport = viewportRef.current;
    if (!viewport) return viewportHoveredRef.current;

    return viewport.matches(':hover');
  };

  const tryResumeScroll = () => {
    if (drawerOpenRef.current || emojiPickerOpenRef.current) return;
    if (!interactiveRef.current) return;
    if (isPointerOverViewport()) return;

    resumeAnimation();
  };

  const handleMouseEnter = () => {
    viewportHoveredRef.current = true;
    window.clearTimeout(pauseTimerRef.current);
    pauseTimerRef.current = window.setTimeout(pauseAtCurrentPosition, PAUSE_HOVER_DELAY_MS);
  };

  const handleMouseLeave = () => {
    viewportHoveredRef.current = false;
    window.clearTimeout(pauseTimerRef.current);
    tryResumeScroll();
  };

  const handleWheel = (event: React.WheelEvent) => {
    if (!interactiveRef.current || emojiPickerOpenRef.current) return;

    const target = event.target as HTMLElement;
    if (target.closest('.work-order-emoji-popover, .work-order-emoji-panel')) return;

    event.preventDefault();
    event.stopPropagation();
    applyManualOffset(offsetRef.current + event.deltaY);
  };

  const handleEmojiPickerOpenChange = (open: boolean) => {
    emojiPickerOpenRef.current = open;
    setEmojiPickerOpen(open);

    if (open) {
      window.clearTimeout(pauseTimerRef.current);
      pauseAtCurrentPosition();
      return;
    }

    window.requestAnimationFrame(() => tryResumeScroll());
  };

  const handleOpenOrder = (order: WorkOrderTicket) => {
    window.clearTimeout(pauseTimerRef.current);
    pauseAtCurrentPosition();
    drawerOpenRef.current = true;
    setSelectedOrder(order);
    setDrawerOpen(true);
  };

  const handleCloseDrawer = () => {
    drawerOpenRef.current = false;
    setDrawerOpen(false);
    setSelectedOrder(null);
    window.requestAnimationFrame(() => tryResumeScroll());
  };

  const handleEmojiSelect = (orderId: string, emoji: string) => {
    setOrderEmojis((prev) => ({
      ...prev,
      [orderId]: { emoji, personName: CURRENT_USER_NAME },
    }));
  };

  return (
    <>
      <Card
        className={`dashboard-card work-scroll-panel${interactive ? ' work-scroll-interactive' : ''}${emojiPickerOpen ? ' work-scroll-panel--emoji-open' : ''}`}
        title={(
          <div style={chartCardTitleStyle}>
            <UnorderedListOutlined style={chartCardTitleIconStyle} />
            <span style={chartCardTitleTextStyle}>工作内容</span>
          </div>
        )}
        styles={{ body: { padding: 0, flex: 1, minHeight: 0, overflow: 'hidden' } }}
        style={{ ...dashboardCardStyle, minHeight: 0, overflow: 'hidden' }}
      >
        <div
          ref={viewportRef}
          className={`work-scroll-viewport${interactive ? ' work-scroll-viewport--interactive' : ''}`}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
          onWheel={handleWheel}
        >
          <div
            ref={trackRef}
            className="work-scroll-track"
            style={{
              ['--scroll-duration' as string]: `${durationSec}s`,
              ['--item-height' as string]: `${ITEM_HEIGHT}px`,
              ['--item-count' as string]: String(workOrderTicketData.length),
            }}
          >
            {loopItems.map((item, index) => (
              <WorkOrderRow
                key={`${item.id}-${index}`}
                item={item}
                emojiReaction={orderEmojis[item.id]}
                onOpen={handleOpenOrder}
                onEmojiSelect={handleEmojiSelect}
                onEmojiPickerOpenChange={handleEmojiPickerOpenChange}
              />
            ))}
          </div>
        </div>
      </Card>

      <WorkOrderDetailDrawer
        order={selectedOrder}
        open={drawerOpen}
        onClose={handleCloseDrawer}
      />
    </>
  );
}
