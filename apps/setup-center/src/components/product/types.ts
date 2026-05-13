import type {
  ProdInfoWireItem,
  ProdProcessDataPayload,
  RdModuleNameItem,
  RdRepoDetailRow,
  RdRepoInfo,
  RepoProcessWireItem,
} from "@/api/rdUnifiedService";
import type { SearchableOption } from "./SearchableVirtualSelect";

/**
 * 研发统一服务单字符状态 → 统一语义（仓库 / 文档 / 工单共用）：
 * N=new | I=init | P=process | D=done | E/F=error
 */
export type UnifiedWireAnalysisState = "new" | "init" | "process" | "done" | "error";

export interface Repository {
  purpose: string;
  url: string;
  /** 仓库分支：repositoryId|destBranchName，对应 RdRepoInfo.repo_branch */
  branch: string;
  /** 应用模块 productModuleId|moduleChName，对应 RdRepoInfo.repo_module */
  repoModule?: string;
  /** 产品分支 branchVersionId|branchName，对应 RdRepoInfo.prod_branch */
  prodBranch?: string;
  token: string;
  /** 仓库代码路径（与研发统一服务 `repo_info.code_path` 对应，手动填写） */
  codePath?: string;
  isMain: boolean;
  /** 与研发统一服务 repo_process 对齐后的单仓状态 */
  wireAnalysisState?: UnifiedWireAnalysisState;
  /** 分析完成时间（状态为 D 且服务端返回时） */
  analysisCompletedAt?: string;
  analysisTime?: string;
  analysisStatus?: "analyzing" | "completed";
}

export interface ProductDocument {
  id: string;
  title: string;
  type: 'markdown' | 'excalidraw' | 'mixed';
  content: string; // Markdown content
  excalidrawElements?: any[]; // Excalidraw mock data
}

/**
 * 单类文档进度，与研发统一服务 `doc_process` 单条语义对齐（归一化状态 + 可选完成时间）。
 */
export interface ProductKnowledgeSlot {
  wireState: UnifiedWireAnalysisState;
  /** 对应 doc_process_time，仅当 wireState 为 done 时一般有值 */
  completedAt?: string;
  /** 服务端 doc_type 原文（匹配到多行时取首条） */
  docType?: string;
}

export type ProductKnowledge = {
  architecture: ProductKnowledgeSlot;
  solution: ProductKnowledgeSlot;
  requirements: ProductKnowledgeSlot;
  manual: ProductKnowledgeSlot;
  delivery: ProductKnowledgeSlot;
};

export type ProductKnowledgeCategory = keyof ProductKnowledge;

export const PRODUCT_KNOWLEDGE_KEYS = [
  "architecture",
  "solution",
  "requirements",
  "manual",
  "delivery",
] as const satisfies readonly ProductKnowledgeCategory[];

/** 研发统一服务 `docs_initialize` / `docs_submit` 的 doc_type，与界面五类标签一致 */
export const UNIFIED_SERVICE_DOC_TYPE: Record<ProductKnowledgeCategory, string> = {
  architecture: "产品架构",
  solution: "产品方案",
  requirements: "产品需求",
  manual: "产品手册",
  delivery: "交付材料",
};

export function unifiedDocTypeForKnowledgeCategory(key: ProductKnowledgeCategory): string {
  return UNIFIED_SERVICE_DOC_TYPE[key];
}

export function emptyProductKnowledge(): ProductKnowledge {
  const slot = (): ProductKnowledgeSlot => ({ wireState: "new" });
  return {
    architecture: slot(),
    solution: slot(),
    requirements: slot(),
    manual: slot(),
    delivery: slot(),
  };
}

export function isProductKnowledgeSlotDone(slot: ProductKnowledgeSlot): boolean {
  return slot.wireState === "done";
}

/** 本地补丁：按类型部分更新 slot，与 patchProductKnowledgeSlots 配合 */
export type ProductKnowledgePatch = {
  [K in ProductKnowledgeCategory]?: Partial<ProductKnowledgeSlot>;
};

export function patchProductKnowledgeSlots(
  base: ProductKnowledge,
  patch: ProductKnowledgePatch,
): ProductKnowledge {
  const out: ProductKnowledge = { ...base };
  for (const key of PRODUCT_KNOWLEDGE_KEYS) {
    const piece = patch[key];
    if (piece != null) out[key] = { ...base[key], ...piece };
  }
  return out;
}

export interface Ticket {
  id: string;
  title: string;
  assignee: string;
  status: string;
}

export interface Product {
  id: string;
  name: string;
  /** 产品版本：productVersionId|productVersionCode，与研发统一服务 `version` 一致 */
  version: string;
  /** 产品标签（研发统一服务 `module` 字段）；仅英文、数字、下划线，≤32 字节 */
  module: string;
  icon: string;
  description: string;
  /** 逗号分隔，与研发统一服务 `function` 字段对应 */
  features?: string;
  /** 项目空间（研发统一服务 `space`） */
  space?: string;
  /** 创建人姓名（研发统一服务 `owner`） */
  owner?: string;
  /** userinfo.encryption 透传（研发统一服务 `owner_info`） */
  ownerInfo?: string;
  repositories: Repository[];
  latestTickets?: Ticket[];
  /** 需求单数量（get_prod_info / get_prod_process_info 与 order_process 同级的 demand_order_count） */
  demandOrderCount?: number;
  /** 研发单数量（task_order_count） */
  taskOrderCount?: number;
  analysisStatus: {
    code: "success" | "processing" | "pending" | "error";
    ticket: "success" | "processing" | "pending" | "error";
    document: "success" | "processing" | "pending" | "error";
  };
  /** 与研发统一服务字符状态对齐的三维语义（卡片/详情展示用） */
  analysisUnified: {
    code: UnifiedWireAnalysisState;
    ticket: UnifiedWireAnalysisState;
    document: UnifiedWireAnalysisState;
  };
  /** 分析完成时间（仅当对应维度为 done 且服务端返回时） */
  analysisTimes?: {
    ticket?: string;
    document?: string;
  };
  knowledge: ProductKnowledge;
}

export const AVAILABLE_PRODUCT_NAMES = [
  "智能搜索助手",
  "协同设计平台",
  "代码审计工具",
  "自动化测试框架",
  "CI/CD 流水线",
  "移动端应用套件",
  "数据可视化引擎",
  "云原生网关"
];

const createIcon = (color: string, path: string) => `data:image/svg+xml;utf8,<svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg"><rect width="32" height="32" rx="8" fill="${color}"/><g transform="translate(4,4)" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none">${path}</g></svg>`;

export const DEFAULT_ICONS = [
  { label: '后端服务 (Backend)', value: createIcon('%233b82f6', '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect><line x1="6" x2="6.01" y1="6" y2="6"></line><line x1="6" x2="6.01" y1="18" y2="18"></line>') },
  { label: '前端应用 (Frontend)', value: createIcon('%2310b981', '<rect width="18" height="18" x="3" y="3" rx="2"></rect><path d="M3 9h18"></path><path d="M9 21V9"></path>') },
  { label: '移动端 (Mobile)', value: createIcon('%238b5cf6', '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"></rect><path d="M12 18h.01"></path>') },
  { label: '微服务 (Microservice)', value: createIcon('%23f97316', '<rect x="16" y="16" width="6" height="6" rx="1"></rect><rect x="2" y="16" width="6" height="6" rx="1"></rect><rect x="9" y="2" width="6" height="6" rx="1"></rect><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"></path><path d="M12 12V8"></path>') },
  { label: '数据中心 (Database)', value: createIcon('%2306b6d4', '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5V19A9 3 0 0 0 21 19V5"></path><path d="M3 12A9 3 0 0 0 21 12"></path>') },
  { label: 'AI 模型 (AI Model)', value: createIcon('%23f43f5e', '<path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"></path>') },
  { label: 'API 网关 (Gateway)', value: createIcon('%236366f1', '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"></path><path d="m3.3 7 8.7 5 8.7-5"></path><path d="M12 22V12"></path>') },
  { label: 'CI/CD 流水线 (Pipeline)', value: createIcon('%23f59e0b', '<circle cx="18" cy="18" r="3"></circle><circle cx="6" cy="6" r="3"></circle><path d="M6 21V9a9 9 0 0 0 9 9"></path>') },
  { label: '安全审计 (Security)', value: createIcon('%23ef4444', '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"></path><path d="m9 12 2 2 4-4"></path>') },
  { label: '中间件 (Middleware)', value: createIcon('%2314b8a6', '<polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 12 12 17 22 12"></polyline><polyline points="2 17 12 22 22 17"></polyline>') },
  { label: '云服务 (Cloud)', value: createIcon('%23334155', '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"></path>') },
  { label: '算法逻辑 (Algorithm)', value: createIcon('%23ec4899', '<path d="m18 16 4-4-4-4"></path><path d="m6 8-4 4 4 4"></path><path d="m14.5 4-5 16"></path>') },
];

/** 将 prod_icon 字符串解析为界面用 data URL（优先匹配 DEFAULT_ICONS 的 label）；服务端可能返回 null */
/** 展示用：存为 id|name 时只显示 name 段（卡片/标签） */
export function displayIdPipeName(value: string | undefined): string {
  const v = (value ?? "").trim();
  if (!v) return "";
  const i = v.indexOf("|");
  if (i > 0) return v.slice(i + 1).trim() || v;
  return v;
}

/** 产品标签（`module`）最大 UTF-8 字节数 */
export const PRODUCT_TAG_MAX_BYTES = 32;

/** 输入框侧：仅保留英文、数字、下划线，并截断至字节上限 */
export function sanitizeProductTagInput(raw: string): string {
  let s = raw.replace(/[^a-zA-Z0-9_]/g, "");
  while (new TextEncoder().encode(s).length > PRODUCT_TAG_MAX_BYTES) {
    s = s.slice(0, -1);
  }
  return s;
}

/** 提交前校验：非空、字符集、字节长度 */
export function isValidProductTag(s: string): boolean {
  const t = s.trim();
  if (!t) return false;
  if (!/^[a-zA-Z0-9_]+$/.test(t)) return false;
  return new TextEncoder().encode(t).length <= PRODUCT_TAG_MAX_BYTES;
}

/**
 * 工单 `product_module_name` 与 get_prod_info 行匹配：
 * 兼容旧数据（产品级 `module`）与新数据（仓库级 `repo_module`）。
 */
export function prodWireMatchesWorkItemModuleName(
  row: ProdInfoWireItem,
  productModuleName: string,
): boolean {
  const modName = productModuleName.trim();
  if (!modName) return false;
  const m = (row.module ?? "").trim();
  if (m === modName) return true;
  if (m.includes("|") && displayIdPipeName(m) === modName) return true;
  const repos = Array.isArray(row.repo_info) ? row.repo_info : [];
  for (const repo of repos) {
    const rm = String(repo?.repo_module ?? "").trim();
    if (!rm) continue;
    if (rm === modName) return true;
    if (displayIdPipeName(rm) === modName) return true;
  }
  return false;
}

/** 与模块下拉的 value 一致：productModuleId|moduleChName */
export function rdModuleNameItemToCompositeValue(row: RdModuleNameItem): string {
  const id = row.productModuleId ?? "";
  const name = (row.moduleChName ?? "").trim() || String(id);
  return `${id}|${name}`;
}

/**
 * 由 get_module_name_list 行内的 branchVersionId、branchName 拼成与产品分支下拉一致的值；
 * 无 branchVersionId 时不自动填充。
 */
export function defaultProdBranchCompositeFromModuleRow(
  row: RdModuleNameItem | undefined,
): string | null {
  if (!row) return null;
  const id = row.branchVersionId;
  if (id == null || id === "") return null;
  const prefix = typeof id === "number" ? String(id) : String(id).trim();
  if (!prefix) return null;
  const name = (row.branchName ?? "").trim() || prefix;
  return `${prefix}|${name}`;
}

/** 选中应用模块后，用模块行自带的产品分支作为默认 prodBranch；未选模块则清空 */
export function defaultProdBranchForAppModuleSelection(
  moduleComposite: string,
  moduleRows: RdModuleNameItem[],
): string {
  const t = moduleComposite.trim();
  if (!t) return "";
  const mod = moduleRows.find((r) => rdModuleNameItemToCompositeValue(r) === t);
  return defaultProdBranchCompositeFromModuleRow(mod) ?? "";
}

/** 多仓库时应用模块下拉：排除其它行已选的 `value`（当前行已选保留可选） */
export function filterAppModuleOptionsForRow(
  options: SearchableOption[],
  repos: { repoModule?: string }[],
  rowIndex: number,
  currentRepoModule: string,
): SearchableOption[] {
  const cur = currentRepoModule.trim();
  const taken = new Set(
    repos
      .map((r, j) => (j !== rowIndex && r.repoModule?.trim() ? r.repoModule.trim() : null))
      .filter((x): x is string => !!x),
  );
  return options.filter((o) => !taken.has(o.value) || o.value === cur);
}

/** 多仓库时产品分支下拉：排除其它行已选的 `value`（当前行已选保留可选） */
export function filterProdBranchOptionsForRow(
  options: SearchableOption[],
  repos: { prodBranch?: string }[],
  rowIndex: number,
  currentProdBranch: string,
): SearchableOption[] {
  const cur = currentProdBranch.trim();
  const taken = new Set(
    repos
      .map((r, j) => (j !== rowIndex && r.prodBranch?.trim() ? r.prodBranch.trim() : null))
      .filter((x): x is string => !!x),
  );
  return options.filter((o) => !taken.has(o.value) || o.value === cur);
}

/** 多仓库时仓库分支下拉：排除其它行已选的 `value`（当前行已选保留可选） */
export function filterRepoBranchOptionsForRow(
  options: SearchableOption[],
  repos: { branch?: string }[],
  rowIndex: number,
  currentBranch: string,
): SearchableOption[] {
  const cur = currentBranch.trim();
  const taken = new Set(
    repos
      .map((r, j) => (j !== rowIndex && r.branch?.trim() ? r.branch.trim() : null))
      .filter((x): x is string => !!x),
  );
  return options.filter((o) => !taken.has(o.value) || o.value === cur);
}

/** 展示/入库格式 repositoryId|destBranchName */
export function repoDetailRowToOption(row: RdRepoDetailRow): SearchableOption {
  const rid = String(row.repositoryId ?? "").trim();
  const dest =
    String(row.destBranchName ?? "").trim() || String(row.branchName ?? "").trim() || rid;
  const value = `${rid}|${dest}`;
  return { label: value, value };
}

export function findRepoUrlForDetailComposite(rows: RdRepoDetailRow[], composite: string): string {
  const t = composite.trim();
  if (!t) return "";
  for (const row of rows) {
    if (repoDetailRowToOption(row).value === t) {
      return String(row.repoUrl ?? "").trim();
    }
  }
  return "";
}

/** 校验仓库分支是否为 repositoryId|destBranchName（两段均非空） */
export function isValidRepoBranchComposite(v: string | undefined): boolean {
  const s = (v ?? "").trim();
  const i = s.indexOf("|");
  if (i <= 0) return false;
  const left = s.slice(0, i).trim();
  const right = s.slice(i + 1).trim();
  return left.length > 0 && right.length > 0;
}

export function resolveProdIconString(prod_icon: string | null | undefined): string {
  const t = (prod_icon ?? "").trim();
  if (!t) return DEFAULT_ICONS[0].value;
  const byLabel = DEFAULT_ICONS.find((i) => i.label === t);
  if (byLabel) return byLabel.value;
  return DEFAULT_ICONS[0].value;
}

function repoWireToRepository(r: RdRepoInfo): Repository {
  return {
    purpose: r.repo_func ?? "",
    url: r.repo_url ?? "",
    branch: r.repo_branch ?? "",
    repoModule: (r.repo_module ?? "").trim() || undefined,
    prodBranch: r.prod_branch?.trim() || undefined,
    token: r.repo_token || "",
    codePath: (r.code_path ?? "").trim() || undefined,
    isMain: r.repo_master === "Y",
  };
}

/** 界面 Repository[] → 研发统一服务 repo_info（含 prod_branch） */
export function repositoriesToRdRepoInfo(repositories: Repository[]): RdRepoInfo[] {
  return repositories.map((r) => ({
    repo_url: r.url,
    repo_branch: r.branch,
    prod_branch: (r.prodBranch ?? "").trim(),
    repo_module: (r.repoModule ?? "").trim(),
    code_path: (r.codePath ?? "").trim(),
    repo_func: r.purpose,
    repo_token: r.token || "",
    repo_master: r.isMain ? "Y" : "N",
  }));
}

/** 界面 Product → 研发统一服务 repo_info 项 */
export function productRepositoriesToRdRepoInfo(p: Product): RdRepoInfo[] {
  return repositoriesToRdRepoInfo(p.repositories);
}

/** 多路聚合：error > init > process > new > done（下标越小越「差」） */
const UNIFIED_PRIORITY = ["error", "init", "process", "new", "done"] as const satisfies readonly UnifiedWireAnalysisState[];

/** 将服务端 repo_process_state / doc_process_state / order_process 归一化为 UnifiedWireAnalysisState */
export function normalizeWireProcessState(raw: string | undefined): UnifiedWireAnalysisState {
  const s = String(raw ?? "").trim();
  if (!s) return "new";
  const c = s.charAt(0).toUpperCase();
  if (c === "N") return "new";
  if (c === "I") return "init";
  if (c === "P") return "process";
  if (c === "D") return "done";
  if (c === "E" || c === "F") return "error";
  const lower = s.toLowerCase();
  if (lower === "fail" || lower === "error") return "error";
  if (lower === "done" || lower === "success" || lower === "completed") return "done";
  if (lower === "process" || lower === "processing") return "process";
  if (lower === "init" || lower === "initializing") return "init";
  if (lower === "new" || lower === "pending" || lower === "none") return "new";
  return "new";
}

/** 研发统一服务 doc_process 条目中 doc_type 与本地 knowledge 五类的宽松匹配 */
export function docTypeMatchesKnowledge(docTypeRaw: string, key: ProductKnowledgeCategory): boolean {
  const t = String(docTypeRaw ?? "").trim().toLowerCase();
  const patterns: Record<keyof ProductKnowledge, string[]> = {
    architecture: ["架构", "architecture", "arch", "总体", "技术架构", "产品架构"],
    solution: ["方案", "solution", "产品方案"],
    requirements: ["需求", "requirements", "产品需求", "需求概要"],
    manual: ["手册", "manual", "产品手册"],
    delivery: ["交付材料", "交付", "delivery", "产品交付"],
  };
  for (const p of patterns[key]) {
    const pl = p.toLowerCase();
    if (t === pl || t.includes(pl)) return true;
  }
  return false;
}

/** 根据统一服务 doc_type 文案解析本地知识分类（用于 get_doc / 进度行匹配） */
export function productKnowledgeCategoryFromDocTypeWire(
  docTypeRaw: string | undefined | null,
): ProductKnowledgeCategory | null {
  const s = String(docTypeRaw ?? "").trim();
  if (!s) return null;
  for (const key of PRODUCT_KNOWLEDGE_KEYS) {
    if (docTypeMatchesKnowledge(s, key)) return key;
  }
  return null;
}

/**
 * 将 get_prod_info / get_prod_process_info 的 `doc_process` 按类型拆成五类进度
 *（与 DocProcessWireItem 一致：多行同类型时按 pickWorstUnifiedState 聚合）。
 */
export function knowledgeFromDocProcess(
  doc_process?:
    | {
        doc_type?: string;
        doc_process_state: string;
        doc_process_time?: string | null;
      }[]
    | null,
): ProductKnowledge {
  if (!doc_process?.length) return emptyProductKnowledge();

  const slotFor = (key: ProductKnowledgeCategory): ProductKnowledgeSlot => {
    const rows = doc_process.filter((d) =>
      docTypeMatchesKnowledge(String(d?.doc_type ?? ""), key),
    );
    if (!rows.length) return { wireState: "new" };
    const wireState = pickWorstUnifiedState(
      rows.map((d) => normalizeWireProcessState(d?.doc_process_state)),
    );
    const completedAt =
      wireState === "done"
        ? pickLatestTimeString(
            rows
              .filter((d) => normalizeWireProcessState(d.doc_process_state) === "done")
              .map((d) => d.doc_process_time),
          )
        : undefined;
    const dt0 = rows[0]?.doc_type;
    const docType = typeof dt0 === "string" && dt0.trim() !== "" ? dt0.trim() : undefined;
    return { wireState, completedAt, docType };
  };

  return {
    architecture: slotFor("architecture"),
    solution: slotFor("solution"),
    requirements: slotFor("requirements"),
    manual: slotFor("manual"),
    delivery: slotFor("delivery"),
  };
}

function mergeKnowledgeSlot(local: ProductKnowledgeSlot, wire: ProductKnowledgeSlot): ProductKnowledgeSlot {
  if (local.wireState === "done" || wire.wireState === "done") {
    return {
      wireState: "done",
      completedAt: pickLatestTimeString([local.completedAt, wire.completedAt]),
      docType: wire.docType ?? local.docType,
    };
  }
  const wireState = pickWorstUnifiedState([local.wireState, wire.wireState]);
  const completedAt =
    wireState === "done"
      ? pickLatestTimeString([local.completedAt, wire.completedAt])
      : undefined;
  return { wireState, completedAt, docType: wire.docType ?? local.docType };
}

/** 合并本地会话 knowledge 与统一服务 doc_process 推导（任一侧 done 则视为该类型已完成） */
export function mergeProductKnowledge(local: ProductKnowledge, fromWire: ProductKnowledge): ProductKnowledge {
  return {
    architecture: mergeKnowledgeSlot(local.architecture, fromWire.architecture),
    solution: mergeKnowledgeSlot(local.solution, fromWire.solution),
    requirements: mergeKnowledgeSlot(local.requirements, fromWire.requirements),
    manual: mergeKnowledgeSlot(local.manual, fromWire.manual),
    delivery: mergeKnowledgeSlot(local.delivery, fromWire.delivery),
  };
}

export function pickWorstUnifiedState(states: UnifiedWireAnalysisState[]): UnifiedWireAnalysisState {
  if (states.length === 0) return "new";
  let bestIdx: number = UNIFIED_PRIORITY.length;
  let picked: UnifiedWireAnalysisState = "done";
  for (const u of states) {
    const idx = (UNIFIED_PRIORITY as readonly string[]).indexOf(u);
    if (idx !== -1 && idx < bestIdx) {
      bestIdx = idx;
      picked = UNIFIED_PRIORITY[idx] as UnifiedWireAnalysisState;
    }
  }
  return bestIdx === UNIFIED_PRIORITY.length ? "new" : picked;
}

function unifiedToAnalysisCode(u: UnifiedWireAnalysisState): Product["analysisStatus"]["code"] {
  switch (u) {
    case "done":
      return "success";
    case "error":
      return "error";
    case "init":
    case "process":
      return "processing";
    case "new":
    default:
      return "pending";
  }
}

function pickLatestTimeString(candidates: (string | null | undefined)[]): string | undefined {
  const xs = candidates.filter((x): x is string => typeof x === "string" && x.trim() !== "");
  if (xs.length === 0) return undefined;
  return xs.slice().sort()[xs.length - 1];
}

function documentAggregatedCompletedTime(
  doc_process?: { doc_process_state: string; doc_process_time?: string | null }[] | null,
): string | undefined {
  if (!doc_process?.length) return undefined;
  const docWorst = pickWorstUnifiedState(
    doc_process.map((d) => normalizeWireProcessState(d?.doc_process_state)),
  );
  if (docWorst !== "done") return undefined;
  return pickLatestTimeString(
    doc_process
      .filter((d) => normalizeWireProcessState(d.doc_process_state) === "done")
      .map((d) => d.doc_process_time),
  );
}

/** 与 order_process 同级的数量字段；兼容服务端误将 key 写成带尾部空格 */
function orderCountsFromProcessWire(data: ProdProcessDataPayload | ProdInfoWireItem): {
  demandOrderCount?: number;
  taskOrderCount?: number;
} {
  const rec = data as Record<string, unknown>;
  const read = (keys: readonly string[]): number | undefined => {
    for (const k of keys) {
      const raw = rec[k];
      if (typeof raw === "number" && Number.isFinite(raw)) return raw;
      if (typeof raw === "string" && raw.trim() !== "") {
        const n = Number(raw);
        if (Number.isFinite(n)) return n;
      }
    }
    return undefined;
  };
  const d = read(["demand_order_count", "demand_order_count "] as const);
  const t = read(["task_order_count", "task_order_count "] as const);
  const out: { demandOrderCount?: number; taskOrderCount?: number } = {};
  if (d !== undefined) out.demandOrderCount = d;
  if (t !== undefined) out.taskOrderCount = t;
  return out;
}

function ticketCompletedTime(data: {
  order_process?: string;
  order_process_time?: string | null;
}): string | undefined {
  if (normalizeWireProcessState(data.order_process) !== "done") return undefined;
  const t = data.order_process_time;
  return typeof t === "string" && t.trim() !== "" ? t.trim() : undefined;
}

export type AnalysisProcessFields = {
  analysisStatus: Product["analysisStatus"];
  analysisUnified: Product["analysisUnified"];
  analysisTimes: NonNullable<Product["analysisTimes"]>;
};

/** get_prod_process_info / get_prod_info 中的过程字段 → 卡片/详情用状态与时间 */
export function buildAnalysisFieldsFromProcessPayload(
  data: ProdProcessDataPayload | Pick<ProdInfoWireItem, "repo_process" | "order_process" | "order_process_time" | "doc_process" | "demand_order_count" | "task_order_count">,
): AnalysisProcessFields {
  const repoWorst = data.repo_process?.length
    ? pickWorstUnifiedState(
        data.repo_process.map((r) => normalizeWireProcessState(r?.repo_process_state)),
      )
    : "new";
  const docWorst = data.doc_process?.length
    ? pickWorstUnifiedState(
        data.doc_process.map((d) => normalizeWireProcessState(d?.doc_process_state)),
      )
    : "new";
  const ticketUnified = normalizeWireProcessState(data.order_process);
  return {
    analysisUnified: {
      code: repoWorst,
      ticket: ticketUnified,
      document: docWorst,
    },
    analysisStatus: {
      code: unifiedToAnalysisCode(repoWorst),
      document: unifiedToAnalysisCode(docWorst),
      ticket: unifiedToAnalysisCode(ticketUnified),
    },
    analysisTimes: {
      ticket: ticketCompletedTime(data),
      document: documentAggregatedCompletedTime(data.doc_process),
    },
  };
}

/** 仅聚合为旧版四维 success/processing/pending/error（兼容调用方） */
export function analysisStatusFromProcessPayload(
  data: ProdProcessDataPayload | Pick<ProdInfoWireItem, "repo_process" | "order_process" | "order_process_time" | "doc_process" | "demand_order_count" | "task_order_count">,
): Product["analysisStatus"] {
  return buildAnalysisFieldsFromProcessPayload(data).analysisStatus;
}

/** 将过程数据合并进已有 Product（刷新 / 更新仓库回调） */
export function applyProcessPayloadToProduct(p: Product, payload: ProdProcessDataPayload): Product {
  const fields = buildAnalysisFieldsFromProcessPayload(payload);
  const counts = orderCountsFromProcessWire(payload);
  const fromWire = knowledgeFromDocProcess(payload.doc_process);
  const nextKnowledge = payload.doc_process?.length
    ? mergeProductKnowledge(p.knowledge, fromWire)
    : p.knowledge;
  return {
    ...p,
    analysisStatus: fields.analysisStatus,
    analysisUnified: fields.analysisUnified,
    analysisTimes: fields.analysisTimes,
    repositories: mergeRepositoriesWithProcess(p.repositories, payload.repo_process),
    demandOrderCount: counts.demandOrderCount ?? p.demandOrderCount,
    taskOrderCount: counts.taskOrderCount ?? p.taskOrderCount,
    knowledge: nextKnowledge,
  };
}

function repoProcessMatchKey(repoBranch: string, prodBranch?: string): string {
  return `${String(repoBranch ?? "").trim()}\0${String(prodBranch ?? "").trim()}`;
}

export function mergeRepositoriesWithProcess(
  repositories: Repository[],
  processes?: RepoProcessWireItem[] | null,
): Repository[] {
  if (!processes?.length) {
    return repositories.map((r) => ({
      ...r,
      wireAnalysisState: r.wireAnalysisState ?? "new",
    }));
  }
  const byKey = new Map(
    processes.map((p) => [
      repoProcessMatchKey(p.repo_branch, p.prod_branch),
      p,
    ] as const),
  );
  const byBranchOnly = new Map(processes.map((p) => [String(p.repo_branch ?? "").trim(), p] as const));
  return repositories.map((r) => {
    const p =
      byKey.get(repoProcessMatchKey(r.branch, r.prodBranch)) ??
      byBranchOnly.get(String(r.branch ?? "").trim());
    if (!p) {
      return { ...r, wireAnalysisState: "new" as const };
    }
    const wire = normalizeWireProcessState(p.repo_process_state);
    const tRaw = p.repo_process_time;
    const timeStr =
      wire === "done" && typeof tRaw === "string" && tRaw.trim() !== "" ? tRaw.trim() : undefined;
    return {
      ...r,
      wireAnalysisState: wire,
      analysisCompletedAt: timeStr,
      analysisTime: timeStr ?? r.analysisTime,
    };
  });
}

/** 稳定 id：同 prod+space+version+module 映射为同一键 */
export function stableProductIdFromWire(item: ProdInfoWireItem): string {
  const raw = `${item.prod ?? ""}\0${item.space ?? ""}\0${item.version ?? ""}\0${item.module ?? ""}`;
  let h = 0;
  for (let i = 0; i < raw.length; i++) h = Math.imul(31, h) + raw.charCodeAt(i);
  return `prod-${(h >>> 0).toString(36)}`;
}

/** 研发统一服务单条产品 → 界面 Product（全量拉取、无分页） */
export function prodInfoWireToProduct(item: ProdInfoWireItem): Product {
  const repos = Array.isArray(item.repo_info) ? item.repo_info.filter((r): r is RdRepoInfo => r != null) : [];
  const baseRepos = repos.map(repoWireToRepository);
  const fields = buildAnalysisFieldsFromProcessPayload(item);
  const counts = orderCountsFromProcessWire(item);
  return {
    id: stableProductIdFromWire(item),
    name: item.prod ?? "",
    version: item.version ?? "",
    module: item.module ?? "",
    space: item.space ?? "",
    owner: item.owner ?? "",
    ownerInfo: item.owner_info ?? "",
    icon: resolveProdIconString(item.prod_icon),
    description: item.prod_desc ?? "",
    features: item.function ?? "",
    repositories: mergeRepositoriesWithProcess(baseRepos, item.repo_process),
    analysisStatus: fields.analysisStatus,
    analysisUnified: fields.analysisUnified,
    analysisTimes: fields.analysisTimes,
    ...counts,
    knowledge: knowledgeFromDocProcess(item.doc_process),
  };
}

/** 与 get_prod_info 返回 data[] 单条结构一致（演示 / 非 Tauri 列表源） */
export const MOCK_PROD_INFO_ITEMS: ProdInfoWireItem[] = [
  {
    prod: "智能搜索助手",
    version: "v2.4.1",
    module: "search_core",
    space: "数据智能部",
    owner: "张三",
    function: "智能检索,语义搜索,多源索引",
    prod_icon: "AI 模型 (AI Model)",
    prod_desc: "基于 RAG 架构的企业级智能搜索解决方案，支持多源异构数据索引。",
    owner_info: "<mock-userinfo-encryption>",
    repo_info: [
      {
        repo_url: "https://github.com/rd-agent/search-backend",
        repo_branch: "develop",
        repo_module: "1001|核心检索模块",
        code_path: "apps/backend",
        repo_func: "后端核心业务",
        repo_token: "",
        repo_master: "Y",
      },
      {
        repo_url: "https://github.com/rd-agent/search-frontend",
        repo_branch: "develop",
        repo_module: "1002|前端展示模块",
        code_path: "src",
        repo_func: "前端交互界面",
        repo_token: "",
        repo_master: "N",
      },
    ],
    repo_process: [
      { repo_branch: "develop", repo_process_state: "D", repo_process_time: "2025-03-01 10:00:00" },
      { repo_branch: "feature/ui", repo_process_state: "E" },
    ],
    order_process: "P",
    order_process_time: null,
    doc_process: [
      { doc_type: "需求", doc_process_state: "P" },
      { doc_type: "架构", doc_process_state: "I" },
    ],
  },
  {
    prod: "代码审计工具",
    version: "v1.2.0",
    module: "audit_core",
    space: "基础平台部",
    owner: "李四",
    function: "静态分析,规则引擎,安全扫描",
    prod_icon: "安全审计 (Security)",
    prod_desc: "静态代码分析平台，内置多种安全规则集，支持并发分析任务。",
    owner_info: "<mock-userinfo-encryption>",
    repo_info: [
      {
        repo_url: "https://github.com/rd-agent/code-audit-core",
        repo_branch: "master",
        repo_module: "2001|安全规则引擎",
        code_path: "",
        repo_func: "审计引擎",
        repo_token: "",
        repo_master: "Y",
      },
    ],
    repo_process: [{ repo_branch: "master", repo_process_state: "D", repo_process_time: "2025-04-01 09:15:00" }],
    order_process: "D",
    order_process_time: "2025-04-01 18:30:00",
    doc_process: [
      { doc_type: "需求", doc_process_state: "D", doc_process_time: "2025-04-01 12:00:00" },
      { doc_type: "方案", doc_process_state: "D", doc_process_time: "2025-04-01 14:20:00" },
      { doc_type: "交付", doc_process_state: "D", doc_process_time: "2025-04-01 16:45:00" },
    ],
  },
];

export const MOCK_PRODUCTS: Product[] = MOCK_PROD_INFO_ITEMS.map(prodInfoWireToProduct);
