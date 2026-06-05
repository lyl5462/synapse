import { useEffect, useMemo, useRef, useState } from 'react';
import { orderEfficiencyDetailData } from '@rd-view/data/mockData';
import type { OrderEfficiencyDetailView } from '@rd-view/types';
import { calcOrderEfficiencyGain } from '@rd-view/utils/orderEfficiency';

const ROW_HEIGHT = 48;
const SCROLL_VIEWPORT_HEIGHT = 200;
const PAUSE_HOVER_DELAY_MS = 120;

function EfficiencyRow({
  item,
  maxHours,
}: {
  item: OrderEfficiencyDetailView;
  maxHours: number;
}) {
  const aiWidthPct = (item.aiHours / maxHours) * 100;
  const manualWidthPct = (item.manualHours / maxHours) * 100;

  return (
    <div className="efficiency-popover-row" style={{ height: ROW_HEIGHT }}>
      <div className="efficiency-popover-name" title={item.title}>
        {item.title}
      </div>
      <div className="efficiency-popover-bar-area">
        <div className="efficiency-popover-compare">
          <div className="efficiency-popover-bar-track">
            <div
              className="efficiency-popover-compare-bar efficiency-popover-compare-bar--ai"
              style={{ width: `${aiWidthPct}%` }}
            />
          </div>
          <div className="efficiency-popover-bar-track">
            <div
              className="efficiency-popover-compare-bar efficiency-popover-compare-bar--manual"
              style={{ width: `${manualWidthPct}%` }}
            />
          </div>
        </div>
        <div className="efficiency-popover-hours">
          <span className="efficiency-popover-hours-ai">{item.aiHours}h</span>
          <span className="efficiency-popover-hours-divider">/</span>
          <span className="efficiency-popover-hours-manual">{item.manualHours}h</span>
        </div>
      </div>
      <div className="efficiency-popover-gain">
        {item.efficiencyGain > 0 ? `+${item.efficiencyGain}%` : '—'}
      </div>
    </div>
  );
}

function readTrackOffset(track: HTMLDivElement | null): number {
  if (!track) return 0;

  const transform = window.getComputedStyle(track).transform;
  if (!transform || transform === 'none') return 0;

  return Math.max(0, -new DOMMatrix(transform).m42);
}

export function EfficiencyGainPopoverContent() {
  const [paused, setPaused] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const offsetRef = useRef(0);
  const pauseTimerRef = useRef<number>();

  const sortedItems = useMemo<OrderEfficiencyDetailView[]>(() => (
    orderEfficiencyDetailData
      .map((item) => ({
        ...item,
        efficiencyGain: calcOrderEfficiencyGain(item.aiHours, item.manualHours),
      }))
      .sort((a, b) => b.efficiencyGain - a.efficiencyGain)
  ), []);

  const maxHours = useMemo(
    () => Math.max(...sortedItems.map((item) => Math.max(item.aiHours, item.manualHours)), 1),
    [sortedItems],
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
      <div className="efficiency-popover-header">工单提效明细</div>
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
            <EfficiencyRow key={`${item.id}-${index}`} item={item} maxHours={maxHours} />
          ))}
        </div>
      </div>
      <div className="efficiency-popover-formula">
        提效率 = (人工耗时 - AI耗时) / 人工耗时 × 100%
      </div>
      <div className="efficiency-popover-legend">
        <span className="efficiency-popover-legend-item">
          <span className="efficiency-popover-legend-dot efficiency-popover-legend-dot--ai" />
          AI耗时
        </span>
        <span className="efficiency-popover-legend-item">
          <span className="efficiency-popover-legend-dot efficiency-popover-legend-dot--manual" />
          人工耗时
        </span>
      </div>
    </div>
  );
}
