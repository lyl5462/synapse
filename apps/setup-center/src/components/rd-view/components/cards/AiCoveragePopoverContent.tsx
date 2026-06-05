import { useEffect, useMemo, useRef, useState } from 'react';
import { personAiCoverageDetailData } from '@rd-view/data/mockData';
import type { PersonAiCoverageView } from '@rd-view/types';
import { calcPersonAiCoverageRate } from '@rd-view/utils/aiCoverage';

const ROW_HEIGHT = 48;
const SCROLL_VIEWPORT_HEIGHT = 200;
const PAUSE_HOVER_DELAY_MS = 120;

function CoverageRow({
  item,
  maxOrders,
}: {
  item: PersonAiCoverageView;
  maxOrders: number;
}) {
  const aiWidthPct = (item.aiOrders / maxOrders) * 100;
  const manualWidthPct = (item.manualOrders / maxOrders) * 100;

  return (
    <div className="efficiency-popover-row efficiency-popover-row--person" style={{ height: ROW_HEIGHT }}>
      <div className="efficiency-popover-name" title={item.name}>
        {item.name}
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
          <span className="efficiency-popover-hours-ai">{item.aiOrders}单</span>
          <span className="efficiency-popover-hours-divider">/</span>
          <span className="efficiency-popover-hours-manual">{item.manualOrders}单</span>
        </div>
      </div>
      <div className="efficiency-popover-gain">{item.coverageRate}%</div>
    </div>
  );
}

function readTrackOffset(track: HTMLDivElement | null): number {
  if (!track) return 0;

  const transform = window.getComputedStyle(track).transform;
  if (!transform || transform === 'none') return 0;

  return Math.max(0, -new DOMMatrix(transform).m42);
}

export function AiCoveragePopoverContent() {
  const [paused, setPaused] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const offsetRef = useRef(0);
  const pauseTimerRef = useRef<number>();

  const sortedItems = useMemo<PersonAiCoverageView[]>(() => (
    personAiCoverageDetailData
      .map((item) => ({
        ...item,
        manualOrders: item.totalOrders - item.aiOrders,
        coverageRate: calcPersonAiCoverageRate(item.aiOrders, item.totalOrders),
      }))
      .sort((a, b) => b.coverageRate - a.coverageRate)
  ), []);

  const maxOrders = useMemo(
    () => Math.max(...sortedItems.map((item) => Math.max(item.aiOrders, item.manualOrders)), 1),
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
      <div className="efficiency-popover-header">智能助手使用率明细</div>
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
            <CoverageRow key={`${item.name}-${index}`} item={item} maxOrders={maxOrders} />
          ))}
        </div>
      </div>
      <div className="efficiency-popover-formula">
        使用率 = 智能助手处理工单数 / 总工单数 × 100%
      </div>
      <div className="efficiency-popover-legend">
        <span className="efficiency-popover-legend-item">
          <span className="efficiency-popover-legend-dot efficiency-popover-legend-dot--ai" />
          智能助手
        </span>
        <span className="efficiency-popover-legend-item">
          <span className="efficiency-popover-legend-dot efficiency-popover-legend-dot--manual" />
          人工处理
        </span>
      </div>
    </div>
  );
}
