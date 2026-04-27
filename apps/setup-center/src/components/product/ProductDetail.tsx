import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  GitBranch,
  GitMerge,
  FileText,
  Book,
  ClipboardList,
  Package,
  ExternalLink,
  Code2,
  Network,
  Share2,
  Maximize2,
  Layers,
  FileArchive,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Zap,
  Sparkles,
  Loader2,
  AlertCircle,
} from "lucide-react";
import {
  Product,
  type ProductKnowledgeCategory,
  type ProductKnowledgePatch,
  type UnifiedWireAnalysisState,
  isProductKnowledgeSlotDone,
  unifiedDocTypeForKnowledgeCategory,
  UNIFIED_SERVICE_DOC_TYPE,
  PRODUCT_KNOWLEDGE_KEYS,
  knowledgeFromDocProcess,
  productKnowledgeCategoryFromDocTypeWire,
} from "./types";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { IS_TAURI, proxyFetch } from "@/platform";
import { isWhalecloudDevToolSkill } from "@/utils/whalecloudDevToolSkill";
import type { SkillInfo } from "@/types";
import { ProductDocumentEditor } from "./ProductDocumentEditor";
import {
  buildCodeGraphEmbedUrl,
  buildTicketKnowledgeGraphEmbedUrl,
  CODE_GRAPH_VIEWER_PORT,
  codeGraphProjectNameFromRepoUrl,
  getDevserviceHost,
  getProdProcessInfo,
  gitNexusAnalysis,
  gitNexusInitialize,
  orderInitialize,
  docsInitialize,
  docsSubmit,
  getProdDoc,
  generateProductKnowledge,
  getProductKnowledgeStatus,
  fetchLlmEndpointsCatalog,
  probeUnifiedServicePortReachable,
  TICKET_KNOWLEDGE_GRAPH_PORT,
  CODE_GRAPH_SERVER_PORT,
  unifiedServiceHostAuthority,
} from "@/api/rdUnifiedService";
import type { ProdProcessDataPayload } from "@/api/rdUnifiedService";
import { assertOwnerInfoMatchesProduct, toastOwnerInfoGuardError } from "@/utils/ownerInfoGuard";
import "./product-workbench.css";

/**
 * 详情页单一节拍：先 get_prod_process_info，再仅对 I/P 且未在「已终态 task」集合中的行调用
 * product_knowledge/status。与列表页仅用 get_prod_info 区分。
 */
const PRODUCT_DETAIL_POLL_MS = 30_000;

type OpenProductDoc = {
  id: string;
  title: string;
  content: string;
  category: string;
  readonly?: boolean;
  excalidrawByFileName?: Record<string, string>;
};

function isExcalidrawOutputDocName(docName: string): boolean {
  return docName.trim().toLowerCase().endsWith(".excalidraw");
}

/** 与 Synapse/仓库约定文件名一致，供 Markdown 中 `![](*.excalidraw)` 查表 */
function excalidrawByFileNameFromArch(arch: {
  sys_arch_layers_excalidraw?: string;
  tech_stack_excalidraw?: string;
}): Record<string, string> | undefined {
  const m: Record<string, string> = {};
  const a = (arch.sys_arch_layers_excalidraw ?? "").trim();
  if (a) m["sys-arch-layers.excalidraw"] = arch.sys_arch_layers_excalidraw as string;
  const b = (arch.tech_stack_excalidraw ?? "").trim();
  if (b) m["tech-stack.excalidraw"] = arch.tech_stack_excalidraw as string;
  return Object.keys(m).length > 0 ? m : undefined;
}

function archMarkdownDocsFromSynapseData(
  categoryKey: string,
  arch: {
    functional_arch?: string;
    tech_arch?: string;
    sys_arch_layers_excalidraw?: string;
    tech_stack_excalidraw?: string;
  },
): OpenProductDoc[] {
  const exMap = excalidrawByFileNameFromArch(arch);
  const newDocs: OpenProductDoc[] = [];
  const ts = Date.now();
  if (arch.functional_arch) {
    newDocs.push({
      id: `doc-${categoryKey}-func-${ts}`,
      title: "FUNCTIONAL_ARCH.md",
      content: arch.functional_arch,
      category: categoryKey,
      ...(exMap ? { excalidrawByFileName: { ...exMap } } : {}),
    });
  }
  if (arch.tech_arch) {
    newDocs.push({
      id: `doc-${categoryKey}-tech-${ts + 1}`,
      title: "TECH_ARCH.md",
      content: arch.tech_arch,
      category: categoryKey,
      ...(exMap ? { excalidrawByFileName: { ...exMap } } : {}),
    });
  }
  return newDocs;
}

interface ProductDetailProps {
  product: Product | null;
  open: boolean;
  onClose: () => void;
  synapseApiBase: string;
  onProcessPayload: (productId: string, payload: ProdProcessDataPayload) => void;
  /** 提交或本地补全后更新产品 knowledge 各类型 slot，避免直接修改 props */
  onPatchProductKnowledge?: (productId: string, patch: ProductKnowledgePatch) => void;
}

type KnowledgeCategoryViewState = { expanded: boolean; generating: boolean };

function initialKnowledgeCategoryViewState(): Record<
  ProductKnowledgeCategory,
  KnowledgeCategoryViewState
> {
  return {
    architecture: { expanded: false, generating: false },
    solution: { expanded: false, generating: false },
    requirements: { expanded: false, generating: false },
    manual: { expanded: false, generating: false },
    delivery: { expanded: false, generating: false },
  };
}

function detailWireBadgeClass(u: UnifiedWireAnalysisState): string {
  switch (u) {
    case "done":
      return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
    case "error":
      return "bg-red-500/10 text-red-700 dark:text-red-400";
    case "init":
    case "process":
      return "bg-blue-500/10 text-blue-700 dark:text-blue-400";
    case "new":
    default:
      return "bg-muted/30 text-muted-foreground";
  }
}

function detailWireStateLabel(
  t: (k: string) => string,
  u: UnifiedWireAnalysisState,
): string {
  switch (u) {
    case "new":
      return t("workbench.products.detail.analysisNotGenerated");
    case "init":
    case "process":
      return t("workbench.products.detail.analysisGenerating");
    case "error":
      return t("workbench.products.detail.analysisAbnormal");
    case "done":
      return t("workbench.products.detail.analysisDoneLabel");
  }
}

export function ProductDetail({
  product,
  open,
  onClose,
  synapseApiBase,
  onProcessPayload,
  onPatchProductKnowledge,
}: ProductDetailProps) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<string>("code-graph");
  const [openDocs, setOpenDocs] = useState<OpenProductDoc[]>([]);
  const [knowledgeCategoryView, setKnowledgeCategoryView] = useState<
    Record<ProductKnowledgeCategory, KnowledgeCategoryViewState>
  >(() => initialKnowledgeCategoryViewState());
  const [activeRepoIdx, setActiveRepoIdx] = useState<number>(0);
  const [gitnexusBusyIdx, setGitnexusBusyIdx] = useState<number | null>(null);
  const [orderTicketBusy, setOrderTicketBusy] = useState(false);
  const [devserviceHost, setDevserviceHost] = useState<string | null>(null);
  /** null = 探测中；iframe 仅在 true 时挂载，避免不可达时 WebView 内嵌浏览器错误白屏 */
  const [ticketGraphReachable, setTicketGraphReachable] = useState<boolean | null>(null);
  const [ticketGraphProbeNonce, setTicketGraphProbeNonce] = useState(0);
  const [codeGraphReachable, setCodeGraphReachable] = useState<boolean | null>(null);
  const [codeGraphProbeNonce, setCodeGraphProbeNonce] = useState(0);

  const [genOptsOpen, setGenOptsOpen] = useState(false);
  const [genCategoryKey, setGenCategoryKey] = useState<ProductKnowledgeCategory | null>(null);
  const [genRdSkills, setGenRdSkills] = useState<string[]>([]);
  const [genEndpoint, setGenEndpoint] = useState("");
  const [llmEpCatalog, setLlmEpCatalog] = useState<{ name: string; model?: string }[]>([]);
  const [llmEpCatalogErr, setLlmEpCatalogErr] = useState<string | null>(null);
  const [rdSkillCatalog, setRdSkillCatalog] = useState<{ skillId: string; name: string }[]>([]);
  const [rdSkillCatalogLoading, setRdSkillCatalogLoading] = useState(false);

  const productRef = useRef(product);
  productRef.current = product;

  /** 本页已用 get_doc 拉取过「统一服务 done」文档的产品 id（每开一次详情至多串行拉一轮） */
  const hydratedUnifiedDoneForOpenRef = useRef<string | null>(null);
  /**
   * 本页会话内已对 product_knowledge/status 得到终态的 task_id（completed / error，来自 doc_process_info）。
   * 命中后不再请求 status，避免与 get_prod_process_info 同节拍下的重复探测。
   */
  const synapseGenCompletedHydratedRef = useRef<Set<string>>(new Set());

  const guardOwnerMatch = useCallback(async (): Promise<boolean> => {
    const p = productRef.current;
    if (!p || !IS_TAURI) return true;
    try {
      await assertOwnerInfoMatchesProduct(synapseApiBase, p);
      return true;
    } catch (e) {
      toastOwnerInfoGuardError(t, e);
      return false;
    }
  }, [synapseApiBase, t]);

  const fetchProcessOnce = useCallback(async () => {
    const p = productRef.current;
    if (!p || !IS_TAURI) return;
    const prodKey = p.name.trim();
    if (!prodKey) return;
    try {
      const resp = await getProdProcessInfo(synapseApiBase, { prod: prodKey });
      if (resp.data != null) {
        onProcessPayload(p.id, resp.data);

        // 统一服务侧已落库完成（D）：正文只走 get_doc，不用 task_id 问 Synapse
        if (
          hydratedUnifiedDoneForOpenRef.current !== p.id &&
          Array.isArray(resp.data.doc_process) &&
          resp.data.doc_process.length > 0
        ) {
          const kslots = knowledgeFromDocProcess(resp.data.doc_process);
          const doneCats = PRODUCT_KNOWLEDGE_KEYS.filter((k) => kslots[k].wireState === "done");
          if (doneCats.length > 0) {
            hydratedUnifiedDoneForOpenRef.current = p.id;
            for (const cat of doneCats) {
              try {
                const dt = unifiedDocTypeForKnowledgeCategory(cat);
                const items = await getProdDoc(synapseApiBase, { prod: prodKey, doc_type: dt });
                if (items.length === 0) continue;
                const exAssets: Record<string, string> = {};
                const textItems: typeof items = [];
                for (const it of items) {
                  const name = (it.doc_name || "").trim() || "document.md";
                  if (isExcalidrawOutputDocName(name)) {
                    exAssets[name] = it.content;
                  } else {
                    textItems.push(it);
                  }
                }
                const exForMd = Object.keys(exAssets).length > 0 ? exAssets : undefined;
                setOpenDocs((prev) => {
                  const seen = new Set(prev.map((x) => `${x.category}:${x.title}`));
                  const toAdd: OpenProductDoc[] = [];
                  textItems.forEach((it, i) => {
                    const title = (it.doc_name || "").trim() || "document.md";
                    const row: OpenProductDoc = {
                      id: `doc-unified-${cat}-${Date.now()}-${i}`,
                      title,
                      content: it.content,
                      category: cat,
                    };
                    if (exForMd) row.excalidrawByFileName = { ...exForMd };
                    const key = `${row.category}:${row.title}`;
                    if (!seen.has(key)) {
                      seen.add(key);
                      toAdd.push(row);
                    }
                  });
                  return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
                });
              } catch {
                /* 单类失败不阻塞 */
              }
            }
          }
        }

        // 状态探测：仅 I/P 且统一服务回了 doc_process_info 时，才用该 task_id 查 Synapse（与初始化时前端写入的是同一个 id）
        const docProcess = resp.data.doc_process ?? [];
        for (const cat of PRODUCT_KNOWLEDGE_KEYS) {
          const docTypeName = UNIFIED_SERVICE_DOC_TYPE[cat];
          const rows = docProcess.filter((d) => {
            const t = String(d?.doc_type ?? "").toLowerCase();
            return t.includes(docTypeName.toLowerCase()) || docTypeName.toLowerCase().includes(t);
          });
          for (const row of rows) {
            const state = String(row?.doc_process_state ?? "").charAt(0).toUpperCase();
            if (state !== "I" && state !== "P") continue;
            const taskIdFromUnified = String(
              (row as { doc_process_info?: string | null }).doc_process_info ?? "",
            ).trim();
            if (!taskIdFromUnified) continue;
            if (synapseGenCompletedHydratedRef.current.has(taskIdFromUnified)) continue;

            // 计算耗时：doc_process_time 为开始时间，若无则暂不显示
            let elapsed = "";
            const startTimeStr = row.doc_process_time;
            if (startTimeStr) {
              const startMs = new Date(startTimeStr).getTime();
              if (!isNaN(startMs)) {
                const diffSec = Math.floor((Date.now() - startMs) / 1000);
                if (diffSec < 60) {
                  elapsed = `${diffSec}秒`;
                } else {
                  const m = Math.floor(diffSec / 60);
                  const s = diffSec % 60;
                  elapsed = `${m}分${s > 0 ? s + "秒" : ""}`;
                }
              }
            }

            try {
              const statusRes = await getProductKnowledgeStatus(
                synapseApiBase,
                taskIdFromUnified,
              );
              if (statusRes.status === "running" || statusRes.status === "pending") {
                toast.info(
                  t("workbench.products.detail.generateProgress", {
                    product: p.name,
                    docType: docTypeName,
                    elapsed: elapsed || "计算中",
                  }),
                  { id: `gen-progress-${taskIdFromUnified}`, duration: 5000 },
                );
              } else if (statusRes.status === "completed") {
                synapseGenCompletedHydratedRef.current.add(taskIdFromUnified);
                const categoryKey =
                  productKnowledgeCategoryFromDocTypeWire(String(row?.doc_type ?? "")) ?? cat;
                if (statusRes.data) {
                  const newDocs = archMarkdownDocsFromSynapseData(categoryKey, statusRes.data);
                  if (newDocs.length > 0) {
                    setOpenDocs((prev) => [...prev, ...newDocs]);
                    setActiveTab(newDocs[0].id);
                    setKnowledgeCategoryView((prev) => ({
                      ...prev,
                      [categoryKey]: { ...prev[categoryKey], expanded: true, generating: false },
                    }));
                    toast.success(t("workbench.products.detail.generateSuccess", "文档生成成功"));
                  } else {
                    setKnowledgeCategoryView((prev) => ({
                      ...prev,
                      [categoryKey]: { ...prev[categoryKey], generating: false },
                    }));
                  }
                } else {
                  setKnowledgeCategoryView((prev) => ({
                    ...prev,
                    [categoryKey]: { ...prev[categoryKey], generating: false },
                  }));
                }
              } else if (statusRes.status === "error") {
                synapseGenCompletedHydratedRef.current.add(taskIdFromUnified);
                const categoryKey =
                  productKnowledgeCategoryFromDocTypeWire(String(row?.doc_type ?? "")) ?? cat;
                setKnowledgeCategoryView((prev) => ({
                  ...prev,
                  [categoryKey]: { ...prev[categoryKey], generating: false },
                }));
                toast.error(
                  t("workbench.products.detail.generateFailed", "文档生成失败") +
                    (statusRes.error ? `: ${statusRes.error}` : ""),
                  { id: `gen-err-${taskIdFromUnified}` },
                );
              }
            } catch {
              // 查询后台进度失败不影响主流程
            }
          }
        }
      }
    } catch {
      /* 轮询失败静默，避免打扰 */
    }
  }, [synapseApiBase, onProcessPayload, t]);

  useEffect(() => {
    if (open && product) {
      setActiveTab("code-graph");
      setOpenDocs([]);
      setKnowledgeCategoryView(initialKnowledgeCategoryViewState());
      hydratedUnifiedDoneForOpenRef.current = null;
      synapseGenCompletedHydratedRef.current.clear();
      const mainIdx = product.repositories.findIndex((r) => r.isMain);
      setActiveRepoIdx(mainIdx >= 0 ? mainIdx : 0);
    }
    // 仅打开或切换产品时重置视图；勿依赖整个 product，避免详情内轮询更新过程字段时打断当前 Tab
  }, [open, product?.id]);

  useEffect(() => {
    if (!open || !product || !IS_TAURI) return;
    void fetchProcessOnce();
    const id = window.setInterval(() => void fetchProcessOnce(), PRODUCT_DETAIL_POLL_MS);
    return () => window.clearInterval(id);
  }, [open, product?.id, fetchProcessOnce]);

  useEffect(() => {
    if (!open || !IS_TAURI) {
      setDevserviceHost(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      const h = await getDevserviceHost();
      if (!cancelled) setDevserviceHost(h);
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const codeGraphIframeSrc = useMemo(() => {
    if (!product || !IS_TAURI || !devserviceHost) return null;
    const repo = product.repositories[activeRepoIdx];
    const url = repo?.url?.trim() ?? "";
    if (!url) return null;
    const proj = codeGraphProjectNameFromRepoUrl(url, repo?.branch ?? "");
    if (!proj) return null;
    return buildCodeGraphEmbedUrl(devserviceHost, proj);
  }, [product, activeRepoIdx, devserviceHost]);

  const ticketGraphIframeSrc = useMemo(() => {
    if (!product || !IS_TAURI || !devserviceHost) return null;
    const prodKey = product.name.trim();
    if (!prodKey) return null;
    return buildTicketKnowledgeGraphEmbedUrl(devserviceHost, prodKey);
  }, [product, devserviceHost]);

  useEffect(() => {
    if (!open || !IS_TAURI || activeTab !== "code-graph") return;
    const p = productRef.current;
    if (!p) return;
    const repo = p.repositories[activeRepoIdx];
    const wireU = repo?.wireAnalysisState ?? "new";
    if (wireU !== "done") {
      setCodeGraphReachable(null);
      return;
    }
    if (!codeGraphIframeSrc || !devserviceHost) {
      setCodeGraphReachable(null);
      return;
    }
    let cancelled = false;
    setCodeGraphReachable(null);
    void (async () => {
      const ok = await probeUnifiedServicePortReachable(devserviceHost, CODE_GRAPH_VIEWER_PORT);
      if (!cancelled) setCodeGraphReachable(ok);
    })();
    return () => {
      cancelled = true;
    };
  }, [
    open,
    activeTab,
    activeRepoIdx,
    codeGraphIframeSrc,
    devserviceHost,
    codeGraphProbeNonce,
    product?.repositories?.[activeRepoIdx]?.wireAnalysisState,
    product?.id,
  ]);

  useEffect(() => {
    if (!open || !IS_TAURI || activeTab !== "ticket-graph") return;
    const p = productRef.current;
    const ticketU = p?.analysisUnified?.ticket ?? "new";
    if (ticketU !== "done") {
      setTicketGraphReachable(null);
      return;
    }
    if (!ticketGraphIframeSrc || !devserviceHost) {
      setTicketGraphReachable(null);
      return;
    }
    let cancelled = false;
    setTicketGraphReachable(null);
    void (async () => {
      const ok = await probeUnifiedServicePortReachable(devserviceHost, TICKET_KNOWLEDGE_GRAPH_PORT);
      if (!cancelled) setTicketGraphReachable(ok);
    })();
    return () => {
      cancelled = true;
    };
  }, [
    open,
    activeTab,
    ticketGraphIframeSrc,
    devserviceHost,
    ticketGraphProbeNonce,
    product?.analysisUnified?.ticket,
    product?.id,
  ]);

  const knowledgeItems = useMemo(
    () => [
      { key: "architecture", label: t("workbench.products.detail.knowledgeArch"), icon: <Layers size={14} /> },
      { key: "solution", label: t("workbench.products.detail.knowledgeSolution"), icon: <Book size={14} /> },
      {
        key: "requirements",
        label: t("workbench.products.detail.knowledgeRequirements"),
        icon: <ClipboardList size={14} />,
      },
      { key: "manual", label: t("workbench.products.detail.knowledgeManual"), icon: <FileText size={14} /> },
      { key: "delivery", label: t("workbench.products.detail.knowledgeDelivery"), icon: <Package size={14} /> },
    ],
    [t],
  );

  if (!product) return null;

  const codeU = product.analysisUnified?.code ?? "new";
  const ticketU = product.analysisUnified?.ticket ?? "new";
  const activeRepoForGraph = product.repositories[activeRepoIdx];
  const activeRepoWireU = activeRepoForGraph?.wireAnalysisState ?? "new";
  const activeRepoAnalyzing = activeRepoWireU === "init" || activeRepoWireU === "process";
  /** 主仓库分析完成（done）时，自动生成按钮才可用 */
  const mainRepo = product.repositories.find((r) => r.isMain);
  const mainRepoAnalysisDone = (mainRepo?.wireAnalysisState ?? "new") === "done";
  const architectureKnowledgeDone = isProductKnowledgeSlotDone(product.knowledge.architecture);

  const ticketReqMetric =
    product.demandOrderCount !== undefined
      ? product.demandOrderCount
      : product.latestTickets?.filter((tick) => tick.title.includes("需求")).length ?? 0;
  const ticketDevMetric =
    product.taskOrderCount !== undefined
      ? product.taskOrderCount
      : product.latestTickets?.filter((tick) => !tick.title.includes("需求")).length ?? 0;

  const getMockDocsForCategory = (categoryKey: string, productName: string): OpenProductDoc[] => {
    // 方案和需求为只读
    const isReadonly = categoryKey === "solution" || categoryKey === "requirements";
    return [
      {
        id: `doc-${categoryKey}-1`,
        title: `${productName}-${categoryKey === "architecture" ? "总体设计" : "需求概要"} v1.0`,
        content: `# ${productName} \n\n这是一篇关于 **${categoryKey}** 的技术文档。包含 Markdown 与示意图占位，以便演示混合展示效果。\n\n- 核心特点：高性能、高可用、可扩展\n- 依赖服务：Redis, PostgreSQL`,
        category: categoryKey,
        readonly: isReadonly,
      },
      {
        id: `doc-${categoryKey}-2`,
        title: `迭代日志与附录`,
        content: `# 迭代日志\n目前处于 v1.0.0 版本阶段，持续完善中。`,
        category: categoryKey,
        readonly: isReadonly,
      },
    ];
  };

  const handleOpenDoc = async (doc: OpenProductDoc, category: string) => {
    if (!(await guardOwnerMatch())) return;
    if (!openDocs.find((d) => d.id === doc.id)) {
      setOpenDocs([...openDocs, { ...doc, category }]);
    }
    setActiveTab(doc.id);
  };

  const toggleKnowledgeCategoryExpanded = (key: ProductKnowledgeCategory) => {
    setKnowledgeCategoryView((prev) => ({
      ...prev,
      [key]: { ...prev[key], expanded: !prev[key].expanded },
    }));
  };

  const openGenerateOptionsDialog = (cat: ProductKnowledgeCategory) => {
    setGenCategoryKey(cat);
    setGenRdSkills([]);
    setGenEndpoint("");
    setLlmEpCatalog([]);
    setLlmEpCatalogErr(null);
    setRdSkillCatalog([]);
    setRdSkillCatalogLoading(true);
    setGenOptsOpen(true);
    void (async () => {
      try {
        const rows = await fetchLlmEndpointsCatalog(synapseApiBase);
        setLlmEpCatalog(rows);
      } catch (e) {
        setLlmEpCatalogErr(e instanceof Error ? e.message : String(e));
      }
    })();
    void (async () => {
      try {
        const base = synapseApiBase.replace(/\/$/, "");
        const resp = await proxyFetch(`${base}/api/skills`, { timeoutSecs: 15 });
        const raw = JSON.parse(resp.body) as { skills?: Record<string, unknown>[] };
        const skills: SkillInfo[] = (raw.skills ?? []).map((s) => ({
          skillId: (s.skill_id as string) || (s.name as string) || "",
          name: (s.name as string) || "",
          description: (s.description as string) || "",
          name_i18n: (s.name_i18n as Record<string, string> | null) || null,
          description_i18n: (s.description_i18n as Record<string, string> | null) || null,
          system: !!(s.system as boolean),
          enabled: typeof s.enabled === "boolean" ? s.enabled : undefined,
          toolName: (s.tool_name as string | null) || null,
          category: (s.category as string | null) || null,
          path: (s.path as string | null) || null,
          sourceUrl: (s.source_url as string | null) || null,
        }));
        const devTools = skills
          .filter((s) => isWhalecloudDevToolSkill(s) && s.enabled !== false)
          .map((s) => ({ skillId: s.skillId, name: s.name_i18n?.["zh"] || s.name_i18n?.["en"] || s.name }));
        setRdSkillCatalog(devTools);
      } catch {
        // 加载失败时 catalog 保持空，UI 会提示用户去启用
      } finally {
        setRdSkillCatalogLoading(false);
      }
    })();
  };

  const handleGenerateKnowledge = async (
    categoryKey: string,
    opts?: { rd_skill_ids?: string[]; preferred_endpoint?: string | null },
  ) => {
    if (!product || !IS_TAURI) return;
    if (!(await guardOwnerMatch())) return;

    const mainRepo = product.repositories.find((r) => r.isMain) || product.repositories[0];
    if (!mainRepo) {
      toast.error(t("workbench.products.detail.noMainRepo", "未找到主仓库"));
      return;
    }

    if (!(PRODUCT_KNOWLEDGE_KEYS as readonly string[]).includes(categoryKey)) {
      toast.error(t("workbench.products.detail.generateInvalidCategory", "无效的文档分类"));
      return;
    }
    const cat = categoryKey as ProductKnowledgeCategory;
    setKnowledgeCategoryView((prev) => ({
      ...prev,
      [cat]: { ...prev[cat], generating: true },
    }));
    try {
      const docTypeParam = unifiedDocTypeForKnowledgeCategory(cat);

      const hostRaw = await getDevserviceHost();
      const devserviceAuth = hostRaw ? unifiedServiceHostAuthority(hostRaw) : null;
      if (!devserviceAuth) {
        setKnowledgeCategoryView((prev) => ({
          ...prev,
          [cat]: { ...prev[cat], generating: false },
        }));
        toast.error(
          t(
            "workbench.products.detail.generateMissingDevserviceHost",
            "未获取到产品公共服务主机，无法生成文档。请在引导中完成「产品公共服务」或检查 ~/.synapse/devservice.ip。",
          ),
        );
        return;
      }
      const gitnexusUrl = `http://${devserviceAuth}:${CODE_GRAPH_SERVER_PORT}/`;

      // 初始化：前端生成 task_id（插入键），写入统一服务 + Synapse；后续统一服务在 doc_process_info 回显同一 id
      const taskId = crypto.randomUUID().replace(/-/g, "");
      await docsInitialize(synapseApiBase, {
        prod: product.name,
        doc_type: docTypeParam,
        task_id: taskId,
      });

      // 2. 触发生成
      const rdSkillIds =
        opts?.rd_skill_ids && opts.rd_skill_ids.length > 0
          ? opts.rd_skill_ids.filter((s) => s.trim())
          : ["whalecloud-dev-tool-arch-create"];
      // 从仓库 URL 解析真实仓库名（去掉 .git 后缀的最后一段路径）
      const repoNameFromUrl = mainRepo.url
        ? mainRepo.url.replace(/\/$/, "").split("/").pop()?.replace(/\.git$/i, "") || product.name
        : product.name;

      await generateProductKnowledge(synapseApiBase, {
        task_id: taskId,
        repo_name: repoNameFromUrl,
        repo_url: mainRepo.url || undefined,
        gitnexus_url: gitnexusUrl,
        product_desc: product.description || "",
        code_path: mainRepo.codePath || "",
        core_features: product.features || "",
        rd_skill_ids: rdSkillIds,
        preferred_endpoint:
          opts?.preferred_endpoint != null && String(opts.preferred_endpoint).trim() !== ""
            ? String(opts.preferred_endpoint).trim()
            : undefined,
      });

      toast.success(t("workbench.products.detail.generateStarted", "文档生成任务已启动，请稍候..."));

      // 进度与终态由统一节拍 fetchProcessOnce（get_prod_process_info → 按需 status）处理；此处立即拉一次统一服务
      void fetchProcessOnce();

      // 总超时对齐后端 3600 秒（仅结束本分类 generating，不再单独轮询 status）
      setTimeout(() => {
        setKnowledgeCategoryView((prev) => {
          if (!prev[cat].generating) return prev;
          toast.error(t("workbench.products.detail.generateTimeout", "文档生成超时"));
          return { ...prev, [cat]: { ...prev[cat], generating: false } };
        });
      }, 3600 * 1000);

    } catch (err) {
      setKnowledgeCategoryView((prev) => ({
        ...prev,
        [cat]: { ...prev[cat], generating: false },
      }));
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(t("workbench.products.detail.generateFailed", "文档生成失败") + ": " + msg);
    }
  };

  const handleSubmitDocs = async (categoryKey: string) => {
    if (!product || !IS_TAURI) return;
    
    // 收集当前分类下所有打开的文档
    const categoryDocs = openDocs.filter(d => d.category === categoryKey);
    if (categoryDocs.length === 0) {
      toast.warning(t("workbench.products.detail.noDocsToSubmit", "没有可提交的文档"));
      return;
    }

    try {
      const submitDocType = unifiedDocTypeForKnowledgeCategory(
        categoryKey as ProductKnowledgeCategory,
      );

      const used = new Set<string>();
      const docContent: { doc_name: string; content: string }[] = [];
      for (const d of categoryDocs) {
        if (!used.has(d.title)) {
          used.add(d.title);
          docContent.push({ doc_name: d.title, content: d.content });
        }
        if (d.excalidrawByFileName) {
          for (const [name, exBody] of Object.entries(d.excalidrawByFileName)) {
            if (!exBody.trim() || used.has(name)) continue;
            used.add(name);
            docContent.push({ doc_name: name, content: exBody });
          }
        }
      }

      await docsSubmit(synapseApiBase, {
        prod: product.name,
        doc_type: submitDocType,
        doc_content: docContent,
      });

      toast.success(t("workbench.products.detail.docSubmitSuccess", "文档提交成功"));
      onPatchProductKnowledge?.(product.id, {
        [categoryKey as ProductKnowledgeCategory]: { wireState: "done" },
      });
      void fetchProcessOnce();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(t("workbench.products.detail.docSubmitFailed", "文档提交失败") + ": " + msg);
    }
  };

  return (
    <>
    <Sheet open={open} onOpenChange={(val) => { if (!val) onClose(); }}>
      <SheetContent side="right" className="w-[85vw] sm:max-w-[85vw] p-0 flex flex-col gap-0 border-l border-border/80 bg-background">
        <SheetHeader className="px-6 py-4 border-b border-border/80 bg-muted/10 flex flex-row items-center justify-between space-y-0">
          <SheetTitle className="flex items-center gap-3 font-normal">
            <img src={product.icon} alt="" className="w-7 h-7 rounded" />
            <div className="flex flex-col items-start gap-1">
              <div className="text-base font-semibold text-foreground leading-none">{product.name}</div>
              <div className="text-xs text-muted-foreground font-normal leading-none max-w-md truncate">
                {product.description}
              </div>
            </div>
          </SheetTitle>
          <div className="flex items-center pr-14">
            <Button variant="outline" size="sm" className="h-8">
              <Share2 size={14} className="mr-1.5" />
              {t("workbench.products.detail.share")}
            </Button>
          </div>
        </SheetHeader>

        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Sidebar */}
          <div className="w-[280px] border-r border-border/80 bg-muted/5 flex flex-col gap-6 p-4 overflow-y-auto custom-scrollbar shrink-0">
            {/* Code View */}
            <div>
              <h5 className="text-[13px] font-semibold text-primary uppercase tracking-wider mb-4">
                {t("workbench.products.detail.codeViewTitle")}
              </h5>
              <div className="flex flex-col gap-3">
                {product.repositories.map((repo, idx) => {
                  const isActive = activeTab === "code-graph" && activeRepoIdx === idx;
                  const bgClass = isActive ? "bg-primary/10" : "bg-muted/30";
                  const borderClass = isActive ? "border-primary/30" : "border-border/50";
                  const wireU = repo.wireAnalysisState ?? "new";
                  const doneTime = repo.analysisCompletedAt ?? repo.analysisTime;
                  const isRepoAnalyzing = wireU === "init" || wireU === "process";

                  return (
                    <div
                      key={repo.url || idx}
                      onClick={() => {
                        setActiveTab("code-graph");
                        setActiveRepoIdx(idx);
                      }}
                      className={`p-3 rounded-md border cursor-pointer transition-all relative group ${bgClass} ${borderClass} hover:border-primary/40`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-1.5">
                          <GitBranch size={13} className="text-muted-foreground" />
                          <span className="font-semibold text-foreground text-[13px]">{repo.branch}</span>
                        </div>
                        {repo.isMain && (
                          <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-normal bg-blue-500/10 text-blue-700 dark:text-blue-400">
                            {t("workbench.products.detail.mainRepoTag")}
                          </Badge>
                        )}
                      </div>

                      <div className="mb-2.5">
                        <div className="text-xs text-muted-foreground truncate w-full" title={repo.purpose || t("workbench.products.detail.noPurpose")}>
                          {repo.purpose || t("workbench.products.detail.noPurpose")}
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
                            <Badge
                              variant="secondary"
                              className={`h-5 max-w-full shrink px-1.5 text-[10px] font-normal border-none ${detailWireBadgeClass(wireU)}`}
                            >
                              <span className="truncate">{detailWireStateLabel(t, wireU)}</span>
                            </Badge>
                            {wireU === "done" && doneTime && (
                              <Badge
                                variant="outline"
                                className="h-5 px-1.5 text-[10px] font-normal border-none bg-background/50 text-muted-foreground"
                              >
                                {doneTime}
                              </Badge>
                            )}
                          </div>
                          {wireU !== "new" && (
                            <div className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100">
                              <Button
                                variant="ghost"
                                size="icon"
                                className={`h-6 w-6 ${wireU === "done" ? "text-primary" : "text-muted-foreground"}`}
                                disabled={
                                  wireU !== "done" || gitnexusBusyIdx === idx || !IS_TAURI
                                }
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (wireU !== "done") return;
                                  if (!IS_TAURI) {
                                    toast.message(t("workbench.products.tauriOnlyAction"));
                                    return;
                                  }
                                  const prodKey = product.name.trim();
                                  if (!prodKey) return;
                                  setGitnexusBusyIdx(idx);
                                  void (async () => {
                                    try {
                                      if (!(await guardOwnerMatch())) return;
                                      const resp = await gitNexusAnalysis(synapseApiBase, {
                                        prod: prodKey,
                                        repo_branch: (repo.branch ?? "").trim(),
                                        prod_branch: (repo.prodBranch ?? "").trim(),
                                      });
                                      const msg =
                                        typeof resp.message === "string" && resp.message.trim() !== ""
                                          ? resp.message.trim()
                                          : t("workbench.products.detail.gitnexusInitDefaultSuccess");
                                      toast.success(msg);
                                      await fetchProcessOnce();
                                    } catch (err) {
                                      const msg = err instanceof Error ? err.message : String(err);
                                      toast.error(
                                        t("workbench.products.detail.gitnexusAnalysisFailed", {
                                          message: msg,
                                        }),
                                      );
                                    } finally {
                                      setGitnexusBusyIdx(null);
                                    }
                                  })();
                                }}
                                title={
                                  wireU === "done"
                                    ? t("workbench.products.detail.reanalyze")
                                    : isRepoAnalyzing
                                      ? t("workbench.products.detail.analyzing")
                                      : detailWireStateLabel(t, wireU)
                                }
                              >
                                <RefreshCw
                                  size={12}
                                  className={
                                    isRepoAnalyzing || gitnexusBusyIdx === idx ? "animate-spin" : ""
                                  }
                                />
                              </Button>
                            </div>
                          )}
                        </div>

                        {wireU === "new" && (
                          <div className="mt-2.5" onClick={(e) => e.stopPropagation()}>
                            <Button
                              type="button"
                              disabled={gitnexusBusyIdx === idx || !IS_TAURI}
                              title={t("workbench.products.detail.autoAnalysisCardHint")}
                              className="w-full h-8 gap-1.5 text-xs font-medium bg-gradient-to-r from-primary/10 to-primary/5 hover:from-primary/20 hover:to-primary/10 text-primary border border-primary/20 shadow-sm transition-all rounded-md"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (!IS_TAURI) {
                                  toast.message(t("workbench.products.tauriOnlyAction"));
                                  return;
                                }
                                const prodKey = product.name.trim();
                                if (!prodKey) return;
                                setGitnexusBusyIdx(idx);
                                void (async () => {
                                  try {
                                    if (!(await guardOwnerMatch())) return;
                                    const resp = await gitNexusInitialize(synapseApiBase, {
                                      prod: prodKey,
                                      repo_branch: (repo.branch ?? "").trim(),
                                      prod_branch: (repo.prodBranch ?? "").trim(),
                                    });
                                    const msg =
                                      typeof resp.message === "string" && resp.message.trim() !== ""
                                        ? resp.message.trim()
                                        : t("workbench.products.detail.gitnexusInitDefaultSuccess");
                                    toast.success(msg);
                                    await fetchProcessOnce();
                                  } catch (err) {
                                    const msg = err instanceof Error ? err.message : String(err);
                                    toast.error(t("workbench.products.detail.gitnexusInitFailed", { message: msg }));
                                  } finally {
                                    setGitnexusBusyIdx(null);
                                  }
                                })();
                              }}
                            >
                              <Zap className="size-3.5 shrink-0" strokeWidth={2.5} />
                              {t("workbench.products.detail.autoAnalysisCta")}
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Knowledge View */}
            <div>
              <h5 className="mb-4 text-[13px] font-semibold uppercase tracking-wider text-primary">
                {t("workbench.products.detail.knowledgeViewTitle")}
              </h5>

              <div className="flex flex-col gap-1">
                {knowledgeItems.map((item) => {
                  const cat = item.key as ProductKnowledgeCategory;
                  const slot = product.knowledge[cat];
                  const done = isProductKnowledgeSlotDone(slot);
                  const categoryDocs = openDocs.filter((d) => d.category === cat);
                  const hasGeneratedDocs = categoryDocs.length > 0;
                  const docs = hasGeneratedDocs ? categoryDocs : (done ? getMockDocsForCategory(item.key, product.name) : []);
                  const kv = knowledgeCategoryView[cat];
                  const isExpanded = kv.expanded;
                  const generating = kv.generating;
                  const isArchitecture = item.key === "architecture";
                  const isManual = item.key === "manual";
                  const archDone = isProductKnowledgeSlotDone(product.knowledge.architecture);
                  const canGenerateArchitecture = isArchitecture && !done && mainRepoAnalysisDone;
                  const canGenerateManual = isManual && !done && archDone;
                  const rowActive = done || hasGeneratedDocs || slot.wireState === "init" || slot.wireState === "process";
                  const showGenerateBtn = !done && !hasGeneratedDocs && (canGenerateArchitecture || canGenerateManual);
                  const showDocs = (done || hasGeneratedDocs) && isExpanded;

                  return (
                    <div key={item.key} className="flex flex-col">
                      <div
                        onClick={() => {
                          if (done || hasGeneratedDocs) toggleKnowledgeCategoryExpanded(cat);
                          setActiveTab("knowledge-graph");
                        }}
                        className="flex items-center justify-between w-full cursor-pointer py-2 px-1 hover:bg-muted/50 rounded-md transition-colors"
                      >
                        <div
                          className={`flex items-center gap-2.5 ${rowActive ? "text-foreground" : "text-muted-foreground"}`}
                        >
                          {item.icon}
                          <span className="text-[13px]">{item.label}</span>
                        </div>
                        <div className="flex min-w-0 flex-col items-end gap-0.5">
                          <div className="flex max-w-full flex-wrap items-center justify-end gap-1.5">
                            {showGenerateBtn && (
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="h-6 shrink-0 gap-1 rounded-md border-amber-500/25 bg-gradient-to-r from-amber-500/10 to-orange-500/10 px-2 text-[10px] font-semibold text-amber-700 hover:from-amber-500/15 hover:to-orange-500/15 dark:text-amber-400"
                                disabled={generating}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (canGenerateManual) {
                                    toast.message(t("workbench.products.detail.manualGenerationPlanned", "规划中"));
                                    return;
                                  }
                                  if (canGenerateArchitecture) {
                                    openGenerateOptionsDialog(cat);
                                  }
                                }}
                              >
                                {generating ? (
                                  <Loader2 className="size-3 shrink-0 animate-spin" />
                                ) : (
                                  <Sparkles className="size-3 shrink-0" strokeWidth={2.5} />
                                )}
                                {generating
                                  ? t("workbench.products.detail.generating", "生成中...")
                                  : t("workbench.products.detail.generate", "生成")}
                              </Button>
                            )}
                            {done || hasGeneratedDocs ? (
                              <>
                                <span className="text-[11px] text-emerald-600 dark:text-emerald-400">
                                  {t("workbench.products.detail.docsCount", { count: docs.length })}
                                </span>
                                <ChevronDown
                                  size={14}
                                  className={`shrink-0 text-muted-foreground transition-transform ${isExpanded ? "rotate-180" : ""}`}
                                />
                              </>
                            ) : slot.wireState !== "new" ? (
                              <Badge
                                variant="secondary"
                                className={`h-5 max-w-[140px] shrink px-1.5 text-[10px] font-normal border-none ${detailWireBadgeClass(slot.wireState)}`}
                              >
                                <span className="truncate">{detailWireStateLabel(t, slot.wireState)}</span>
                              </Badge>
                            ) : (
                              <span className="text-[11px] text-muted-foreground">
                                {t("workbench.products.detail.notCreated")}
                              </span>
                            )}
                          </div>
                          {done && slot.completedAt && (
                            <span className="text-[10px] text-muted-foreground tabular-nums">
                              {slot.completedAt}
                            </span>
                          )}
                        </div>
                      </div>

                      {showDocs && (
                        <div className="flex flex-col gap-1 pl-6 py-1">
                          {docs.map((doc) => {
                            const isDocActive = activeTab === doc.id;
                            return (
                              <div
                                key={doc.id}
                                onClick={() => void handleOpenDoc(doc, item.key)}
                                className={`px-3 py-1.5 cursor-pointer rounded-md text-xs flex items-center gap-2 transition-colors ${
                                  isDocActive 
                                    ? "bg-primary/10 border border-primary/20 text-primary" 
                                    : "bg-transparent border border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                                }`}
                              >
                                <FileArchive size={12} className="shrink-0" />
                                <span className="truncate">{doc.title}</span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Ticket View */}
            <div>
              <h5 className="text-[13px] font-semibold text-primary uppercase tracking-wider mb-4">
                {t("workbench.products.detail.ticketViewTitle")}
              </h5>
              <div
                onClick={() => setActiveTab("ticket-graph")}
                className={`p-4 rounded-md border cursor-pointer transition-all ${
                  activeTab === "ticket-graph" ? "bg-primary/10 border-primary/30" : "bg-muted/30 border-border/50 hover:border-border"
                }`}
              >
                <div className="mb-3 flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <ClipboardList
                      size={16}
                      className={activeTab === "ticket-graph" ? "text-primary" : "text-muted-foreground"}
                    />
                    <span className="font-semibold text-foreground text-sm">
                      {t("workbench.products.detail.ticketAnalysisView")}
                    </span>
                  </div>
                  <div className="flex min-w-0 max-w-[55%] flex-col items-end gap-0.5">
                    <Badge
                      variant="secondary"
                      className={`h-5 max-w-full shrink px-1.5 text-[10px] font-normal border-none ${detailWireBadgeClass(product.analysisUnified?.ticket ?? "new")}`}
                    >
                      <span className="truncate">
                        {detailWireStateLabel(t, product.analysisUnified?.ticket ?? "new")}
                      </span>
                    </Badge>
                    {(product.analysisUnified?.ticket ?? "new") === "done" && product.analysisTimes?.ticket && (
                      <span className="text-[10px] text-muted-foreground tabular-nums">
                        {product.analysisTimes.ticket}
                      </span>
                    )}
                  </div>
                </div>

                {ticketU === "new" && (
                  <div className="mb-3" onClick={(e) => e.stopPropagation()}>
                    <Button
                      type="button"
                      disabled={orderTicketBusy || !IS_TAURI || !architectureKnowledgeDone}
                      title={
                        !architectureKnowledgeDone
                          ? t("workbench.products.detail.autoAnalysisTicketArchRequired")
                          : t("workbench.products.detail.autoAnalysisTicketCardHint")
                      }
                      className="w-full h-8 gap-1.5 text-xs font-medium bg-gradient-to-r from-primary/10 to-primary/5 hover:from-primary/20 hover:to-primary/10 text-primary border border-primary/20 shadow-sm transition-all rounded-md"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (!IS_TAURI) {
                          toast.message(t("workbench.products.tauriOnlyAction"));
                          return;
                        }
                        const prodKey = product.name.trim();
                        if (!prodKey) return;
                        setOrderTicketBusy(true);
                        void (async () => {
                          try {
                            if (!(await guardOwnerMatch())) return;
                            const resp = await orderInitialize(synapseApiBase, { prod: prodKey });
                            const msg =
                              typeof resp.message === "string" && resp.message.trim() !== ""
                                ? resp.message.trim()
                                : t("workbench.products.detail.gitnexusInitDefaultSuccess");
                            toast.success(msg);
                            await fetchProcessOnce();
                          } catch (err) {
                            const msg = err instanceof Error ? err.message : String(err);
                            toast.error(t("workbench.products.detail.orderInitializeFailed", { message: msg }));
                          } finally {
                            setOrderTicketBusy(false);
                          }
                        })();
                      }}
                    >
                      <Zap
                        className={`size-3.5 shrink-0 ${orderTicketBusy ? "animate-pulse" : ""}`}
                        strokeWidth={2.5}
                      />
                      {t("workbench.products.detail.autoAnalysisCta")}
                    </Button>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-background/50 p-2 rounded text-center border border-border/40">
                    <div className="text-[11px] text-muted-foreground mb-1">
                      {t("workbench.products.detail.reqTickets")}
                    </div>
                    <div className="text-base text-foreground font-semibold">
                      {ticketReqMetric}
                    </div>
                  </div>
                  <div className="bg-background/50 p-2 rounded text-center border border-border/40">
                    <div className="text-[11px] text-muted-foreground mb-1">
                      {t("workbench.products.detail.devTickets")}
                    </div>
                    <div className="text-base text-foreground font-semibold">
                      {ticketDevMetric}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Main Content Area */}
          <div className="flex-1 flex flex-col min-w-0 bg-background relative overflow-y-auto custom-scrollbar">
            {activeTab === "code-graph" && (
              <div className="p-6 h-full flex min-h-0 flex-col gap-4">
                <div className="flex min-h-[400px] flex-1 flex-col rounded-xl border border-border bg-muted/5 relative overflow-hidden">
                  {activeRepoWireU !== "done" ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--primary)_1px,transparent_1px)] [background-size:30px_30px] opacity-10 pointer-events-none" />
                      <div className="relative z-10 flex min-h-[400px] flex-1 flex-col items-center justify-center px-6 text-center">
                        {activeRepoAnalyzing ? (
                          <Loader2
                            size={40}
                            className="text-primary/80 mb-3 app-loading-spin"
                            strokeWidth={1.5}
                            aria-hidden
                          />
                        ) : (
                          <Code2 size={44} className="text-primary/45 mb-3" strokeWidth={1} aria-hidden />
                        )}
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedWaitingTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {t("workbench.products.detail.graphEmbedWaitingHintCode")}
                        </p>
                        <p className="text-xs text-muted-foreground/90 mt-2">
                          {detailWireStateLabel(t, activeRepoWireU)}
                        </p>
                      </div>
                    </>
                  ) : !IS_TAURI || !devserviceHost ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--destructive)_1px,transparent_1px)] [background-size:28px_28px] opacity-[0.07] pointer-events-none" />
                      <div className="relative z-10 flex min-h-[400px] flex-1 flex-col items-center justify-center px-6 text-center">
                        <AlertCircle size={44} className="text-destructive/80 mb-3" strokeWidth={1.25} aria-hidden />
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedErrorTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {!IS_TAURI
                            ? t("workbench.products.detail.codeGraphEmbedTauriOnly")
                            : t("workbench.products.createMissingDevservice")}
                        </p>
                      </div>
                    </>
                  ) : !codeGraphIframeSrc ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--destructive)_1px,transparent_1px)] [background-size:28px_28px] opacity-[0.07] pointer-events-none" />
                      <div className="relative z-10 flex min-h-[400px] flex-1 flex-col items-center justify-center px-6 text-center">
                        <AlertCircle size={44} className="text-destructive/80 mb-3" strokeWidth={1.25} aria-hidden />
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedErrorTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {!activeRepoForGraph?.url?.trim()
                            ? t("workbench.products.detail.codeGraphNoRepoUrl")
                            : t("workbench.products.detail.codeGraphEmbedUnavailable")}
                        </p>
                      </div>
                    </>
                  ) : codeGraphReachable === null ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--primary)_1px,transparent_1px)] [background-size:30px_30px] opacity-10 pointer-events-none" />
                      <div className="relative z-10 flex min-h-[400px] flex-1 flex-col items-center justify-center px-6 text-center">
                        <Loader2
                          size={40}
                          className="text-primary/80 mb-3 app-loading-spin"
                          strokeWidth={1.5}
                          aria-hidden
                        />
                        <p className="text-sm text-muted-foreground">{t("workbench.products.detail.codeGraphProbing")}</p>
                      </div>
                    </>
                  ) : codeGraphReachable === false ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--destructive)_1px,transparent_1px)] [background-size:28px_28px] opacity-[0.07] pointer-events-none" />
                      <div className="relative z-10 flex min-h-[400px] flex-1 flex-col items-center justify-center px-6 text-center">
                        <AlertCircle size={44} className="text-destructive/80 mb-3" strokeWidth={1.25} aria-hidden />
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedErrorTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {t("workbench.products.detail.graphEmbedErrorHintProbe")}
                        </p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="mt-4"
                          onClick={() => setCodeGraphProbeNonce((n) => n + 1)}
                        >
                          <RefreshCw size={14} className="mr-1.5" />
                          {t("workbench.products.detail.ticketGraphRetryProbe")}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <iframe
                      key={codeGraphIframeSrc}
                      title={t("workbench.products.detail.codeGraphTitle")}
                      src={codeGraphIframeSrc}
                      className="h-full min-h-[400px] w-full flex-1 border-0 bg-background"
                      referrerPolicy="no-referrer-when-downgrade"
                    />
                  )}
                </div>
              </div>
            )}

            {activeTab === "ticket-graph" && (
              <div className="p-6 h-full flex min-h-0 flex-col gap-4">
                <div className="flex min-h-[720px] flex-1 flex-col rounded-xl border border-border bg-muted/5 relative overflow-hidden">
                  {ticketU !== "done" ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(theme(colors.emerald.500)_1px,transparent_1px)] [background-size:30px_30px] opacity-10" />
                      <div className="relative z-10 flex min-h-[720px] w-full flex-col items-center justify-center px-6 text-center">
                        {ticketU === "init" || ticketU === "process" ? (
                          <Loader2
                            size={40}
                            className="text-emerald-500/80 mb-3 app-loading-spin"
                            strokeWidth={1.5}
                            aria-hidden
                          />
                        ) : (
                          <ClipboardList size={44} className="text-emerald-500/45 mb-3" strokeWidth={1} aria-hidden />
                        )}
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedWaitingTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {t("workbench.products.detail.graphEmbedWaitingHintTicket")}
                        </p>
                        <p className="text-xs text-muted-foreground/90 mt-2">{detailWireStateLabel(t, ticketU)}</p>
                      </div>
                    </>
                  ) : !IS_TAURI || !devserviceHost ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--destructive)_1px,transparent_1px)] [background-size:28px_28px] opacity-[0.07]" />
                      <div className="relative z-10 flex min-h-[720px] w-full flex-col items-center justify-center px-6 text-center">
                        <AlertCircle size={44} className="text-destructive/80 mb-3" strokeWidth={1.25} aria-hidden />
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedErrorTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {!IS_TAURI
                            ? t("workbench.products.detail.codeGraphEmbedTauriOnly")
                            : t("workbench.products.createMissingDevservice")}
                        </p>
                      </div>
                    </>
                  ) : !ticketGraphIframeSrc ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--destructive)_1px,transparent_1px)] [background-size:28px_28px] opacity-[0.07]" />
                      <div className="relative z-10 flex min-h-[720px] w-full flex-col items-center justify-center px-6 text-center">
                        <AlertCircle size={44} className="text-destructive/80 mb-3" strokeWidth={1.25} aria-hidden />
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedErrorTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {t("workbench.products.detail.graphEmbedErrorHintNoProd")}
                        </p>
                      </div>
                    </>
                  ) : ticketGraphReachable === null ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(theme(colors.emerald.500)_1px,transparent_1px)] [background-size:30px_30px] opacity-10" />
                      <div className="relative z-10 flex min-h-[720px] w-full flex-col items-center justify-center px-6 text-center">
                        <Loader2
                          size={40}
                          className="text-emerald-500/80 mb-3 app-loading-spin"
                          strokeWidth={1.5}
                          aria-hidden
                        />
                        <p className="text-sm text-muted-foreground">{t("workbench.products.detail.ticketGraphProbing")}</p>
                      </div>
                    </>
                  ) : ticketGraphReachable === false ? (
                    <>
                      <div className="absolute inset-0 bg-[radial-gradient(var(--destructive)_1px,transparent_1px)] [background-size:28px_28px] opacity-[0.07]" />
                      <div className="relative z-10 flex min-h-[720px] w-full flex-col items-center justify-center px-6 text-center">
                        <AlertCircle size={44} className="text-destructive/80 mb-3" strokeWidth={1.25} aria-hidden />
                        <h4 className="text-lg font-semibold text-foreground mb-2">
                          {t("workbench.products.detail.graphEmbedErrorTitle")}
                        </h4>
                        <p className="text-sm text-muted-foreground max-w-md">
                          {t("workbench.products.detail.graphEmbedErrorHintProbe")}
                        </p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="mt-4"
                          onClick={() => setTicketGraphProbeNonce((n) => n + 1)}
                        >
                          <RefreshCw size={14} className="mr-1.5" />
                          {t("workbench.products.detail.ticketGraphRetryProbe")}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <iframe
                      key={ticketGraphIframeSrc}
                      title={t("workbench.products.detail.ticketKnowledgeGraphIframeTitle")}
                      src={ticketGraphIframeSrc}
                      className="h-full min-h-[720px] w-full flex-1 border-0 bg-background"
                      referrerPolicy="no-referrer-when-downgrade"
                    />
                  )}
                </div>
              </div>
            )}

            {activeTab === "knowledge-graph" && (
              <div className="p-6 h-full flex flex-col gap-4">
                <div className="flex-1 rounded-xl border border-border bg-muted/5 relative overflow-hidden flex items-center justify-center min-h-[400px]">
                  <div className="absolute inset-0 bg-[radial-gradient(theme(colors.emerald.500)_1px,transparent_1px)] [background-size:30px_30px] opacity-10"></div>
                  <div className="relative z-10 flex flex-col items-center text-center max-w-md">
                    <Network size={48} className="text-emerald-500 opacity-50 mb-4" strokeWidth={1} />
                    <h4 className="text-lg font-semibold text-foreground mb-2">
                      {t("workbench.products.detail.knowledgeGraphTitle")}
                    </h4>
                    <p className="text-sm text-muted-foreground">
                      {t("workbench.products.detail.knowledgeGraphHint")}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {openDocs.map((doc) => {
              if (activeTab !== doc.id) return null;
              return (
                <div key={doc.id} className="flex flex-col h-full bg-background overflow-hidden">
                  <ProductDocumentEditor
                    content={doc.content}
                    title={doc.title}
                    synapseApiBase={synapseApiBase}
                    excalidrawByFileName={doc.excalidrawByFileName}
                    readonly={doc.readonly}
                    onSave={(newContent) => {
                      setOpenDocs((docs) =>
                        docs.map((d) => (d.id === doc.id ? { ...d, content: newContent } : d)),
                      );
                    }}
                    onSubmit={() => handleSubmitDocs(doc.category)}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </SheetContent>
    </Sheet>

    <Dialog open={genOptsOpen} onOpenChange={setGenOptsOpen}>
      <DialogContent className="sm:max-w-md" showCloseButton>
        <DialogHeader>
          <DialogTitle>{t("workbench.products.detail.generateOptionsTitle", "生成文档")}</DialogTitle>
          <DialogDescription>
            {t(
              "workbench.products.detail.generateOptionsDesc",
              "请选择要挂载的研发工具技能，以及用于本次生成的 LLM 端点。",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label className="text-xs font-medium">
              {t("workbench.products.detail.generateOptionsRdSkill", "研发工具")}
            </Label>
            {rdSkillCatalogLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t("workbench.products.detail.generateOptionsRdSkillLoading", "加载研发工具列表...")}
              </div>
            ) : rdSkillCatalog.length === 0 ? (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {t(
                  "workbench.products.detail.generateOptionsRdSkillEmpty",
                  "未找到已启用的研发工具技能，请先在「研发工具」页面启用。",
                )}
              </p>
            ) : (
              <div className="flex flex-col gap-1 max-h-36 overflow-y-auto rounded-md border border-input bg-background px-2 py-1">
                {rdSkillCatalog.map((skill) => (
                  <label key={skill.skillId} className="flex items-center gap-2 text-sm cursor-pointer py-0.5">
                    <input
                      type="checkbox"
                      className="accent-primary"
                      checked={genRdSkills.includes(skill.skillId)}
                      onChange={(e) => {
                        setGenRdSkills((prev) =>
                          e.target.checked
                            ? [...prev, skill.skillId]
                            : prev.filter((id) => id !== skill.skillId),
                        );
                      }}
                    />
                    <span>{skill.name}</span>
                    <span className="text-xs text-muted-foreground ml-1">({skill.skillId})</span>
                  </label>
                ))}
              </div>
            )}
          </div>
          <div className="grid gap-2">
            <Label htmlFor="llm-ep-select" className="text-xs font-medium">
              {t("workbench.products.detail.generateOptionsLlmEndpoint", "LLM 端点")}
            </Label>
            <select
              id="llm-ep-select"
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
              value={genEndpoint}
              onChange={(e) => setGenEndpoint(e.target.value)}
            >
              <option value="">
                {t("workbench.products.detail.generateOptionsEndpointAuto", "系统默认（自动选择端点）")}
              </option>
              {llmEpCatalog.map((ep) => (
                <option key={ep.name} value={ep.name}>
                  {ep.model ? `${ep.name} — ${ep.model}` : ep.name}
                </option>
              ))}
            </select>
            {llmEpCatalogErr && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {t("workbench.products.detail.generateOptionsEndpointsFailed", "加载端点列表失败")}: {llmEpCatalogErr}
              </p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setGenOptsOpen(false)}>
            {t("workbench.products.detail.generateOptionsCancel", "取消")}
          </Button>
          <Button
            type="button"
            disabled={rdSkillCatalogLoading || rdSkillCatalog.length === 0}
            onClick={() => {
              if (!genCategoryKey) return;
              setGenOptsOpen(false);
              void handleGenerateKnowledge(genCategoryKey, {
                rd_skill_ids: genRdSkills.length > 0 ? genRdSkills : rdSkillCatalog.map((s) => s.skillId),
                preferred_endpoint: genEndpoint.trim() || null,
              });
            }}
          >
            {t("workbench.products.detail.generateOptionsConfirm", "开始生成")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  );
}
