import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons';
import { orderCoverageDetailData } from '@rd-view/data/mockData';
import type { OrderCoverageDetailItem } from '@rd-view/types';

const ROW_HEIGHT = 40;
const SCROLL_VIEWPORT_HEIGHT = 200;
const PAUSE_HOVER_DELAY_MS = 120;

const PRIORITY_COLOR: Record<OrderCoverageDetailItem['priority'], string> = {
  高: '#F53F3F',
  中: '#FF7D00',
  低: '#86909C',
};

const PRIORITY_WEIGHT: Record<OrderCoverageDetailItem['priority'], number> = {
  高: 0,
  中: 1,
  低: 2,
};

function formatTokens(tokens: number): string {
  if (tokens >= 10000) {
    return `${(tokens / 10000).toFixed(1)}万`;
  }
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k`;
  }
  return String(tokens);
}

function CoverageOrderRow({ item }: { item: OrderCoverageDetailItem }) {
  return (
    <div className="order-coverage-row" style={{ height: ROW_HEIGHT }}>
      <span
        className="order-coverage-dot"
        style={{ backgroundColor: PRIORITY_COLOR[item.priority] }}
        title={`${item.priority}优先级`}
      />
      <div className="order-coverage-title-wrap">
        <span className="order-coverage-id">{item.id}</span>
        <span className="order-coverage-title" title={item.title}>
          {item.title}
        </span>
      </div>
      {item.covered && item.model && item.tokens != null && item.hours != null && (
        <div className="order-coverage-meta">
          <span>{item.model}</span>
          <span className="order-coverage-meta-divider">·</span>
          <span>{formatTokens(item.tokens)} Token</span>
          <span className="order-coverage-meta-divider">·</span>
          <span>{item.hours}h</span>
        </div>
      )}
      {item.covered ? (
        <CheckCircleFilled className="order-coverage-icon order-coverage-icon--covered" />
      ) : (
        <CloseCircleFilled className="order-coverage-icon order-coverage-icon--uncovered" />
      )}
    </div>
  );
}

function readTrackOffset(track: HTMLDivElement | null): number {
  if (!track) return 0;

  const transform = window.getComputedStyle(track).transform;
  if (!transform || transform === 'none') return 0;

  return Math.max(0, -new DOMMatrix(transform).m42);
}

export function OrderCoveragePopoverContent() {
  const [paused, setPaused] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const offsetRef = useRef(0);
  const pauseTimerRef = useRef<number>();

  const sortedItems = useMemo(
    () => [...orderCoverageDetailData].sort((a, b) => {
      const priorityDiff = PRIORITY_WEIGHT[a.priority] - PRIORITY_WEIGHT[b.priority];
      if (priorityDiff !== 0) return priorityDiff;
      return a.title.localeCompare(b.title, 'zh-CN');
    }),
    [],
  );

  const loopItems = useMemo(() => [...sortedItems, ...sortedItems], [sortedItems]);
  const scrollDuration = Math.max(sortedItems.length * 2.8, 16);
  const loopHeight = sortedItems.length * ROW_HEIGHT;

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
    track.style.animationDelay = `${-progress * scrollDuration}s`;
  };

  const pauseAtCurrentPosition = () => {
    const currentOffset = readTrackOffset(trackRef.current);
    offsetRef.current = currentOffset;
    applyManualOffset(currentOffset);
    setPaused(true);
  };

  const handleMouseEnter = () => {
    window.clearTimeout(pauseTimerRef.current);
    pauseTimerRef.current = window.setTimeout(pauseAtCurrentPosition, PAUSE_HOVER_DELAY_MS);
  };

  const handleMouseLeave = () => {
    window.clearTimeout(pauseTimerRef.current);

    if (paused) {
      resumeAnimation();
      setPaused(false);
    }
  };

  const handleWheel = (event: React.WheelEvent) => {
    if (!paused) return;

    event.preventDefault();
    event.stopPropagation();
    applyManualOffset(offsetRef.current + event.deltaY);
  };

  return (
    <div className="efficiency-popover">
      <div className="efficiency-popover-header">需求工单覆盖明细</div>
      <div
        className={`efficiency-popover-viewport${paused ? ' efficiency-popover-viewport--interactive' : ''}`}
        style={{ height: SCROLL_VIEWPORT_HEIGHT }}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onWheel={handleWheel}
      >
        <div
          ref={trackRef}
          className="efficiency-popover-track"
          style={{
            ['--scroll-duration' as string]: `${scrollDuration}s`,
            ['--item-height' as string]: `${ROW_HEIGHT}px`,
            ['--item-count' as string]: String(sortedItems.length),
          }}
        >
          {loopItems.map((item, index) => (
            <CoverageOrderRow key={`${item.id}-${index}`} item={item} />
          ))}
        </div>
      </div>
      <div className="efficiency-popover-formula">
        覆盖率 = 智能助手覆盖工单数 / 总工单数 × 100%
      </div>
      <div className="efficiency-popover-legend">
        <span className="efficiency-popover-legend-item">
          <CheckCircleFilled className="order-coverage-icon order-coverage-icon--covered" />
          已覆盖
        </span>
        <span className="efficiency-popover-legend-item">
          <CloseCircleFilled className="order-coverage-icon order-coverage-icon--uncovered" />
          未覆盖
        </span>
      </div>
    </div>
  );
}
