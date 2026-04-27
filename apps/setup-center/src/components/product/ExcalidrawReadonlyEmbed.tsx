import React, { lazy, memo, Suspense, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  applyAppThemeToExcalidrawInitialData,
  excalidrawThemeFromApp,
  getExcalidrawViewBackgroundForAppTheme,
  parseExcalidrawFileToInitialData,
} from "./excalidrawScene";

const Excalidraw = lazy(() =>
  import("@excalidraw/excalidraw").then((m) => ({ default: m.Excalidraw })),
);

const PREVIEW_UI_OPTIONS = {
  canvasActions: {
    changeViewBackgroundColor: false,
    clearCanvas: false,
    export: false,
    loadScene: false,
    saveToActiveFile: false,
    saveAsImage: false,
    toggleTheme: false,
  },
} as const;

type ExcalidrawReadonlyContentProps = {
  /** 原始 .excalidraw 文件 JSON 字符串，用于稳定 memo 与 useMemo 解析 */
  sceneJson: string;
  /** `data-theme` 变化时递增，使 initialData/组件 theme 与主应用同步 */
  themeRevision: number;
};

function ExcalidrawReadonlyContent({ sceneJson, themeRevision }: ExcalidrawReadonlyContentProps) {
  const { initialData, uiTheme } = useMemo(() => {
    const parsed = parseExcalidrawFileToInitialData(sceneJson);
    const viewBackground = getExcalidrawViewBackgroundForAppTheme();
    const excalidrawTheme = excalidrawThemeFromApp();
    return {
      initialData: applyAppThemeToExcalidrawInitialData(parsed, {
        viewBackground,
        excalidrawTheme,
      }),
      uiTheme: excalidrawTheme,
    };
  }, [sceneJson, themeRevision]);
  return (
    <Excalidraw
      initialData={initialData}
      theme={uiTheme}
      viewModeEnabled
      zenModeEnabled
      UIOptions={PREVIEW_UI_OPTIONS}
      renderTopRightUI={() => null}
    />
  );
}

const ExcalidrawReadonlyContentMemo = memo(
  ExcalidrawReadonlyContent,
  (a, b) => a.sceneJson === b.sceneJson && a.themeRevision === b.themeRevision,
);

/**
 * 只读 Excalidraw 预览：懒加载包体、关 Canvas 操作菜单、全量依赖入口已引入的 index.css。
 */
type ExcalidrawReadonlyEmbedProps = {
  /** 原始 .excalidraw 文件 JSON 字符串 */
  sceneJson: string;
  className?: string;
};

export function ExcalidrawReadonlyEmbed({ sceneJson, className }: ExcalidrawReadonlyEmbedProps) {
  const [themeRevision, setThemeRevision] = useState(0);
  useEffect(() => {
    const el = document.documentElement;
    const bump = () => setThemeRevision((k) => k + 1);
    const obs = new MutationObserver(bump);
    obs.observe(el, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  return (
    <div
      className={cn(
        "excalidraw-embed-host w-full min-w-0 h-full min-h-0 flex flex-col overflow-hidden bg-background",
        className,
      )}
    >
      <Suspense
        fallback={
          <div
            className="flex h-full min-h-[200px] w-full flex-1 items-center justify-center text-muted-foreground"
            aria-hidden
          >
            <Loader2 className="h-6 w-6 shrink-0 animate-spin" />
          </div>
        }
      >
        <div className="excalidraw-embed-inner flex min-h-0 min-w-0 flex-1 flex-col">
          <ExcalidrawReadonlyContentMemo sceneJson={sceneJson} themeRevision={themeRevision} />
        </div>
      </Suspense>
    </div>
  );
}
