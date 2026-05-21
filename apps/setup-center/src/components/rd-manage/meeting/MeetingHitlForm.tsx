/**
 * 研发会议室统一人机确认表单（questionnaire v1.0）。
 * 配置 schema 驱动；会议室介入弹窗中嵌入提交或只读预览。
 */
import React, { useCallback, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, ChevronRight, Sparkles } from 'lucide-react';
import { Button, Form, Input, Progress } from 'antd';

const { TextArea } = Input;

const OPTION_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

/* ── Questionnaire v1.0 ── */
export type HitlQuestionType = 'single' | 'multiple' | 'boolean' | 'text' | 'textarea';
export type HitlOptionStyle = 'radio' | 'checkbox' | 'boolean';

export interface HitlQuestionOption {
  value: string;
  label: string;
  selected?: boolean;
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

export interface HitlFormSchema {
  type?: 'questionnaire';
  version?: string;
  title?: string;
  description?: string;
  questions?: HitlQuestion[];
  render?: {
    layout?: 'stepped' | 'flat';
    showOverallProgress?: boolean;
    accent?: 'blue' | 'violet' | 'emerald';
    animate?: boolean;
  };
}

export type HitlFormValues = Record<string, string | string[] | boolean>;

function isQuestionnaire(schema: HitlFormSchema): boolean {
  return Array.isArray(schema.questions) && schema.questions.length > 0;
}

function isBooleanQuestion(q: HitlQuestion): boolean {
  if (q.render?.optionStyle === 'boolean') return true;
  const opts = q.options || [];
  return (
    opts.length === 2 &&
    opts.every((o) => o.value === 'true' || o.value === 'false')
  );
}

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
  const questions = schema.questions || [];
  const stepped = schema.render?.layout === 'stepped';
  const accent = accentClasses(schema.render?.accent);
  const [step, setStep] = useState(0);
  const [selections, setSelections] = useState<Record<string, Set<string>>>(() => {
    const init: Record<string, Set<string>> = {};
    questions.forEach((q) => {
      init[q.id] = new Set();
    });
    return init;
  });
  const [customTexts, setCustomTexts] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    questions.forEach((q) => {
      init[q.id] = '';
    });
    return init;
  });
  const [showCustom, setShowCustom] = useState<Record<string, boolean>>({});

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

  const toggleOption = useCallback((q: HitlQuestion, value: string) => {
    if (preview) return;
    const multi = q.type === 'multiple' || q.render?.optionStyle === 'checkbox';
    setSelections((prev) => {
      const next = new Set(prev[q.id]);
      if (multi) {
        if (next.has(value)) next.delete(value);
        else next.add(value);
      } else if (next.has(value)) {
        next.clear();
      } else {
        next.clear();
        next.add(value);
      }
      return { ...prev, [q.id]: next };
    });
  }, [preview]);

  const questionAnswered = (q: HitlQuestion): boolean => {
    const sel = selections[q.id];
    const custom = customTexts[q.id]?.trim();
    if (q.type === 'textarea' || q.type === 'text') return !!custom || !q.required;
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
          {opts.map((o) => {
            const active = sel.has(o.value);
            const yes = o.value === 'true';
            return (
              <motion.button
                key={o.value}
                type="button"
                disabled={preview}
                whileHover={preview ? undefined : { scale: 1.02 }}
                whileTap={preview ? undefined : { scale: 0.98 }}
                onClick={() => toggleOption(q, o.value)}
                className={`flex-1 py-3 px-4 rounded-xl border text-sm font-medium transition-all ${
                  active
                    ? yes
                      ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300 shadow-[0_0_20px_rgba(16,185,129,0.15)]'
                      : 'border-rose-500/60 bg-rose-500/15 text-rose-300 shadow-[0_0_20px_rgba(244,63,94,0.12)]'
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
          const active = sel.has(o.value);
          const letter = OPTION_LETTERS[idx] || String(idx + 1);
          const isDecision = q.id === 'decision';
          const approve = o.value === 'approve';
          const reject = o.value === 'reject';
          return (
            <motion.button
              key={o.value}
              type="button"
              disabled={preview}
              whileHover={preview ? undefined : { x: 2 }}
              onClick={() => toggleOption(q, o.value)}
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

  const renderQuestionBody = (q: HitlQuestion) => (
    <div className="space-y-1">
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-semibold text-foreground leading-snug">
          {q.title}
          {q.required ? <span className="text-rose-400 ml-1">*</span> : null}
        </h4>
        {q.render?.showProgress !== false && q.render?.progress ? (
          <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground bg-muted/40 px-2 py-0.5 rounded-full">
            {q.render.progress.current}/{q.render.progress.total}
          </span>
        ) : null}
      </div>
      {q.context ? (
        <p className="text-[11px] text-muted-foreground leading-relaxed pl-0.5 border-l-2 border-border/50 pl-2.5 mt-1.5">
          {q.context}
        </p>
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
      {q.inputEnabled && q.type !== 'textarea' && q.type !== 'text' ? (
        showCustom[q.id] ? (
          <Input
            autoFocus
            disabled={preview}
            value={customTexts[q.id] || ''}
            onChange={(e) => setCustomTexts((p) => ({ ...p, [q.id]: e.target.value }))}
            placeholder={q.inputPlaceholder || '或者你的答案：'}
            className="mt-2 bg-background/50 border-dashed border-border/60 text-xs"
          />
        ) : (
          <button
            type="button"
            disabled={preview}
            onClick={() => setShowCustom((p) => ({ ...p, [q.id]: true }))}
            className="mt-2 text-[11px] text-muted-foreground hover:text-foreground border border-dashed border-border/50 rounded-lg px-3 py-1.5 w-full text-left transition-colors"
          >
            {q.inputPlaceholder || '或者你的答案…'}
          </button>
        )
      ) : null}
    </div>
  );

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
            <span>{answeredCount}/{totalSteps} 已答</span>
          </div>
          <Progress
            percent={Math.round((answeredCount / totalSteps) * 100)}
            showInfo={false}
            strokeColor={{ from: '#3b82f6', to: '#8b5cf6' }}
            trailColor="rgba(128,128,128,0.15)"
            size="small"
          />
        </div>
      ) : null}

      {summaryMarkdown && !preview ? (
        <div className="rounded-xl border border-border/50 bg-background/60 p-3 max-h-44 overflow-y-auto custom-scrollbar backdrop-blur-sm">
          <div className="text-[10px] font-medium text-muted-foreground mb-2 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> 待确认总结
          </div>
          <pre className="text-[11px] text-foreground/90 whitespace-pre-wrap font-sans leading-relaxed m-0">
            {summaryMarkdown}
          </pre>
        </div>
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
  initialValues?: HitlFormValues;
  onSubmit?: (values: HitlFormValues) => void;
  submitLabel?: string;
  className?: string;
}> = ({
  schema,
  summaryMarkdown,
  preview = false,
  initialValues,
  onSubmit,
  submitLabel = '提交确认',
  className = '',
}) => {
  const questionnaire = isQuestionnaire(schema);
  const accent = accentClasses(schema.render?.accent);

  return (
    <div
      className={`rd-meeting-hitl-form overflow-hidden rounded-xl border border-border/60 bg-gradient-to-br ${accent.bg} ${className}`}
    >
      <div className="p-4 space-y-3">
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
            preview={preview}
            initialValues={initialValues}
            onSubmit={onSubmit}
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
