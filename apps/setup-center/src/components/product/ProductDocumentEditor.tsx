import React, { useState, useMemo, useEffect } from "react";
import MDEditor from "@uiw/react-md-editor";
import { Editor } from "@monaco-editor/react";
import { Button } from "@/components/ui/button";
import { ExcalidrawReadonlyEmbed } from "./ExcalidrawReadonlyEmbed";
import {
  applyAppThemeToExcalidrawInitialData,
  excalidrawThemeFromApp,
  getExcalidrawViewBackgroundForAppTheme,
  getExcalidrawPayload,
  parseExcalidrawFileToInitialData,
} from "./excalidrawScene";
import { Sparkles, Loader2, Send, Save, Eye, Edit2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { refineProductKnowledge } from "@/api/rdUnifiedService";

/** Markdown 中 `![...](foo.excalidraw)` 的 foo.excalidraw 原文 JSON（多文件时按文件名查） */
interface ProductDocumentEditorProps {
  content: string;
  title: string;
  synapseApiBase: string;
  excalidrawByFileName?: Record<string, string>;
  readonly?: boolean;
  onSave?: (content: string) => void;
  onSubmit?: () => void;
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

export function ProductDocumentEditor({
  content: initialContent,
  title,
  synapseApiBase,
  excalidrawByFileName,
  readonly = false,
  onSave,
  onSubmit,
}: ProductDocumentEditorProps) {
  const { t } = useTranslation();
  const [content, setContent] = useState(() => fixMarkdownTableDelimiters(initialContent));
  const [prompt, setPrompt] = useState("");
  const [isRefining, setIsRefining] = useState(false);
  const [mode, setMode] = useState<"edit" | "preview">("preview");

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
    setContent(fixMarkdownTableDelimiters(initialContent));
  }, [initialContent]);

  const handleRefine = async () => {
    if (!prompt.trim() || isRefining) return;
    
    setIsRefining(true);
    try {
      const res = await refineProductKnowledge(synapseApiBase, {
        content,
        prompt: prompt.trim(),
      });
      setContent(res.content);
      setPrompt("");
      toast.success(t("workbench.products.detail.refineSuccess", "文档优化成功"));
      if (onSave) onSave(res.content);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(t("workbench.products.detail.refineFailed", "文档优化失败") + ": " + msg);
    } finally {
      setIsRefining(false);
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
                  style={{ height: "400px" }}
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
                  style={{ height: "400px" }}
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
              onClick={() => setMode(m => m === "preview" ? "edit" : "preview")}
              disabled={isRefining}
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
              onClick={() => onSave(fixMarkdownTableDelimiters(content))}
              disabled={isRefining || readonly}
            >
              <Save size={14} className="mr-1.5" />
              {t("common.save", "保存")}
            </Button>
          )}
          {onSubmit && (
            <Button
              variant="default"
              size="sm"
              className="h-8 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={onSubmit}
              disabled={isRefining || readonly}
            >
              <Send size={14} className="mr-1.5" />
              {t("workbench.products.detail.submitToServer", "提交到服务端")}
            </Button>
          )}
        </div>
      </div>

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
        
        {/* Overlay when refining */}
        {isRefining && (
          <div className="absolute inset-0 bg-background/50 backdrop-blur-[1px] flex items-center justify-center z-10">
            <div className="flex flex-col items-center gap-3 bg-background p-6 rounded-lg shadow-lg border">
              <Loader2 size={32} className="animate-spin text-primary" />
              <span className="text-sm font-medium text-foreground">
                {t("workbench.products.detail.refining", "AI 正在优化文档...")}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* AI Refine Input */}
      {!readonly && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-20">
          <div className="flex items-center gap-2 bg-background border shadow-lg rounded-full p-1.5 pr-2 focus-within:ring-2 focus-within:ring-primary/20 transition-all">
            <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10 text-primary shrink-0">
              <Sparkles size={16} />
            </div>
            <input
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("workbench.products.detail.refinePlaceholder", "输入修改需求，AI 自动调整文档...")}
              className="flex-1 bg-transparent border-none outline-none text-sm px-2 text-foreground placeholder:text-muted-foreground"
              disabled={isRefining}
            />
            <Button
              size="sm"
              className="h-8 rounded-full px-4"
              disabled={!prompt.trim() || isRefining}
              onClick={handleRefine}
            >
              {isRefining ? <Loader2 size={14} className="animate-spin" /> : t("common.send", "发送")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}