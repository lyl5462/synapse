/**
 * 研发会议室统一人机确认表单（questionnaire v1.0）。
 * 配置 schema 驱动；会议室介入弹窗中嵌入提交或只读预览。
 */
import React, { useCallback, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, CheckCircle2, ChevronRight, FileText, Sparkles } from 'lucide-react';
import { Button, Input, Progress } from 'antd';
import { ReviewMarkdown } from './ReviewMarkdown';

const { TextArea } = Input;

const OPTION_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

const HUMAN_SUPPLEMENT_QUESTION_ID = 'human_supplement';
const HUMAN_SUPPLEMENT_TITLE = '请问您还有什么需要补充的吗？';
const DEFAULT_CUSTOM_PLACEHOLDER = '或者你的答案：';

function isFreeTextQuestion(q: HitlQuestion): boolean {
  return q.type === 'textarea' || q.type === 'text';
}

function buildSupplementQuestion(): HitlQuestion {
  return {
    id: HUMAN_SUPPLEMENT_QUESTION_ID,
    type: 'textarea',
    title: HUMAN_SUPPLEMENT_TITLE,
    context: '选填。此处为自由补充说明，不会覆盖您在上方各题中的选择；无补充可留空直接提交。',
    required: false,
    render: { showProgress: true },
  };
}

/** 渲染前护栏：每题可输入；末尾追加统一补充题（与后端 normalize 对齐）。 */
function normalizeQuestionsForRender(raw: HitlQuestion[]): HitlQuestion[] {
  const mapped = raw.map((q) => {
    const item: HitlQuestion = { ...q };
    if (item.id === HUMAN_SUPPLEMENT_QUESTION_ID) return item;
    if (isFreeTextQuestion(item)) return item;
    const opts = item.options || [];
    if ((item.type === 'single' || item.type === 'multiple') && opts.length === 0) {
      return {
        ...item,
        type: 'textarea' as HitlQuestionType,
        options: [],
        inputPlaceholder: item.inputPlaceholder || '请输入您的回答…',
      };
    }
    return {
      ...item,
      inputEnabled: true,
      inputPlaceholder: item.inputPlaceholder || DEFAULT_CUSTOM_PLACEHOLDER,
    };
  });
  const hasSupplement = mapped.some(
    (q) =>
      q.id === HUMAN_SUPPLEMENT_QUESTION_ID ||
      (q.title || '').includes(HUMAN_SUPPLEMENT_TITLE),
  );
  const withSupplement = hasSupplement ? mapped : [...mapped, buildSupplementQuestion()];
  return withSupplement.map((q, idx, arr) => ({
    ...q,
    render: {
      ...q.render,
      showProgress: q.render?.showProgress !== false,
      progress: { current: idx + 1, total: arr.length },
    },
  }));
}

function normalizeSchemaForRender(schema: HitlFormSchema): HitlFormSchema {
  const raw = schema.questions || [];
  if (raw.length === 0) return schema;
  return { ...schema, questions: normalizeQuestionsForRender(raw) };
}

/* ── Questionnaire v1.0 ── */
export type HitlQuestionType = 'single' | 'multiple' | 'boolean' | 'text' | 'textarea';
export type HitlOptionStyle = 'radio' | 'checkbox' | 'boolean';

export interface HitlQuestionOption {
  /** 选项主键；LLM 偶尔输出 `id` 而不是 `value`，渲染时会自动回退 */
  value: string;
  /** 兼容字段：当 LLM 输出 ``{"id": "...", "label": "..."}`` 时使用 */
  id?: string;
  label: string;
  selected?: boolean;
}

/** 归一化选项主键：是/否、bool、True/False 统一为 true/false，保证选中态一致。 */
function optionKey(o: HitlQuestionOption, idx: number): string {
  if (typeof o.value === 'boolean') {
    return o.value ? 'true' : 'false';
  }
  const raw =
    (typeof o.value === 'string' && o.value.trim()) ||
    (typeof o.id === 'string' && o.id.trim()) ||
    (typeof o.label === 'string' && o.label.trim()) ||
    '';
  const text = raw.trim();
  if (!text) return `opt_${idx}`;
  const low = text.toLowerCase();
  if (low === 'true' || low === 'yes' || low === 'y' || low === '1' || text === '是') return 'true';
  if (low === 'false' || low === 'no' || low === 'n' || low === '0' || text === '否') return 'false';
  return text;
}

function isAffirmativeOption(key: string, label?: string): boolean {
  const k = (key || '').trim().toLowerCase();
  const lb = (label || '').trim();
  if (k === 'true' || k === 'yes' || k === 'y' || k === '1') return true;
  if (lb === '是') return true;
  return false;
}

export interface HitlQuestionRender {
  layout?: 'vertical' | 'horizontal' | 'grid';
  optionStyle?: HitlOptionStyle;
  showProgress?: boolean;
  progress?: { current: number; total: number };
}

export interface HitlQuestion {
  id: string;
  type: HitlQuestionType;
  title: string;
  context?: string;
  options?: HitlQuestionOption[];
  inputEnabled?: boolean;
  inputPlaceholder?: string;
  required?: boolean;
  render?: HitlQuestionRender;
}

export type HitlSummaryKind = 'exception' | 'result_confirm' | 'interactive';

export interface HitlFormSchema {
  type?: 'questionnaire';
  version?: string;
  title?: string;
  description?: string;
  questions?: HitlQuestion[];
  render?: {
    layout?: 'stepped' | 'flat';
    showOverallProgress?: boolean;
    /** stepped 下总进度按当前题序（非已填题数）；默认 step */
    progressBasis?: 'step' | 'answered';
    accent?: 'blue' | 'violet' | 'emerald';
    animate?: boolean;
  };
  /** 工具 / 异常默认模板写入：表单上方展示给用户的 markdown 摘要 */
  summary_markdown?: string;
  /** 异常原因短文本（与 summary_kind 一起渲染醒目卡片） */
  summary_reason?: string;
  /** 介入类型；驱动摘要的颜色 / 图标 */
  summary_kind?: HitlSummaryKind;
  intervention_kind?: HitlSummaryKind;
}

export type HitlFormValues = Record<string, string | string[] | boolean>;

function isQuestionnaire(schema: HitlFormSchema): boolean {
  return Array.isArray(schema.questions) && schema.questions.length > 0;
}

function isBooleanQuestion(q: HitlQuestion): boolean {
  if (q.type === 'boolean') return true;
  if (q.render?.optionStyle === 'boolean') return true;
  const opts = q.options || [];
  if (opts.length !== 2) return false;
  const keys = opts.map((o, idx) => optionKey(o, idx));
  return keys.includes('true') && keys.includes('false');
}

function isRichMarkdownText(text: string): boolean {
  const t = (text || '').trim();
  if (!t) return false;
  return (
    t.includes('\n') ||
    /^#{1,3}\s/m.test(t) ||
    /^\s*[-*•]\s/m.test(t) ||
    /^\s*\d+\.\s/m.test(t) ||
    t.includes('|') ||
    t.includes('**')
  );
}

function resolveEffectiveSummary(schema: HitlFormSchema, summaryMarkdown?: string): string {
  const fromProp = (summaryMarkdown || '').trim();
  const fromSchema = (schema.summary_markdown || '').trim();
  if (fromProp && fromSchema && fromProp !== fromSchema) {
    return `${fromProp}\n\n---\n\n${fromSchema}`;
  }
  return fromProp || fromSchema;
}

const HitlSummaryPanel: React.FC<{
  markdown: string;
  accent: ReturnType<typeof accentClasses>;
  kind?: HitlSummaryKind;
}> = ({ markdown, accent, kind }) => {
  const text = (markdown || '').trim();
  if (!text) return null;
  const label =
    kind === 'result_confirm' ? '待确认总结' : kind === 'exception' ? '异常摘要' : '待确认内容';
  return (
    <div
      className={`rounded-xl border ${accent.ring} bg-background/55 backdrop-blur-md shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] overflow-hidden`}
    >
      <div className={`flex items-center gap-2 px-3.5 py-2.5 border-b border-border/40 bg-gradient-to-r ${accent.bg}`}>
        <FileText className={`w-3.5 h-3.5 shrink-0 ${accent.text}`} />
        <span className={`text-[11px] font-semibold tracking-wide ${accent.text}`}>{label}</span>
        <span className="text-[10px] text-muted-foreground ml-auto">表单上方 · 请先阅读再答题</span>
      </div>
      <div className="relative max-h-[min(42vh,320px)] overflow-y-auto custom-scrollbar px-3.5 py-3">
        <ReviewMarkdown content={text} compact className="rd-meeting-hitl-summary-md text-[12px]" />
        <div
          className="pointer-events-none sticky bottom-0 left-0 right-0 h-8 -mb-3 bg-gradient-to-t from-background/90 to-transparent"
          aria-hidden
        />
      </div>
    </div>
  );
};

function accentClasses(accent?: string): { ring: string; bg: string; text: string; bar: string } {
  switch (accent) {
    case 'violet':
      return {
        ring: 'ring-violet-500/40 border-violet-500/50 bg-violet-500/10',
        bg: 'from-violet-600/20 via-violet-500/5 to-transparent',
        text: 'text-violet-400',
        bar: 'bg-violet-500',
      };
    case 'emerald':
      return {
        ring: 'ring-emerald-500/40 border-emerald-500/50 bg-emerald-500/10',
        bg: 'from-emerald-600/20 via-emerald-500/5 to-transparent',
        text: 'text-emerald-400',
        bar: 'bg-emerald-500',
      };
    default:
      return {
        ring: 'ring-blue-500/40 border-blue-500/50 bg-blue-500/10',
        bg: 'from-blue-600/25 via-blue-500/8 to-transparent',
        text: 'text-blue-400',
        bar: 'bg-blue-500',
      };
  }
}

/* ── Questionnaire UI ── */
const HitlQuestionnaireForm: React.FC<{
  schema: HitlFormSchema;
  summaryMarkdown?: string;
  preview?: boolean;
  initialValues?: HitlFormValues;
  onSubmit?: (values: HitlFormValues) => void;
  submitLabel?: string;
}> = ({
  schema,
  summaryMarkdown,
  preview = false,
  initialValues,
  onSubmit,
  submitLabel = '提交确认',
}) => {
  const normalizedSchema = useMemo(() => normalizeSchemaForRender(schema), [schema]);
  const questions = normalizedSchema.questions || [];
  const stepped = schema.render?.layout === 'stepped';
  const accent = accentClasses(schema.render?.accent);
  const summaryKind = schema.summary_kind ?? schema.intervention_kind;
  const effectiveSummary = useMemo(
    () => resolveEffectiveSummary(schema, summaryMarkdown),
    [schema, summaryMarkdown],
  );
  const [step, setStep] = useState(0);
  const hydrateFromInitial = (vals?: HitlFormValues) => {
    const selInit: Record<string, Set<string>> = {};
    const customInit: Record<string, string> = {};
    const showInit: Record<string, boolean> = {};
    questions.forEach((q) => {
      selInit[q.id] = new Set();
      customInit[q.id] = '';
      const raw = vals?.[q.id];
      if (raw === undefined || raw === null) return;
      if (q.type === 'textarea' || q.type === 'text') {
        customInit[q.id] = String(raw);
        return;
      }
      const items = Array.isArray(raw) ? raw.map(String) : [String(raw)];
      const opts = new Set<string>();
      items.forEach((item) => {
        if (item.startsWith('OTHER:')) {
          customInit[q.id] = item.slice(6).trim();
          showInit[q.id] = true;
        } else {
          opts.add(item);
        }
      });
      selInit[q.id] = opts;
      if (customInit[q.id]) showInit[q.id] = true;
    });
    return { selInit, customInit, showInit };
  };

  const seeded = useMemo(() => hydrateFromInitial(initialValues), [initialValues, questions]);
  const [selections, setSelections] = useState<Record<string, Set<string>>>(seeded.selInit);
  const [customTexts, setCustomTexts] = useState<Record<string, string>>(seeded.customInit);
  const [showCustom, setShowCustom] = useState<Record<string, boolean>>(seeded.showInit);

  const currentQ = questions[step];
  const totalSteps = questions.length;
  const answeredCount = useMemo(() => {
    return questions.filter((q) => {
      const sel = selections[q.id];
      const custom = customTexts[q.id]?.trim();
      if (q.type === 'textarea' || q.type === 'text') return !!custom;
      return (sel && sel.size > 0) || !!custom;
    }).length;
  }, [questions, selections, customTexts]);

  const progressBasis = schema.render?.progressBasis ?? (stepped ? 'step' : 'answered');
  const progressCurrent = progressBasis === 'step' ? step + 1 : answeredCount;

  const toggleOption = useCallback((q: HitlQuestion, value: string) => {
    if (preview) return;
    const multi = q.type === 'multiple' || q.render?.optionStyle === 'checkbox';
    const boolQ = isBooleanQuestion(q);
    setSelections((prev) => {
      const next = new Set(prev[q.id]);
      if (multi) {
        if (next.has(value)) next.delete(value);
        else next.add(value);
      } else if (!boolQ && next.has(value)) {
        next.clear();
      } else {
        next.clear();
        next.add(value);
      }
      return { ...prev, [q.id]: next };
    });
  }, [preview]);

  const setCustomForQuestion = useCallback((q: HitlQuestion, text: string) => {
    if (preview) return;
    setCustomTexts((p) => ({ ...p, [q.id]: text }));
    if (text.trim()) {
      setShowCustom((p) => ({ ...p, [q.id]: true }));
    }
  }, [preview]);

  const questionAnswered = (q: HitlQuestion): boolean => {
    const sel = selections[q.id];
    const custom = customTexts[q.id]?.trim();
    if (isFreeTextQuestion(q)) return !!custom || !q.required;
    if (q.required) return (sel?.size ?? 0) > 0 || !!custom;
    return true;
  };

  const canProceed = currentQ ? questionAnswered(currentQ) : false;
  const isLastStep = step >= totalSteps - 1;

  const buildValues = (): HitlFormValues => {
    const values: HitlFormValues = {};
    questions.forEach((q) => {
      const sel = selections[q.id];
      const custom = customTexts[q.id]?.trim();
      if (q.type === 'textarea' || q.type === 'text') {
        if (custom) values[q.id] = custom;
        return;
      }
      const arr = sel ? Array.from(sel) : [];
      if (custom) arr.push(`OTHER:${custom}`);
      if (arr.length === 0) return;
      values[q.id] =
        q.type === 'multiple' || q.render?.optionStyle === 'checkbox'
          ? arr
          : arr[0];
    });
    return values;
  };

  const handleSubmit = () => {
    if (preview || !onSubmit) return;
    onSubmit(buildValues());
  };

  const renderOptions = (q: HitlQuestion) => {
    const opts = q.options || [];
    const sel = selections[q.id] || new Set<string>();
    const boolStyle = isBooleanQuestion(q);
    const multi = q.type === 'multiple' || q.render?.optionStyle === 'checkbox';

    if (boolStyle) {
      return (
        <div className="flex gap-3 mt-3">
          {opts.map((o, idx) => {
            const key = optionKey(o, idx);
            const active = sel.has(key);
            const yes = isAffirmativeOption(key, o.label);
            return (
              <motion.button
                key={key}
                type="button"
                disabled={preview}
                aria-pressed={active}
                whileHover={preview ? undefined : { scale: 1.02 }}
                whileTap={preview ? undefined : { scale: 0.98 }}
                onClick={() => toggleOption(q, key)}
                className={`flex-1 py-3 px-4 rounded-xl border text-sm font-medium transition-all ${
                  active
                    ? yes
                      ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300 shadow-[0_0_20px_rgba(16,185,129,0.15)] ring-1 ring-emerald-500/40'
                      : 'border-rose-500/60 bg-rose-500/15 text-rose-300 shadow-[0_0_20px_rgba(244,63,94,0.12)] ring-1 ring-rose-500/40'
                    : 'border-border/50 bg-background/40 text-muted-foreground hover:border-border'
                }`}
              >
                {o.label}
              </motion.button>
            );
          })}
        </div>
      );
    }

    return (
      <div className="flex flex-col gap-2 mt-3">
        {opts.map((o, idx) => {
          const key = optionKey(o, idx);
          const active = sel.has(key);
          const letter = OPTION_LETTERS[idx] || String(idx + 1);
          const isDecision = q.id === 'decision';
          const approve = key === 'approve';
          const reject = key === 'reject';
          return (
            <motion.button
              key={key}
              type="button"
              disabled={preview}
              whileHover={preview ? undefined : { x: 2 }}
              onClick={() => toggleOption(q, key)}
              className={`group flex items-start gap-3 w-full text-left p-3 rounded-xl border transition-all duration-200 ${
                active
                  ? isDecision && approve
                    ? 'border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/30'
                    : isDecision && reject
                      ? 'border-rose-500/50 bg-rose-500/10 ring-1 ring-rose-500/30'
                      : accent.ring
                  : 'border-border/40 bg-background/30 hover:border-border/70 hover:bg-muted/20'
              }`}
            >
              <span
                className={`shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold transition-colors ${
                  active
                    ? isDecision && approve
                      ? 'bg-emerald-500 text-white'
                      : isDecision && reject
                        ? 'bg-rose-500 text-white'
                        : `${accent.bar} text-white`
                    : 'bg-muted/60 text-muted-foreground group-hover:bg-muted'
                } ${multi ? 'rounded-md' : 'rounded-full'}`}
              >
                {multi ? (active ? '✓' : '') : letter}
              </span>
              <span className={`text-xs leading-relaxed pt-0.5 ${active ? 'text-foreground' : 'text-foreground/80'}`}>
                {o.label}
              </span>
            </motion.button>
          );
        })}
      </div>
    );
  };

  const renderPerQuestionInput = (q: HitlQuestion) => {
    if (isFreeTextQuestion(q)) return null;
    return (
      <div
        className={`mt-3 rounded-xl border-2 p-0.5 transition-all ${
          (customTexts[q.id] || '').trim()
            ? 'border-amber-400/70 bg-amber-500/10 shadow-[0_0_16px_rgba(245,158,11,0.18)] ring-1 ring-amber-400/30'
            : 'border-dashed border-border/50 bg-muted/15'
        }`}
      >
        <div className="px-2.5 pt-1.5 text-[10px] font-medium text-amber-300/90">
          您的回答{optsLength(q) > 0 ? '（可与上方选项配合；仅填此项亦可）' : ''}
        </div>
        <Input
          disabled={preview}
          value={customTexts[q.id] || ''}
          onChange={(e) => setCustomForQuestion(q, e.target.value)}
          placeholder={q.inputPlaceholder || DEFAULT_CUSTOM_PLACEHOLDER}
          className="border-0 bg-transparent text-xs text-foreground shadow-none focus:shadow-none"
        />
      </div>
    );
  };

  const renderQuestionBody = (q: HitlQuestion) => {
    const qProgress =
      progressBasis === 'step'
        ? { current: step + 1, total: totalSteps }
        : q.render?.progress;
    return (
    <div className="space-y-1">
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-semibold text-foreground leading-snug">
          {q.title}
          {q.required ? <span className="text-rose-400 ml-1">*</span> : null}
        </h4>
        {q.render?.showProgress !== false && qProgress ? (
          <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground bg-muted/40 px-2 py-0.5 rounded-full">
            {qProgress.current}/{qProgress.total}
          </span>
        ) : null}
      </div>
      {q.context ? (
        isRichMarkdownText(q.context) ? (
          <div className="mt-2 rounded-lg border border-border/45 bg-muted/15 px-3 py-2.5">
            <div className="text-[10px] font-medium text-muted-foreground mb-1.5 uppercase tracking-wider">
              待审阅内容
            </div>
            <ReviewMarkdown content={q.context} compact className="rd-meeting-hitl-context-md text-[11px]" />
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground leading-relaxed pl-0.5 border-l-2 border-border/50 pl-2.5 mt-1.5">
            {q.context}
          </p>
        )
      ) : null}
      {(q.type === 'textarea' || q.type === 'text') && (
        <TextArea
          rows={q.type === 'textarea' ? 4 : 2}
          disabled={preview}
          value={customTexts[q.id] || ''}
          onChange={(e) => setCustomTexts((p) => ({ ...p, [q.id]: e.target.value }))}
          placeholder={q.inputPlaceholder || '请输入…'}
          className="mt-3 bg-background/50 border-border/50 text-foreground text-xs resize-none"
        />
      )}
      {optsLength(q) > 0 ? renderOptions(q) : null}
      {renderPerQuestionInput(q)}
    </div>
    );
  };

  const visibleQuestions = stepped ? (currentQ ? [currentQ] : []) : questions;

  return (
    <div className="space-y-4">
      {schema.render?.showOverallProgress !== false && totalSteps > 1 ? (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Sparkles className={`w-3 h-3 ${accent.text}`} />
              确认进度
            </span>
            <span>
              {progressCurrent}/{totalSteps}
              {progressBasis === 'answered' ? ' 已答' : ''}
            </span>
          </div>
          <Progress
            percent={Math.round((progressCurrent / totalSteps) * 100)}
            showInfo={false}
            strokeColor={{ from: '#3b82f6', to: '#8b5cf6' }}
            trailColor="rgba(128,128,128,0.15)"
            size="small"
          />
        </div>
      ) : null}

      {(() => {
        const kind: HitlSummaryKind | undefined =
          schema.summary_kind ?? schema.intervention_kind;
        if (kind !== 'exception') return null;
        const reason = (schema.summary_reason || '').trim();
        if (!reason) return null;
        return (
          <div className="rounded-xl border border-violet-500/40 bg-violet-500/10 ring-1 ring-violet-500/25 p-3.5 backdrop-blur-sm">
            <div className="text-[11px] font-semibold flex items-center gap-1.5 text-violet-200/90 mb-2">
              <AlertTriangle className="w-3.5 h-3.5" />
              异常说明
            </div>
            <p className="text-[12px] text-foreground/95 leading-relaxed m-0">{reason}</p>
            <p className="text-[10px] text-muted-foreground mt-2 leading-relaxed">
              请选择处置方式后提交。
            </p>
          </div>
        );
      })()}

      {effectiveSummary ? (
        <HitlSummaryPanel markdown={effectiveSummary} accent={accent} kind={summaryKind} />
      ) : null}

      <AnimatePresence mode="wait">
        {visibleQuestions.map((q) => (
          <motion.div
            key={q.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.22 }}
            className="rounded-xl border border-border/50 bg-background/40 p-4 backdrop-blur-sm shadow-sm"
          >
            {renderQuestionBody(q)}
          </motion.div>
        ))}
      </AnimatePresence>

      {!preview && onSubmit ? (
        <div className="flex items-center justify-between gap-2 pt-1">
          {stepped && step > 0 ? (
            <Button size="small" onClick={() => setStep((s) => s - 1)}>
              上一题
            </Button>
          ) : (
            <span />
          )}
          {stepped && !isLastStep ? (
            <Button
              type="primary"
              size="small"
              disabled={!canProceed}
              icon={<ChevronRight className="w-3.5 h-3.5" />}
              iconPosition="end"
              onClick={() => setStep((s) => s + 1)}
              className="bg-blue-600 hover:bg-blue-500 border-none shadow-[0_4px_14px_rgba(37,99,235,0.35)]"
            >
              下一题
            </Button>
          ) : (
            <Button
              type="primary"
              size="small"
              disabled={!questions.every(questionAnswered)}
              onClick={handleSubmit}
              className="bg-blue-600 hover:bg-blue-500 border-none shadow-[0_4px_14px_rgba(37,99,235,0.35)]"
            >
              {submitLabel}
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
};

function optsLength(q: HitlQuestion): number {
  return q.options?.length ?? 0;
}

/* ── Entry ── */
export const MeetingHitlForm: React.FC<{
  schema: HitlFormSchema;
  summaryMarkdown?: string;
  preview?: boolean;
  locked?: boolean;
  initialValues?: HitlFormValues;
  onSubmit?: (values: HitlFormValues) => void;
  submitLabel?: string;
  className?: string;
}> = ({
  schema,
  summaryMarkdown,
  preview = false,
  locked = false,
  initialValues,
  onSubmit,
  submitLabel = '提交确认',
  className = '',
}) => {
  const questionnaire = isQuestionnaire(schema);
  const accent = accentClasses(schema.render?.accent);
  const readOnly = preview || locked;

  return (
    <div
      className={`rd-meeting-hitl-form overflow-hidden rounded-xl border border-border/60 bg-gradient-to-br ${accent.bg} ${className}`}
    >
      <div className="p-4 space-y-3">
        {locked ? (
          <div className="flex items-center gap-2 text-[11px] text-emerald-300/95 bg-emerald-500/10 border border-emerald-500/35 rounded-lg px-3 py-2">
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
            已提交并锁定，不可再修改；系统正在根据您的答案继续处理。
          </div>
        ) : null}
        {schema.title ? (
          <div className="flex items-center gap-2">
            <div className={`w-1 h-5 rounded-full ${accent.bar}`} />
            <div className="text-sm font-semibold text-foreground/95">{schema.title}</div>
          </div>
        ) : null}
        {schema.description ? (
          <p className="text-[11px] text-muted-foreground leading-relaxed pl-3">{schema.description}</p>
        ) : null}

        {questionnaire ? (
          <HitlQuestionnaireForm
            schema={schema}
            summaryMarkdown={summaryMarkdown}
            preview={readOnly}
            initialValues={initialValues}
            onSubmit={readOnly ? undefined : onSubmit}
            submitLabel={submitLabel}
          />
        ) : (
          <p className="text-[11px] text-amber-400/90 pl-3">
            表单配置无效：须包含非空的 <code className="text-[10px]">questions</code> 数组（questionnaire v1.0）。
          </p>
        )}

        {preview && questionnaire ? (
          <p className="text-[10px] text-muted-foreground pt-1 border-t border-border/30">
            预览：节点开启「人工确认」后，智能体输出待确认总结，用户逐项回答上述问题提交；
            分步向导支持进度追踪与自定义补充。确认通过后系统才写入归档产物并推进节点。
          </p>
        ) : null}
      </div>
    </div>
  );
};
