/**
 * 方案评审 · 影响评估：按函数级方案文档解析的 sections 原样展示（标题 + 表格列/行）。
 */
import React, { useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  GitMerge,
  Layers,
  Palette,
  Settings2,
  Shield,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';

import type {
  SolutionReviewImpactAssessment,
  SolutionReviewImpactSection,
} from '../../../api/meetingRoomService';

type Accent = 'sky' | 'violet' | 'amber' | 'rose' | 'emerald' | 'cyan' | 'fuchsia';

export interface ParsedImpactSection {
  id: string;
  title: string;
  heading?: string;
  short: string;
  icon: LucideIcon;
  accent: Accent;
  headers: string[];
  rows: Record<string, string>[];
}

const ACCENT_BAR: Record<Accent, string> = {
  sky: 'from-sky-400 to-cyan-500',
  violet: 'from-violet-400 to-purple-500',
  amber: 'from-amber-400 to-orange-500',
  rose: 'from-rose-400 to-red-500',
  emerald: 'from-emerald-400 to-teal-500',
  cyan: 'from-cyan-400 to-blue-500',
  fuchsia: 'from-fuchsia-400 to-pink-500',
};

const ACCENT_CHIP: Record<Accent, string> = {
  sky: 'bg-sky-500/15 text-sky-200 border-sky-500/35',
  violet: 'bg-violet-500/15 text-violet-200 border-violet-500/35',
  amber: 'bg-amber-500/15 text-amber-200 border-amber-500/35',
  rose: 'bg-rose-500/15 text-rose-200 border-rose-500/35',
  emerald: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/35',
  cyan: 'bg-cyan-500/15 text-cyan-200 border-cyan-500/35',
  fuchsia: 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/35',
};

const ACCENT_ICON_RING: Record<Accent, string> = {
  sky: 'from-sky-500/25 to-cyan-500/10 border-sky-500/40 text-sky-300',
  violet: 'from-violet-500/25 to-purple-500/10 border-violet-500/40 text-violet-300',
  amber: 'from-amber-500/25 to-orange-500/10 border-amber-500/40 text-amber-300',
  rose: 'from-rose-500/25 to-red-500/10 border-rose-500/40 text-rose-300',
  emerald: 'from-emerald-500/25 to-teal-500/10 border-emerald-500/40 text-emerald-300',
  cyan: 'from-cyan-500/25 to-blue-500/10 border-cyan-500/40 text-cyan-300',
  fuchsia: 'from-fuchsia-500/25 to-pink-500/10 border-fuchsia-500/40 text-fuchsia-300',
};

function styleForTitle(title: string): { short: string; icon: LucideIcon; accent: Accent } {
  const t = title.trim();
  if (t.includes('性能')) return { short: '性能', icon: Activity, accent: 'sky' };
  if (t.includes('功能')) return { short: '功能', icon: Layers, accent: 'violet' };
  if (t.includes('配置')) return { short: '配置', icon: Settings2, accent: 'amber' };
  if (t.includes('升级') || t.includes('风险')) return { short: '升级', icon: AlertTriangle, accent: 'rose' };
  if (t.includes('安全')) return { short: '安全', icon: Shield, accent: 'emerald' };
  if (t.includes('兼容')) return { short: '兼容', icon: GitMerge, accent: 'cyan' };
  if (/UI|UE|界面/i.test(t)) return { short: '体验', icon: Palette, accent: 'fuchsia' };
  const short = t.length > 8 ? `${t.slice(0, 8)}…` : t || '影响';
  return { short, icon: Layers, accent: 'amber' };
}

/** 按文档表格列顺序保留表头 */
export function headersFromParsedRows(rows: Record<string, string>[]): string[] {
  const order: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    for (const k of Object.keys(row)) {
      const h = k.trim();
      if (!h || seen.has(h)) continue;
      seen.add(h);
      order.push(h);
    }
  }
  return order;
}

function legacyDictToSections(impact: SolutionReviewImpactAssessment): SolutionReviewImpactSection[] {
  const labels: Record<string, string> = {
    performance: '性能影响分析',
    functional: '功能影响分析',
    config: '配置变更说明',
    upgrade_risk: '升级风险',
    security: '安全影响',
    compatibility: '兼容性影响',
    ui_ue: 'UI/UE 设计',
  };
  const out: SolutionReviewImpactSection[] = [];
  for (const [key, title] of Object.entries(labels)) {
    const rows = impact[key as keyof SolutionReviewImpactAssessment];
    if (Array.isArray(rows) && rows.length > 0) {
      out.push({ title, rows });
    }
  }
  return out;
}

export function parseImpactSections(
  impact: SolutionReviewImpactAssessment | null | undefined,
): ParsedImpactSection[] {
  if (!impact) return [];

  const rawSections =
    impact.sections && impact.sections.length > 0
      ? impact.sections
      : legacyDictToSections(impact);

  const out: ParsedImpactSection[] = [];
  for (let i = 0; i < rawSections.length; i += 1) {
    const sec = rawSections[i];
    const title = (sec.title || '').trim();
    const rows = Array.isArray(sec.rows) ? sec.rows : [];
    if (!title || !rows.length) continue;
    const headers = headersFromParsedRows(rows);
    if (!headers.length) continue;
    const visual = styleForTitle(title);
    out.push({
      id: `impact-${i}-${title.slice(0, 24)}`,
      title,
      heading: sec.heading,
      short: visual.short,
      icon: visual.icon,
      accent: visual.accent,
      headers,
      rows,
    });
  }
  return out;
}

export function buildImpactSummary(sections: ParsedImpactSection[]): string {
  if (!sections.length) return '';
  const total = sections.reduce((n, s) => n + s.rows.length, 0);
  const names = sections.map((s) => s.short);
  if (names.length === 1) {
    return `该方案在${names[0]}方面产生影响，共 ${total} 条评估记录`;
  }
  if (names.length === 2) {
    return `该方案在${names[0]}与${names[1]}等方面产生影响，共 ${total} 条评估记录`;
  }
  const head = names.slice(0, -1).join('、');
  const tail = names[names.length - 1];
  return `该方案在${head}及${tail}等 ${names.length} 个维度产生影响，共 ${total} 条评估记录`;
}

function severityClass(value: string): string {
  const v = value.trim();
  if (/^高|严重|critical/i.test(v)) return 'rd-impact-cell--high';
  if (/^中|medium/i.test(v)) return 'rd-impact-cell--mid';
  if (/^低|轻微|low/i.test(v)) return 'rd-impact-cell--low';
  return '';
}

const ImpactDataTable: React.FC<{ headers: string[]; rows: Record<string, string>[] }> = ({
  headers,
  rows,
}) => (
  <div className="rd-impact-table-wrap custom-scrollbar">
    <div
      className="rd-impact-table"
      style={{ gridTemplateColumns: `repeat(${headers.length}, minmax(120px, 1fr))` }}
    >
      <div className="rd-impact-table__head">
        {headers.map((h) => (
          <div key={h} className="rd-impact-table__cell rd-impact-table__cell--head">
            {h}
          </div>
        ))}
      </div>
      {rows.map((row, ri) => (
        <div key={ri} className="rd-impact-table__row">
          {headers.map((h) => {
            const val = String(row[h] ?? '').trim() || '—';
            return (
              <div
                key={h}
                className={`rd-impact-table__cell ${severityClass(val)}`}
                title={val}
              >
                {val}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  </div>
);

const DimensionCard: React.FC<{ section: ParsedImpactSection }> = ({ section }) => {
  const Icon = section.icon;
  return (
    <article className="rd-impact-dimension group">
      <div className={`rd-impact-dimension__bar bg-gradient-to-b ${ACCENT_BAR[section.accent]}`} />
      <div className="rd-impact-dimension__body">
        <header className="rd-impact-dimension__header">
          <div
            className={`rd-impact-dimension__icon bg-gradient-to-br border ${ACCENT_ICON_RING[section.accent]}`}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-semibold text-foreground tracking-tight">{section.title}</h4>
            {section.heading && section.heading !== section.title ? (
              <p className="text-[10px] text-muted-foreground/80 mt-0.5 font-mono truncate">
                {section.heading}
              </p>
            ) : null}
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {section.rows.length} 条 · {section.headers.length} 列
            </p>
          </div>
          <span
            className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${ACCENT_CHIP[section.accent]}`}
          >
            {section.short}
          </span>
        </header>
        <ImpactDataTable headers={section.headers} rows={section.rows} />
      </div>
    </article>
  );
};

export const ImpactAssessmentPanel: React.FC<{
  impact?: SolutionReviewImpactAssessment | null;
}> = ({ impact }) => {
  const sections = useMemo(() => parseImpactSections(impact), [impact]);
  const summary = useMemo(() => buildImpactSummary(sections), [sections]);
  const totalRows = sections.reduce((n, s) => n + s.rows.length, 0);

  if (!sections.length) {
    return (
      <section className="rd-impact-assessment rd-impact-assessment--empty">
        <div className="rd-impact-assessment__glow" aria-hidden />
        <div className="relative z-[1] flex flex-col items-center justify-center py-14 px-6 text-center">
          <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-4 mb-4">
            <Shield className="h-8 w-8 text-amber-400/80 mx-auto" />
          </div>
          <p className="text-sm text-muted-foreground max-w-md leading-relaxed">
            函数级方案中暂未解析到影响评估内容。若文档含「影响评估」章节，请确认各子标题下已填写 Markdown 表格。
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="rd-impact-assessment">
      <div className="rd-impact-assessment__glow" aria-hidden />
      <div className="relative z-[1] space-y-5">
        <header className="rd-impact-assessment__hero">
          <div className="flex items-start gap-3">
            <div className="rd-impact-assessment__hero-icon">
              <Sparkles className="h-5 w-5 text-amber-300" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-lg font-semibold text-foreground tracking-tight">影响评估</h3>
              <p className="text-[13px] text-foreground/80 mt-1 leading-relaxed">{summary}</p>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-2xl font-bold tabular-nums text-amber-300/95">{totalRows}</div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">评估项</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 mt-4">
            {sections.map((s) => {
              const Icon = s.icon;
              return (
                <span
                  key={s.id}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium ${ACCENT_CHIP[s.accent]}`}
                >
                  <Icon className="h-3.5 w-3.5 opacity-90" />
                  {s.title}
                  <span className="opacity-70">×{s.rows.length}</span>
                </span>
              );
            })}
          </div>
        </header>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {sections.map((section) => (
            <div
              key={section.id}
              className={section.headers.length >= 5 ? 'xl:col-span-2' : undefined}
            >
              <DimensionCard section={section} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
