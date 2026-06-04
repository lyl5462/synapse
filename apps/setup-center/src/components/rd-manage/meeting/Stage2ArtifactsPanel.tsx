/**
 * 需求设计阶段产出物：顶部多文件切换 · 左侧 Markdown 文档目录 · 右侧可滚动正文
 */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { message } from 'antd';
import { FileText, ListOrdered, Loader2 } from 'lucide-react';

import { fetchArtifactFile, type SolutionReviewArtifactInput } from '../../../api/meetingRoomService';
import {
  collectMarkdownHeadingsFromDom,
  ReviewMarkdown,
  type MarkdownHeading,
} from './ReviewMarkdown';

function fileNameFromPath(relativePath: string, fallback: string): string {
  const norm = relativePath.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/^\/+/, '');
  const idx = norm.lastIndexOf('/');
  return idx < 0 ? norm || fallback : norm.slice(idx + 1) || fallback;
}

interface ArtifactFileEntry {
  relative_path: string;
  fileName: string;
  meta: SolutionReviewArtifactInput;
}

const MarkdownDocToc: React.FC<{
  headings: MarkdownHeading[];
  onJump: (heading: MarkdownHeading) => void;
}> = ({ headings, onJump }) => {
  const items = headings.filter((h) => h.level >= 1 && h.level <= 6);
  if (!items.length) {
    return (
      <p className="px-3 py-6 text-[12px] text-muted-foreground leading-relaxed">
        当前文档未解析到标题，无法生成目录。
      </p>
    );
  }
  return (
    <ul className="rd-stage2-toc__list">
      {items.map((h, i) => (
        <li key={`${h.slug}-${i}`}>
          <button
            type="button"
            className="rd-stage2-toc__item"
            style={{ paddingLeft: `${8 + (h.level - 1) * 12}px` }}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onJump(h);
            }}
            title={h.text}
          >
            <span className="rd-stage2-toc__level">H{h.level}</span>
            <span className="truncate">{h.text}</span>
          </button>
        </li>
      ))}
    </ul>
  );
};

export const Stage2ArtifactsPanel: React.FC<{
  artifacts: SolutionReviewArtifactInput[] | undefined;
  synapseApiBase: string;
  roomId: string;
}> = ({ artifacts, synapseApiBase, roomId }) => {
  const entries = useMemo(() => {
    const list = (artifacts ?? []).filter((a) => a.included !== false && a.relative_path);
    return list.map((meta) => {
      const relative_path = String(meta.relative_path).trim();
      return {
        relative_path,
        fileName: fileNameFromPath(relative_path, meta.artifact || relative_path),
        meta,
      } satisfies ArtifactFileEntry;
    });
  }, [artifacts]);

  const [activePath, setActivePath] = useState<string | null>(null);
  const [contentByPath, setContentByPath] = useState<Record<string, string>>({});
  const [loadingPath, setLoadingPath] = useState<string | null>(null);
  const previewRef = useRef<HTMLDivElement>(null);

  const activeEntry = useMemo(
    () => entries.find((e) => e.relative_path === activePath) ?? null,
    [entries, activePath],
  );

  const content = activePath ? contentByPath[activePath] ?? '' : '';
  const loading = Boolean(activePath && loadingPath === activePath);
  const [tocHeadings, setTocHeadings] = useState<MarkdownHeading[]>([]);

  useEffect(() => {
    if (!entries.length) {
      setActivePath(null);
      return;
    }
    if (!activePath || !entries.some((e) => e.relative_path === activePath)) {
      setActivePath(entries[0].relative_path);
    }
  }, [entries, activePath]);

  useEffect(() => {
    if (!activePath || !synapseApiBase || !roomId) return;
    if (contentByPath[activePath] !== undefined) return;

    let cancelled = false;
    setLoadingPath(activePath);
    void fetchArtifactFile(synapseApiBase, roomId, activePath)
      .then((file) => {
        if (!cancelled) {
          setContentByPath((prev) => ({ ...prev, [activePath]: file.content }));
        }
      })
      .catch(() => {
        if (!cancelled) message.error('无法读取产出物');
      })
      .finally(() => {
        if (!cancelled) setLoadingPath(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activePath, synapseApiBase, roomId, contentByPath]);

  useLayoutEffect(() => {
    if (loading) {
      setTocHeadings([]);
      return;
    }
    const root = previewRef.current;
    if (!root) return;
    const refreshToc = () => setTocHeadings(collectMarkdownHeadingsFromDom(root));
    refreshToc();
    const frame = requestAnimationFrame(refreshToc);
    return () => cancelAnimationFrame(frame);
  }, [content, loading, activePath]);

  const jumpToHeading = useCallback((heading: MarkdownHeading) => {
    const container = previewRef.current;
    if (!container) return;

    const headingNodes = container.querySelectorAll('h1,h2,h3,h4,h5,h6');
    let el: HTMLElement | null = null;

    if (heading.index >= 0 && heading.index < headingNodes.length) {
      el = headingNodes[heading.index] as HTMLElement;
    }
    if (!el && heading.slug) {
      try {
        el = container.querySelector(`#${CSS.escape(heading.slug)}`) as HTMLElement | null;
      } catch {
        el = null;
      }
    }
    if (!el && heading.text) {
      for (const node of headingNodes) {
        if ((node.textContent || '').trim() === heading.text) {
          el = node as HTMLElement;
          break;
        }
      }
    }
    if (!el) return;

    const top =
      el.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop -
      12;
    container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  }, []);

  if (!entries.length) {
    return (
      <div className="rounded-xl border border-dashed border-border/50 px-6 py-10 text-center text-muted-foreground text-sm">
        暂无已纳入评审的需求设计产出物
      </div>
    );
  }

  return (
    <div className="rd-stage2-artifacts">
      <header className="rd-stage2-artifacts__file-tabs-wrap">
        <span className="rd-stage2-artifacts__file-tabs-label">文档</span>
        <div className="rd-stage2-artifacts__file-tabs custom-scrollbar">
          {entries.map((e) => {
            const selected = e.relative_path === activePath;
            return (
              <button
                key={e.relative_path}
                type="button"
                className={`rd-stage2-artifacts__file-tab ${selected ? 'rd-stage2-artifacts__file-tab--active' : ''}`}
                onClick={() => setActivePath(e.relative_path)}
                title={e.relative_path}
              >
                <FileText className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate max-w-[200px]">{e.fileName}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div className="rd-stage2-artifacts__body">
        <aside className="rd-stage2-artifacts__sidebar">
          <div className="rd-stage2-artifacts__sidebar-label">
            <ListOrdered className="h-3.5 w-3.5 inline mr-1 opacity-70" />
            文档目录
          </div>
          <div className="rd-stage2-artifacts__toc custom-scrollbar">
            {loading ? (
              <p className="px-3 py-8 text-center text-[12px] text-muted-foreground">加载目录中…</p>
            ) : (
              <MarkdownDocToc headings={tocHeadings} onJump={jumpToHeading} />
            )}
          </div>
        </aside>

        <main className="rd-stage2-artifacts__preview">
          <div className="rd-stage2-artifacts__preview-label">正文</div>
          <div ref={previewRef} className="rd-stage2-artifacts__preview-body custom-scrollbar">
            {loading ? (
              <div className="flex min-h-[240px] items-center justify-center gap-2 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin text-cyan-400" />
                正在加载…
              </div>
            ) : (
              <ReviewMarkdown key={activePath ?? 'doc'} content={content} compact />
            )}
          </div>
        </main>
      </div>
    </div>
  );
};
