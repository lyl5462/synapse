import React, { useState, useMemo, useEffect, useRef, useCallback } from "react";
import MDEditor from "@uiw/react-md-editor";
import { Editor, DiffEditor } from "@monaco-editor/react";
import { Button } from "@/components/ui/button";
import { ExcalidrawReadonlyEmbed } from "./ExcalidrawReadonlyEmbed";
import {
  applyAppThemeToExcalidrawInitialData,
  excalidrawThemeFromApp,
  getExcalidrawViewBackgroundForAppTheme,
  getExcalidrawPayload,
  parseExcalidrawFileToInitialData,
} from "./excalidrawScene";
import { Wrench, Loader2, Send, Save, Eye, Edit2, Check, X } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  refineProductKnowledge,
  getProductKnowledgeRefineStatus,
  productKnowledgeRefineSessionClose,
  RefinePendingError,
} from "@/api/rdUnifiedService";
import type {
  ProductKnowledgeRefineResult,
  ProductKnowledgeRefineStatusResult,
} from "@/api/rdUnifiedService";

/** 文档预览中 Excalidraw 外框：占视口高度为主，大屏最高约 800px，避免原 400px 过小 */
const EXCALIDRAW_PREVIEW_FRAME_STYLE: React.CSSProperties = {
  height: "min(70vh, 600px)",
};

/** Markdown 中 `![...](foo.excalidraw)` 的 foo.excalidraw 原文 JSON（多文件时按文件名查） */
type OnSaveMeta = { showSaveSuccessToast?: boolean };

/** refine 所需的产品上下文与文件定位信息（由 ProductDetail 注入） */
export type RefineContext = {
  prod_name: string;
  doc_type: string;
  /** 当前 Tab 对应的稳定文件名（如 FUNCTIONAL_ARCH.md） */
  target: string;
  product_desc?: string;
  code_path?: string;
  core_features?: string;
  /** GitNexus 服务地址（源码缓存缺失时用于拉取，与 generate 接口同源） */
  gitnexus_url?: string;
};

/** 已加载的 LLM 端点 / 研发技能 catalog（由 ProductDetail 注入，与生成弹窗同源） */
export type RefineCatalog = {
  llmEndpoints: { name: string; model?: string }[];
  rdSkills: { skillId: string; name: string }[];
  rdSkillsLoading?: boolean;
};

interface ProductDocumentEditorProps {
  content: string;
  title: string;
  synapseApiBase: string;
  excalidrawByFileName?: Record<string, string>;
  readonly?: boolean;
  onSave?: (content: string, meta?: OnSaveMeta) => void | Promise<void>;
  onSubmit?: () => void;
  /** 为 false 时禁用「提交到服务端」（例如本地缓存目录无草稿时） */
  submitEnabled?: boolean;
  /** 当前文档是否有未保存的编辑（曾进入编辑模式且内容与上次保存不一致） */
  onDirtyChange?: (dirty: boolean) => void;
  /** refine 所需定位信息；缺少时不渲染 AI 区 */
  refineContext?: RefineContext;
  /** catalog 数据（由父组件懒加载后传入） */
  refineCatalog?: RefineCatalog;
  /** 父组件触发 catalog 加载（打开配置面板时） */
  onLoadRefineCatalog?: () => void;
}

function fixMarkdownTableDelimiters(md: string): string {
  if (!md) return md;
  const lines = md.split('\n');
  let inCodeBlock = false;
  
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    
    if (line.startsWith('```') || line.startsWith('~~~')) {
      inCodeBlock = !inCodeBlock;
      continue;
    }
    
    if (inCodeBlock) continue;
    
    if (/^[|\-:\s]+$/.test(line) && line.includes('-')) {
      const prevLine = lines[i - 1].trim();
      
      if (prevLine.includes('|')) {
        const getCellCount = (str: string) => {
          let s = str.trim();
          if (s.startsWith('|')) s = s.slice(1);
          if (s.endsWith('|')) s = s.slice(0, -1);
          return s.split(/(?<!\\)\|/).length;
        };
        
        const headerCount = getCellCount(prevLine);
        const delimCount = getCellCount(line);
        
        if (headerCount > 0 && delimCount > 0 && headerCount !== delimCount) {
          const newDelim = Array(headerCount).fill('---').join(' | ');
          lines[i] = prevLine.startsWith('|') ? `| ${newDelim} |` : newDelim;
        }
      }
    }
  }
  return lines.join('\n');
}

function fileNameFromMarkdownSrc(src: string | undefined): string {
  if (!src) return "";
  const noQuery = src.trim().split(/[?#]/)[0] || "";
  const parts = noQuery.replace(/\\/g, "/").split("/");
  return (parts[parts.length - 1] || noQuery).trim();
}

const REFINE_POLL_INTERVAL_MS = 30_000;

export function ProductDocumentEditor({
  content: initialContent,
  title,
  synapseApiBase,
  excalidrawByFileName,
  readonly = false,
  onSave,
  onSubmit,
  submitEnabled = true,
  onDirtyChange,
  refineContext,
  refineCatalog,
  onLoadRefineCatalog,
}: ProductDocumentEditorProps) {
  const { t } = useTranslation();
  const [content, setContent] = useState(() => fixMarkdownTableDelimiters(initialContent));
  const savedContentRef = useRef(fixMarkdownTableDelimiters(initialContent));
  const [hasOpenedEdit, setHasOpenedEdit] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [isRefining, setIsRefining] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [mode, setMode] = useState<"edit" | "preview">("preview");
  const onDirtyChangeRef = useRef(onDirtyChange);
  onDirtyChangeRef.current = onDirtyChange;

  // AI 配置面板
  const [configPanelOpen, setConfigPanelOpen] = useState(false);
  const [refineEndpoint, setRefineEndpoint] = useState("");
  const [refineSkills, setRefineSkills] = useState<string[]>([]);

  // Diff 状态（接受/拒绝面板）
  const [diffResult, setDiffResult] = useState<ProductKnowledgeRefineResult | null>(null);

  /** 是否对当前 target 做 30s 一次的 refine/status 轮询 */
  const [refinePollActive, setRefinePollActive] = useState(false);
  const [refineStatusText, setRefineStatusText] = useState<string>("");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isAppThemeDark = (theme: string | null) =>
    theme === "dark" || theme === "daltonized-dark" || theme === "high-contrast";

  const [isDark, setIsDark] = useState(() =>
    isAppThemeDark(document.documentElement.getAttribute("data-theme")),
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(isAppThemeDark(document.documentElement.getAttribute("data-theme")));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const fixed = fixMarkdownTableDelimiters(initialContent);
    setContent(fixed);
    savedContentRef.current = fixed;
    setHasOpenedEdit(false);
    // 切换 tab 时清除未完成的 diff 面板（不自动关闭会话，让服务端自然过期）
    setDiffResult(null);
  }, [initialContent]);

  const isDirty =
    !readonly &&
    hasOpenedEdit &&
    fixMarkdownTableDelimiters(content) !== savedContentRef.current;

  useEffect(() => {
    onDirtyChangeRef.current?.(isDirty);
  }, [isDirty]);

  // 是否有挂起的未审核 refine 会话（diff 已就绪待用户决策）
  const hasPendingSession = diffResult !== null;
  const isPolling = refinePollActive && diffResult === null;

  const stopPolling = useCallback(() => {
    if (pollingRef.current !== null) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    setRefinePollActive(false);
    setRefineStatusText("");
    setIsRefining(false);
  }, []);

  const refineContextRef = useRef(refineContext);
  refineContextRef.current = refineContext;

  /** 处理一次 status 响应；返回是否应继续轮询（pending/running） */
  const applyRefineStatus = useCallback(
    (status: ProductKnowledgeRefineStatusResult, ctx: RefineContext): boolean => {
      if (status.status === "none") {
        setIsRefining(false);
        return false;
      }
      if (status.status === "pending" || status.status === "running") {
        setIsRefining(true);
        setRefineStatusText(
          status.status === "running"
            ? t("workbench.products.detail.refinePollingRunning", "AI 正在修改文档...")
            : t("workbench.products.detail.refinePollingPending", "AI 正在处理中，请稍候..."),
        );
        return true;
      }
      if (status.status === "completed") {
        const tgt = (status.target ?? ctx.target).trim();
        setIsRefining(false);
        if (status.proposed !== undefined && status.original !== undefined) {
          setDiffResult({
            target: tgt,
            targets: status.targets ?? [tgt],
            original: status.original,
            proposed: status.proposed,
          });
          toast.success(t("workbench.products.detail.refineCompleted", "AI 修改完成，请查看修改建议"));
        }
        return false;
      }
      if (status.status === "timeout") {
        setIsRefining(false);
        const up = (status.user_prompt ?? "").trim();
        const min = status.elapsed_minutes ?? "?";
        toast.error(
          t(
            "workbench.products.detail.refineTimeoutToast",
            "AI处理超时(超过{{min}}分钟)，文档需求：{{req}}",
            { min: String(min), req: up || "—" },
          ),
        );
        return false;
      }
      if (status.status === "error") {
        setIsRefining(false);
        const up = (status.user_prompt ?? "").trim();
        toast.error(
          t(
            "workbench.products.detail.refineFailedWithPrompt",
            "AI处理失败，文档需求：{{req}}",
            { req: up || (status.error ?? "unknown") },
          ),
        );
        return false;
      }
      return false;
    },
    [t],
  );

  const pollRefineOnce = useCallback(async (): Promise<boolean> => {
    const latestCtx = refineContextRef.current;
    if (!latestCtx) return false;
    try {
      const status = await getProductKnowledgeRefineStatus(synapseApiBase, {
        prod_name: latestCtx.prod_name,
        doc_type: latestCtx.doc_type,
        target: latestCtx.target,
      });
      return applyRefineStatus(status, latestCtx);
    } catch {
      return true;
    }
  }, [synapseApiBase, applyRefineStatus]);

  const beginRefinePollingLoop = useCallback(() => {
    if (pollingRef.current !== null) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    setRefinePollActive(true);
    void pollRefineOnce().then((cont) => {
      if (!cont) stopPolling();
    });
    pollingRef.current = setInterval(() => {
      void pollRefineOnce().then((cont) => {
        if (!cont) stopPolling();
      });
    }, REFINE_POLL_INTERVAL_MS);
  }, [pollRefineOnce, stopPolling]);

  // 点击/切换到文档 Tab：仅此处与 refine 提交后触发 status（见 handleRefine）
  const refineProd = refineContext?.prod_name?.trim() ?? "";
  const refineDocType = refineContext?.doc_type?.trim() ?? "";
  const refineTarget = refineContext?.target?.trim() ?? "";
  useEffect(() => {
    if (!refineProd || !refineDocType || !refineTarget) return;
    stopPolling();
    setDiffResult(null);
    let cancelled = false;
    void (async () => {
      const ctx = refineContextRef.current;
      if (!ctx) return;
      try {
        const status = await getProductKnowledgeRefineStatus(synapseApiBase, {
          prod_name: ctx.prod_name,
          doc_type: ctx.doc_type,
          target: ctx.target,
        });
        if (cancelled) return;
        const cont = applyRefineStatus(status, ctx);
        if (cancelled) return;
        if (cont) beginRefinePollingLoop();
      } catch {
        /* 静默 */
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [synapseApiBase, refineProd, refineDocType, refineTarget, applyRefineStatus, stopPolling, beginRefinePollingLoop]);

  // 组件卸载时清理轮询
  useEffect(() => {
    return () => {
      if (pollingRef.current !== null) clearInterval(pollingRef.current);
    };
  }, []);

  const handleRefine = async () => {
    if (!prompt.trim() || isRefining || isPolling) return;
    if (!refineContext) return;

    if (isDirty) {
      toast.warning(t("workbench.products.detail.refineDirtyBlocked", "请先保存文档后再使用 AI 编辑"));
      return;
    }
    if (hasPendingSession) {
      toast.warning(t("workbench.products.detail.refinePendingBlocked", "请先处理上一次 AI 编辑结果（接受或拒绝）后再使用"));
      return;
    }

    // 直接触发保存文档, 避免后台服务没有临时文档的target, 不需要任何前置条件判断
    if (onSave) {
      await Promise.resolve(onSave(content, { showSaveSuccessToast: false }));
      savedContentRef.current = content;
      setHasOpenedEdit(false);
    }

    const catalog = refineCatalog ?? { llmEndpoints: [], rdSkills: [] };
    const rdSkillIds =
      refineSkills.length > 0 ? refineSkills : catalog.rdSkills.map((s) => s.skillId);

    try {
      await refineProductKnowledge(synapseApiBase, {
        prod_name: refineContext.prod_name,
        doc_type: refineContext.doc_type,
        targets: [refineContext.target],
        user_prompt: prompt.trim(),
        preferred_endpoint: refineEndpoint.trim() || undefined,
        rd_skill_ids: rdSkillIds.length > 0 ? rdSkillIds : undefined,
        product_desc: refineContext.product_desc,
        code_path: refineContext.code_path,
        core_features: refineContext.core_features,
        gitnexus_url: refineContext.gitnexus_url,
      });
      setPrompt("");
      setIsRefining(true);
      setRefineStatusText(t("workbench.products.detail.refinePollingPending", "AI 正在处理中，请稍候..."));
      beginRefinePollingLoop();
      toast.info(t("workbench.products.detail.refineSubmitted", "AI 修改任务已提交，正在处理中..."));
    } catch (err) {
      if (err instanceof RefinePendingError) {
        const { pendingInfo } = err;
        const min = pendingInfo?.elapsed_minutes ?? "?";
        const preview = pendingInfo?.user_prompt
          ? `「${String(pendingInfo.user_prompt).slice(0, 40)}」`
          : "";
        const rawMsg = err.message || "";
        if (rawMsg.includes("pending_review") || rawMsg.includes("refine_session_pending_review")) {
          toast.warning(
            t(
              "workbench.products.detail.refinePendingReviewBlocked",
              "请先完成上一次对比合入或拒绝后再发起新的 AI 编辑",
            ),
          );
        } else {
          toast.warning(
            t(
              "workbench.products.detail.refineAlreadyRunning",
              "上次修改请求 {{preview}} 正在处理中（已 {{min}} 分钟），请稍候",
              { preview, min },
            ),
          );
        }
        setIsRefining(true);
        setRefineStatusText(t("workbench.products.detail.refinePollingPending", "AI 正在处理中，请稍候..."));
        beginRefinePollingLoop();
        return;
      }
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(t("workbench.products.detail.refineFailed", "文档优化失败") + ": " + msg);
    }
  };

  const handleAcceptDiff = async () => {
    if (!diffResult || !refineContext) return;
    const proposed = diffResult.proposed;
    const fixed = fixMarkdownTableDelimiters(proposed);
    setContent(fixed);

    if (onSave) {
      await Promise.resolve(onSave(fixed, { showSaveSuccessToast: false }));
      savedContentRef.current = fixed;
      setHasOpenedEdit(false);
    }

    const tgt = diffResult.target;
    setDiffResult(null);
    try {
      await productKnowledgeRefineSessionClose(synapseApiBase, {
        prod_name: refineContext.prod_name,
        doc_type: refineContext.doc_type,
        target: tgt,
      });
    } catch {
      // 关闭失败静默
    }
    toast.success(t("workbench.products.detail.refineAccepted", "已接受 AI 修改"));
  };

  const handleRejectDiff = async () => {
    if (!diffResult || !refineContext) return;
    const tgt = diffResult.target;
    setDiffResult(null);
    try {
      await productKnowledgeRefineSessionClose(synapseApiBase, {
        prod_name: refineContext.prod_name,
        doc_type: refineContext.doc_type,
        target: tgt,
      });
    } catch {
      // 关闭失败静默
    }
    toast.info(t("workbench.products.detail.refineRejected", "已放弃 AI 修改"));
  };

  const handleSaveClick = async () => {
    if (!onSave) return;
    setIsSaving(true);
    try {
      const fixed = fixMarkdownTableDelimiters(content);
      await Promise.resolve(
        onSave(fixed, { showSaveSuccessToast: true }),
      );
      savedContentRef.current = fixed;
      setHasOpenedEdit(false);
    } finally {
      setIsSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleRefine();
    }
  };

  // react-markdown 的 code 组件类型与 Excalidraw 嵌入强校验冲突，用窄化实现即可
  const previewOptions = useMemo(() => {
    const map = excalidrawByFileName ?? {};
    return {
      components: {
        img: (props: { src?: string; alt?: string; className?: string }) => {
          const { src, alt, className } = props;
          const base = fileNameFromMarkdownSrc(src);
          const lower = base.toLowerCase();
          const raw = base ? getExcalidrawPayload(map, base) : undefined;
          if (lower.endsWith(".excalidraw") && base && raw) {
            try {
              parseExcalidrawFileToInitialData(raw);
              return (
                <div
                  className="my-4 w-full min-w-0 overflow-hidden rounded-md border bg-background"
                  style={EXCALIDRAW_PREVIEW_FRAME_STYLE}
                >
                  <ExcalidrawReadonlyEmbed sceneJson={raw} className="h-full" />
                </div>
              );
            } catch {
              return (
                <div className="my-4 p-4 border border-amber-200 bg-amber-50 text-amber-800 rounded-md text-sm">
                  {t("workbench.products.detail.excalidrawParseError", "无法解析 Excalidraw 文件：{{name}}", {
                    name: base,
                  })}
                </div>
              );
            }
          }
          if (lower.endsWith(".excalidraw") && base) {
            return (
              <div className="my-4 p-3 border border-dashed rounded-md text-sm text-muted-foreground">
                {t("workbench.products.detail.excalidrawMissing", "未加载图形数据：{{name}}", { name: base })}
              </div>
            );
          }
          return <img src={src} alt={alt ?? ""} className={className} />;
        },
        code: (props: { inline?: boolean; className?: string; children?: React.ReactNode }) => {
          const { inline, className, children, ...rest } = props;
          const match = /language-(\w+)/.exec(className || "");
          const lang = match ? match[1] : "";

          if (!inline && lang === "excalidraw") {
            try {
              const data = JSON.parse(String(children).replace(/\n$/, "")) as { elements?: object[] };
              const sceneJson = JSON.stringify(
                applyAppThemeToExcalidrawInitialData(
                  parseExcalidrawFileToInitialData(
                    JSON.stringify({ elements: data.elements ?? [] }),
                  ),
                  {
                    viewBackground: getExcalidrawViewBackgroundForAppTheme(),
                    excalidrawTheme: excalidrawThemeFromApp(),
                  },
                ),
              );
              return (
                <div
                  className="my-4 w-full min-w-0 overflow-hidden rounded-md border"
                  style={EXCALIDRAW_PREVIEW_FRAME_STYLE}
                >
                  <ExcalidrawReadonlyEmbed sceneJson={sceneJson} className="h-full" />
                </div>
              );
            } catch {
              return (
                <div className="my-4 p-4 border border-red-200 bg-red-50 text-red-600 rounded-md text-sm">
                  Excalidraw 数据解析失败
                </div>
              );
            }
          }

          return (
            <code className={className} {...(rest as object)}>
              {children}
            </code>
          );
        },
      },
    };
  }, [excalidrawByFileName, t, isDark]);

  // ---- diff 面板 ----
  if (diffResult) {
    return (
      <div className="flex flex-col h-full w-full relative">
        {/* Diff 面板 header */}
        <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/10 shrink-0">
          <h3 className="text-sm font-semibold text-foreground">
            {t("workbench.products.detail.refineDiffTitle", "AI 修改对比 — {{target}}", {
              target: diffResult.targets[0] ?? title,
            })}
          </h3>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs border-destructive text-destructive hover:bg-destructive/10"
              onClick={() => void handleRejectDiff()}
            >
              <X size={14} className="mr-1.5" />
              {t("workbench.products.detail.refineReject", "拒绝")}
            </Button>
            <Button
              size="sm"
              className="h-8 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={() => void handleAcceptDiff()}
            >
              <Check size={14} className="mr-1.5" />
              {t("workbench.products.detail.refineAccept", "接受全部")}
            </Button>
          </div>
        </div>
        {/* Monaco DiffEditor */}
        <div className="flex-1 min-h-0">
          <DiffEditor
            original={diffResult.original}
            modified={diffResult.proposed}
            language="markdown"
            theme={isDark ? "vs-dark" : "light"}
            options={{
              renderSideBySide: true,
              wordWrap: "on",
              minimap: { enabled: false },
              fontSize: 13,
              readOnly: true,
              scrollBeyondLastLine: false,
            }}
          />
        </div>
        <div className="shrink-0 px-4 py-1.5 text-xs border-t bg-muted/10 text-muted-foreground">
          {t("workbench.products.detail.refineDiffHint", "左侧为原文，右侧为 AI 修改建议。接受后将更新编辑器内容。")}
        </div>
      </div>
    );
  }

  // ---- 正常编辑器 ----
  return (
    <div className="flex flex-col h-full w-full relative">
      {/* Header Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/10 shrink-0">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <div className="flex items-center gap-2">
          {!readonly && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs"
              onClick={() =>
                setMode((m) => {
                  const next = m === "preview" ? "edit" : "preview";
                  if (next === "edit") setHasOpenedEdit(true);
                  return next;
                })
              }
              disabled={isRefining || isSaving}
            >
              {mode === "preview" ? (
                <>
                  <Edit2 size={14} className="mr-1.5" />
                  {t("workbench.products.detail.modeEdit", "编辑模式")}
                </>
              ) : (
                <>
                  <Eye size={14} className="mr-1.5" />
                  {t("workbench.products.detail.modePreview", "预览模式")}
                </>
              )}
            </Button>
          )}
          {onSave && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs"
              onClick={() => void handleSaveClick()}
              disabled={isRefining || isSaving || readonly}
            >
              {isSaving ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <Save size={14} className="mr-1.5" />
              )}
              {t("common.save", "保存")}
            </Button>
          )}
          {onSubmit && (
            <Button
              variant="default"
              size="sm"
              className="h-8 text-xs bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
              onClick={onSubmit}
              disabled={isRefining || isSaving || readonly || !submitEnabled}
              title={
                !submitEnabled && !readonly
                  ? t(
                      "workbench.products.detail.submitToServerNeedLocalDraft",
                      "请先通过「保存」将文档写入本地缓存后再提交",
                    )
                  : undefined
              }
            >
              <Send size={14} className="mr-1.5" />
              {t("workbench.products.detail.submitToServer", "提交到服务端")}
            </Button>
          )}
        </div>
      </div>

      {isDirty && (
        <div
          className="shrink-0 px-4 py-1.5 text-xs border-b border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
          role="status"
        >
          {t("workbench.products.detail.docUnsavedHint", "文档已修改，尚未保存")}
        </div>
      )}

      {/* Editor Area */}
      <div className="flex-1 min-h-0 relative">
        {mode === "edit" && !readonly ? (
          <div className="h-full w-full py-4 bg-background">
            <Editor
              defaultLanguage="markdown"
              value={content}
              onChange={(val) => setContent(val || "")}
              theme={isDark ? "vs-dark" : "light"}
              options={{
                wordWrap: "on",
                minimap: { enabled: false },
                fontSize: 14,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
                padding: { top: 16, bottom: 16 },
                renderLineHighlight: "none",
                lineDecorationsWidth: 16,
              }}
            />
          </div>
        ) : (
          <MDEditor
            value={fixMarkdownTableDelimiters(content)}
            preview="preview"
            height="100%"
            visibleDragbar={false}
            hideToolbar={true}
            previewOptions={previewOptions as never}
            className="h-full border-none rounded-none"
          />
        )}
        
        {/* Overlay when refining / polling */}
        {(isRefining || isPolling) && (
          <div className="absolute inset-0 bg-background/50 backdrop-blur-[1px] flex items-center justify-center z-10">
            <div className="flex flex-col items-center gap-3 bg-background p-6 rounded-lg shadow-lg border">
              <Loader2 size={32} className="animate-spin text-primary" />
              <span className="text-sm font-medium text-foreground">
                {refineStatusText || t("workbench.products.detail.refining", "AI 正在优化文档...")}
              </span>
            </div>
          </div>
        )}
        {isSaving && !isRefining && (
          <div className="absolute inset-0 bg-background/40 backdrop-blur-[1px] flex items-center justify-center z-10">
            <div className="flex flex-col items-center gap-2 bg-background/95 px-5 py-3 rounded-lg shadow-md border text-sm text-muted-foreground">
              <Loader2 size={24} className="animate-spin text-primary" />
              {t("workbench.products.detail.saving", "正在保存...")}
            </div>
          </div>
        )}
      </div>

      {/* AI Refine Input */}
      {!readonly && refineContext && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-20">
          <div className="flex items-center gap-2 bg-background border shadow-lg rounded-full p-1.5 pr-2 focus-within:ring-2 focus-within:ring-primary/20 transition-all">
            {/* 工具配置按钮 */}
            <Button
              type="button"
              variant="outline"
              size="sm"
              title={t("workbench.products.detail.refineConfigTitle", "AI 编辑配置")}
              className="h-8 rounded-full px-3 shrink-0 border-primary/30 text-primary hover:bg-primary/10 hover:border-primary/50"
              onClick={() => {
                setConfigPanelOpen(true);
                onLoadRefineCatalog?.();
              }}
              disabled={isRefining || isPolling || isSaving}
            >
              <Wrench size={14} className="mr-1.5" />
              {t("workbench.products.detail.refineConfigBtn", "工具")}
            </Button>
            <input
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isDirty
                  ? t("workbench.products.detail.refineDirtyPlaceholder", "请先保存文档再使用 AI 编辑")
                  : isPolling
                  ? t("workbench.products.detail.refinePollingPlaceholder", "AI 修改进行中，请等待结果...")
                  : hasPendingSession
                  ? t("workbench.products.detail.refinePendingPlaceholder", "请先处理上次 AI 修改结果")
                  : t("workbench.products.detail.refinePlaceholder", "输入修改需求，AI 自动调整文档...")
              }
              className="flex-1 bg-transparent border-none outline-none text-sm px-2 text-foreground placeholder:text-muted-foreground"
              disabled={isRefining || isPolling || isSaving || isDirty || hasPendingSession}
            />
            <Button
              size="sm"
              className="h-8 rounded-full px-4"
              disabled={!prompt.trim() || isRefining || isPolling || isSaving || isDirty || hasPendingSession}
              onClick={() => void handleRefine()}
            >
              {(isRefining || isPolling) ? <Loader2 size={14} className="animate-spin" /> : t("common.send", "发送")}
            </Button>
          </div>
          {/* 状态提示行 */}
          {(isDirty || hasPendingSession || isPolling) && (
            <div className="mt-1 text-center text-xs text-amber-600 dark:text-amber-400">
              {isDirty
                ? t("workbench.products.detail.refineDirtyBlocked", "请先保存文档后再使用 AI 编辑")
                : isPolling
                ? (refineStatusText || t("workbench.products.detail.refinePollingPending", "AI 正在处理中，请稍候..."))
                : t("workbench.products.detail.refinePendingBlocked", "请先处理上一次 AI 编辑结果（接受或拒绝）后再使用")}
            </div>
          )}
        </div>
      )}

      {/* AI 编辑配置对话框 */}
      <Dialog open={configPanelOpen} onOpenChange={setConfigPanelOpen}>
        <DialogContent className="sm:max-w-md" showCloseButton>
          <DialogHeader>
            <DialogTitle>
              {t("workbench.products.detail.refineConfigTitle", "AI 编辑配置")}
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 py-2">
            {/* LLM 端点 */}
            <div className="grid gap-2">
              <Label className="text-xs font-medium">
                {t("workbench.products.detail.refineConfigEndpoint", "LLM 端点")}
              </Label>
              <select
                className="w-full text-sm border rounded-md px-3 py-1.5 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
                value={refineEndpoint}
                onChange={(e) => setRefineEndpoint(e.target.value)}
              >
                <option value="">{t("workbench.products.detail.refineConfigEndpointAuto", "自动（全局路由）")}</option>
                {(refineCatalog?.llmEndpoints ?? []).map((ep) => (
                  <option key={ep.name} value={ep.name}>
                    {ep.name}{ep.model ? ` (${ep.model})` : ""}
                  </option>
                ))}
              </select>
            </div>

            {/* 研发工具技能 */}
            <div className="grid gap-2">
              <Label className="text-xs font-medium">
                {t("workbench.products.detail.refineConfigSkills", "研发工具技能")}
              </Label>
              {refineCatalog?.rdSkillsLoading ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                  <Loader2 size={12} className="animate-spin" />
                  {t("workbench.products.detail.generateOptionsRdSkillLoading", "加载研发工具列表...")}
                </div>
              ) : (refineCatalog?.rdSkills ?? []).length === 0 ? (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  {t("workbench.products.detail.generateOptionsRdSkillEmpty", "未找到已启用的研发工具技能，请先在「研发工具」页面启用。")}
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {(refineCatalog?.rdSkills ?? []).map((skill) => (
                    <label key={skill.skillId} className="flex items-center gap-2 text-sm cursor-pointer py-0.5">
                      <input
                        type="checkbox"
                        checked={refineSkills.length === 0 || refineSkills.includes(skill.skillId)}
                        onChange={(e) => {
                          const allIds = (refineCatalog?.rdSkills ?? []).map((s) => s.skillId);
                          if (e.target.checked) {
                            setRefineSkills((prev) =>
                              prev.length === 0
                                ? allIds.filter((id) => id !== skill.skillId).concat(skill.skillId)
                                : [...prev, skill.skillId],
                            );
                          } else {
                            setRefineSkills((prev) =>
                              prev.length === 0
                                ? allIds.filter((id) => id !== skill.skillId)
                                : prev.filter((id) => id !== skill.skillId),
                            );
                          }
                        }}
                        className="rounded"
                      />
                      <span>{skill.name || skill.skillId}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button size="sm" onClick={() => setConfigPanelOpen(false)}>
              {t("common.confirm", "确定")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
