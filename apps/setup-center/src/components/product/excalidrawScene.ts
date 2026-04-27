/** 当前是否为应用「暗色」系主题（与 styles.css 中各 dark 变体一致） */
export function isAppThemeDarkMode(): boolean {
  if (typeof document === "undefined") return false;
  const t = document.documentElement.getAttribute("data-theme") || "light";
  return t === "dark" || t === "daltonized-dark" || t === "high-contrast";
}

/**
 * 画布底与主界面一致：亮色为白，暗色用透明（让容器背景透出，避免 Excalidraw 的 dark mode filter 将深色反转为白色/浅灰）
 */
export function getExcalidrawViewBackgroundForAppTheme(): string {
  if (typeof document === "undefined") return "#ffffff";
  if (!isAppThemeDarkMode()) return "#ffffff";
  // 在暗色模式下，Excalidraw 会对画布应用 filter: invert(93%) hue-rotate(180deg)
  // 如果这里传入了深色（例如 --bg-app 的 #09090b），它反而会被反转成近乎白色的浅灰。
  // 所以我们传入 "transparent"，利用外层容器的背景色（bg-background）来提供正确的暗色底。
  return "transparent";
}

export function excalidrawThemeFromApp(): "light" | "dark" {
  return isAppThemeDarkMode() ? "dark" : "light";
}

/** 预览中强制与当前应用主题对齐（覆盖文件内原 canvas 背景/主题，避免白底在暗色界面刺眼） */
export function applyAppThemeToExcalidrawInitialData(
  data: {
    elements: never;
    appState: never;
    files?: never;
  },
  opts: { viewBackground: string; excalidrawTheme: "light" | "dark" },
) {
  const prev = (data.appState as Record<string, unknown> | null) ?? {};
  return {
    ...data,
    appState: {
      ...prev,
      viewBackgroundColor: opts.viewBackground,
      theme: opts.excalidrawTheme,
    } as never,
  };
}

/** 将 .excalidraw 文件 JSON 解析为给 Excalidraw 的 initialData（含 elements、appState、files 以支持贴图等） */
export function parseExcalidrawFileToInitialData(text: string) {
  const data = JSON.parse(text) as {
    elements?: object[];
    appState?: Record<string, unknown>;
    files?: Record<string, unknown>;
  };
  const srcApp = data.appState && typeof data.appState === "object" ? { ...data.appState } : {};
  const out: {
    elements: never;
    appState: never;
    files?: never;
  } = {
    elements: (data.elements ?? []) as never,
    appState: srcApp as never,
  };
  if (data.files && typeof data.files === "object" && Object.keys(data.files).length > 0) {
    out.files = data.files as never;
  }
  return out;
}

export function getExcalidrawPayload(
  byFile: Record<string, string>,
  fileName: string,
): string | undefined {
  if (byFile[fileName] != null) return byFile[fileName];
  const want = fileName.toLowerCase();
  for (const k of Object.keys(byFile)) {
    if (k.toLowerCase() === want) return byFile[k];
  }
  return undefined;
}
