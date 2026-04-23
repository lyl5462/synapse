/**
 * 研发统一服务（产品公共服务 IP + 固定端口 10001）HTTP 接口。
 *
 * 约定：仅 **Tauri 桌面模式** 会访问研发统一服务；非 Tauri 环境不应调用本模块（由调用方分支处理）。
 * - 服务地址：`~/.synapse/devservice.ip`（Synapse 用户根）中的真实 IP，仅通过 Tauri `read_devservice_ip` 读取。
 * - `owner_info` / 姓名：仍通过本机 Synapse `GET /api/dev/userinfo-for-unified-service`（桌面通常带本地后端）。
 */

import { IS_TAURI, invoke, proxyFetch } from "@/platform";

/** 研发统一服务固定端口（与引导「产品公共服务」一致） */
export const RD_UNIFIED_PORT = 10001;

export const RD_UNIFIED_PATHS = {
  insertProdInfo: "/dev/iwhalecloud/synapse/create_prod",
  updateProdInfo: "/dev/iwhalecloud/synapse/update_prod_info",
  getProdInfo: "/dev/iwhalecloud/synapse/get_prod_info",
  /** 单产品/仓库维度查询（与 get_prod_info 中 repo_info 结构一致，含 code_path） */
  getRepoInfo: "/dev/iwhalecloud/synapse/get_repo_info",
  getProdProcessInfo: "/dev/iwhalecloud/synapse/get_prod_process_info",
  gitNexusInitialize: "/dev/iwhalecloud/synapse/gitnexus_initialize",
  gitNexusAnalysis: "/dev/iwhalecloud/synapse/gitnexus_analysis",
  orderInitialize: "/dev/iwhalecloud/synapse/order_initialize",
  docsInitialize: "/dev/iwhalecloud/synapse/docs_initialize",
  docsSubmit: "/dev/iwhalecloud/synapse/docs_submit",
  changeRepoInfo: "/dev/iwhalecloud/synapse/change_repo_info",
  destroyProd: "/dev/iwhalecloud/synapse/destroy_prod",
} as const;

export type RdRepoInfo = {
  repo_url: string;
  repo_branch: string;
  /** 产品分支：branchVersionId|branchName（与仓库条目绑定） */
  prod_branch?: string;
  /** 仓库代码路径（create_prod / change_repo_info 提交；get_prod_info / get_repo_info 回读） */
  code_path?: string;
  repo_func: string;
  repo_token: string;
  repo_master: "Y" | "N";
};

/** 仓库分析进度（多仓库按优先级聚合展示）；repo_process_state 单字符 N/I/P/D/E/F（见 normalizeWireProcessState） */
export type RepoProcessWireItem = {
  repo_branch: string;
  /** 产品分支：branchVersionId|branchName */
  prod_branch?: string;
  repo_process_state: string;
  /** 分析完成时间（状态为 D 时由服务端返回，可选） */
  repo_process_time?: string | null;
};

/** 文档维度进度（多文档类型按优先级聚合）；doc_process_state 单字符与仓库一致 */
export type DocProcessWireItem = {
  doc_type: string;
  doc_process_state: string;
  /** 该类型文档分析完成时间（状态为 D 时可选） */
  doc_process_time?: string | null;
};

export type InsertProdInfoBody = {
  prod: string;
  version: string;
  module: string;
  space: string;
  owner: string;
  function: string;
  prod_icon: string;
  prod_desc: string;
  owner_info: string;
  repo_info: RdRepoInfo[];
};

/** 研发统一服务通用 JSON 响应（insert / update 等） */
export type DevServiceResponse = {
  code: number;
  data: unknown;
  message: string;
  total: number;
};

export type UpdateProdInfoBody = {
  prod: string;
  function: string;
  /** 图标标识字符串，服务端据此解析实际图标 */
  prod_icon: string;
  /** 产品描述 */
  prod_desc: string;
};

/** destroy_prod：按产品标识删除 */
export type DestroyProdBody = {
  prod: string;
};

/** 研发统一服务 get_prod_info 单条记录（与 insert 字段对齐）；部分字段服务端可能为 null */
export type ProdInfoWireItem = {
  prod: string | null;
  version: string | null;
  module: string | null;
  space: string | null;
  owner: string | null;
  /** 产品功能（与创建时 function 一致） */
  function: string | null;
  /** 图标标识字符串，前端用 DEFAULT_ICONS label 等规则解析为展示用图标 */
  prod_icon: string | null;
  prod_desc: string | null;
  owner_info: string | null;
  repo_info: RdRepoInfo[] | null;
  /** 各仓库处理状态；多条时按 error > init > process > new > done 聚合（见 pickWorstUnifiedState） */
  repo_process?: RepoProcessWireItem[];
  /** 工单维度单值；字符含义与 repo_process_state 一致 */
  order_process?: string;
  /** 工单分析完成时间（order_process 为 D 时可选） */
  order_process_time?: string | null;
  /** 需求单数量（与 order_process 同级；部分环境字段名可能误带尾部空格，解析见 types 层） */
  demand_order_count?: number;
  /** 研发单数量 */
  task_order_count?: number;
  /** 各文档类型处理状态；聚合规则与 repo_process 相同 */
  doc_process?: DocProcessWireItem[];
};

/** get_prod_info 完整响应；total 为查询到的产品条数，一般与 data.length 一致，不做分页 */
export type GetProdInfoResponse = {
  code: number;
  data: ProdInfoWireItem[] | null;
  message: string;
  total: number;
};

/** get_prod_process_info 入参 */
export type GetProdProcessInfoBody = {
  prod: string;
};

/** get_prod_process_info 的 data 载荷（与列表项中的过程字段一致） */
export type ProdProcessDataPayload = {
  repo_process?: RepoProcessWireItem[];
  order_process?: string;
  order_process_time?: string | null;
  demand_order_count?: number;
  task_order_count?: number;
  doc_process?: DocProcessWireItem[];
};

export type GetProdProcessInfoResponse = {
  code: number;
  data: ProdProcessDataPayload | null;
  message: string;
  total: number;
};

/** gitnexus_initialize：按产品与分支启动 GitNexus 初始化（异步任务） */
export type GitNexusInitializeBody = {
  prod: string;
  repo_branch: string;
  prod_branch: string;
};

/** gitnexus_analysis：按产品与分支重新分析（异步任务）；请求体与 {@link GitNexusInitializeBody} 相同 */
export type GitNexusAnalysisBody = GitNexusInitializeBody;

/** order_initialize：按产品启动工单分析初始化（异步任务） */
export type OrderInitializeBody = {
  prod: string;
};

export type DocsInitializeBody = {
  prod: string;
  doc_type: string;
};

export type DocsSubmitBody = {
  prod: string;
  doc_type: string;
  doc_content: {
    doc_name: string;
    content: string;
  }[];
};

/** change_repo_info：服务端若需产品标识可一并传 prod */
export type ChangeRepoInfoBody = {
  prod: string;
  repo_info: RdRepoInfo[];
};

function rdUnifiedOrigin(host: string): string {
  const h = host.trim();
  if (!h) {
    throw new Error("missing_devservice_host");
  }
  if (h.includes("://")) {
    try {
      const u = new URL(h);
      return `${u.protocol}//${u.hostname}:${RD_UNIFIED_PORT}`;
    } catch {
      throw new Error("invalid_devservice_host");
    }
  }
  const isV4 = /^\d{1,3}(\.\d{1,3}){3}$/.test(h);
  const hostPart = !isV4 && h.includes(":") ? `[${h}]` : h;
  return `http://${hostPart}:${RD_UNIFIED_PORT}`;
}

export async function fetchSynapseJson<T>(
  synapseApiBase: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const base = synapseApiBase.replace(/\/$/, "");
  const res = await fetch(`${base}${path}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(30_000),
  });
  const j = (await res.json()) as { errorcode?: number; message?: string; data?: T };
  if (j.errorcode !== 0) {
    throw new Error(j.message || "synapse_api_error");
  }
  return j.data as T;
}

/**
 * 从 `synapse_root/devservice.ip`（如 `~/.synapse/devservice.ip`）读取产品公共服务真实 IP（仅 Tauri）。
 * 非 Tauri 返回 `null`，调用方不应依赖 Web 降级路径访问 10001。
 */
export async function getDevserviceHost(): Promise<string | null> {
  if (!IS_TAURI) return null;
  try {
    const ip = await invoke<string | null>("read_devservice_ip");
    return ip?.trim() || null;
  } catch {
    return null;
  }
}

/** 代码关系分析图谱前端（与统一服务同机，端口 11001） */
export const CODE_GRAPH_VIEWER_PORT = 11001;
/** 图谱后端服务端口（嵌入页 `server` 查询参数，端口 11011） */
export const CODE_GRAPH_SERVER_PORT = 11011;
/** 工单知识图谱展示页（与统一服务同机，端口 12001，`?prod=` 产品标识） */
export const TICKET_KNOWLEDGE_GRAPH_PORT = 12001;

/**
 * 将 `devservice.ip` 内容规范为 `http://host:port` 中的 host（IPv6 加 `[]`）。
 * 规则与 {@link rdUnifiedOrigin} 中非 URL 分支一致。
 */
export function unifiedServiceHostAuthority(hostRaw: string): string | null {
  const h = hostRaw.trim();
  if (!h) return null;
  if (h.includes("://")) {
    try {
      return formatHostAuthority(new URL(h).hostname);
    } catch {
      return null;
    }
  }
  const bare = h.replace(/^\[|\]$/g, "");
  return formatHostAuthority(bare);
}

function formatHostAuthority(hostname: string): string {
  const isV4 = /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname);
  if (isV4) return hostname;
  if (hostname.includes(":")) return `[${hostname}]`;
  return hostname;
}

/** 从 `repo_branch`（如 `repositoryId|destBranchName`）解析真实分支名：`|` 后为分支；无 `|` 则整段视为分支名。 */
function branchNameFromRepoBranchComposite(repoBranch: string): string {
  const t = repoBranch.trim();
  if (!t) return "";
  const parts = t.split("|").map((p) => p.trim()).filter((p) => p.length > 0);
  if (parts.length >= 2) {
    return parts.slice(1).join("|");
  }
  return parts[0] ?? "";
}

function projectNameFromRepoUrl(repoUrl: string): string {
  const s = repoUrl.trim();
  if (!s) return "";
  try {
    const u = new URL(s);
    const seg = u.pathname.replace(/\/$/, "").split("/").filter(Boolean).pop() ?? "";
    const name = seg.replace(/\.git$/i, "");
    return name || u.hostname || s;
  } catch {
    return s;
  }
}

/**
 * 图谱嵌入页 `repo` 查询参数取值：先由仓库 URL 得到 project（路径最后一段，去掉 `.git`），再结合 `repo_branch`。
 * - 将 `repo_branch` 按 `|` 分割，取 `|` 之后为真实分支名（多段时后续段再拼回，兼容分支名中含 `|` 的极端情况）。
 * - 若分支名为 `master`（大小写不敏感），仅返回 project，不拼接分支。
 * - 否则返回 `project@@branch_name`。
 */
export function codeGraphProjectNameFromRepoUrl(repoUrl: string, repoBranch: string): string {
  const project = projectNameFromRepoUrl(repoUrl);
  if (!project) return "";
  const branchName = branchNameFromRepoBranchComposite(repoBranch);
  if (!branchName) return project;
  if (branchName.toLowerCase() === "master") {
    return project;
  }
  return `${project}@@${branchName}`;
}

/**
 * 代码关系分析图谱嵌入 URL：
 * `http://{host}:11001/?server=http://{host}:11011/&repo={...}`
 */
export function buildCodeGraphEmbedUrl(unifiedServiceHostRaw: string, repo: string): string | null {
  const host = unifiedServiceHostAuthority(unifiedServiceHostRaw);
  const repoParam = repo.trim();
  if (!host || !repoParam) return null;
  const server = `http://${host}:${CODE_GRAPH_SERVER_PORT}/`;
  const viewer = `http://${host}:${CODE_GRAPH_VIEWER_PORT}/`;
  const q = new URLSearchParams({ server, repo: repoParam });
  return `${viewer}?${q.toString()}`;
}

/**
 * 工单知识图谱嵌入 URL：`http://{统一服务 IP}:12001/?prod={产品标识}`
 */
export function buildTicketKnowledgeGraphEmbedUrl(
  unifiedServiceHostRaw: string,
  prod: string,
): string | null {
  const host = unifiedServiceHostAuthority(unifiedServiceHostRaw);
  const prodParam = prod.trim();
  if (!host || !prodParam) return null;
  const base = `http://${host}:${TICKET_KNOWLEDGE_GRAPH_PORT}/`;
  const q = new URLSearchParams({ prod: prodParam });
  return `${base}?${q.toString()}`;
}

/**
 * TCP 探测产品公共服务某端口是否可达（与引导 `probe_devservice_ports` 一致，避免 iframe 内出现浏览器错误白屏）。
 */
export async function probeUnifiedServicePortReachable(
  unifiedServiceHostRaw: string,
  port: number,
): Promise<boolean> {
  if (!IS_TAURI) return false;
  const host = unifiedServiceHostAuthority(unifiedServiceHostRaw);
  if (!host) return false;
  if (!Number.isFinite(port) || port < 1 || port > 65535) return false;
  try {
    const row = await invoke<{ port: number; ok: boolean; error?: string }>("probe_devservice_one_port", {
      ip: host,
      port: port as number,
    });
    return row?.ok === true;
  } catch {
    return false;
  }
}

export async function fetchUserinfoForUnifiedService(synapseApiBase: string): Promise<{
  owner_info: string;
  owner_name: string;
}> {
  return fetchSynapseJson(synapseApiBase, "/api/dev/userinfo-for-unified-service");
}

/** POST 研发统一服务（Tauri `http_proxy_request`） */
export async function postRdUnifiedJson<T>(
  host: string,
  relativePath: string,
  body: unknown,
): Promise<T> {
  const url = `${rdUnifiedOrigin(host)}${relativePath.startsWith("/") ? "" : "/"}${relativePath}`;
  const json = JSON.stringify(body);
  const { status, body: text } = await proxyFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: json,
    timeoutSecs: 60,
  });
  let parsed: T;
  try {
    parsed = JSON.parse(text) as T;
  } catch {
    throw new Error(`rd_unified_invalid_json: HTTP ${status}`);
  }
  if (status >= 400) {
    throw new Error(`rd_unified_http_${status}`);
  }
  return parsed;
}

/**
 * 创建产品：调用研发统一服务 insert_prod_info，并自动附带 owner_info / owner。
 * 仅应在 Tauri 下调用（依赖 `read_devservice_ip` 与 `proxyFetch`）。
 */
export async function insertProdInfo(
  synapseApiBase: string,
  input: Omit<InsertProdInfoBody, "owner_info" | "owner"> & { owner?: string },
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const { owner_info, owner_name } = await fetchUserinfoForUnifiedService(synapseApiBase);
  const owner = (input.owner ?? owner_name ?? "").trim();
  const payload: InsertProdInfoBody = {
    ...input,
    owner,
    owner_info,
  };
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.insertProdInfo,
    payload,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "insert_prod_failed");
  }
  return resp;
}

/**
 * 更新产品信息：研发统一服务 update_prod_info（prod / function / prod_icon / prod_desc）。
 * 仅应在 Tauri 下调用。
 */
export async function updateProdInfo(
  _synapseApiBase: string,
  body: UpdateProdInfoBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.updateProdInfo,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "update_prod_failed");
  }
  return resp;
}

/**
 * 查询产品列表：研发统一服务 get_prod_info，无请求体。
 * 仅应在 Tauri 下调用。数据量通常较小，一次性拉全量、不分页。
 */
export async function getProdInfo(_synapseApiBase: string): Promise<GetProdInfoResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<GetProdInfoResponse>(host, RD_UNIFIED_PATHS.getProdInfo, {});
  if (resp.code !== 0) {
    throw new Error(resp.message || "get_prod_failed");
  }
  return resp;
}

/**
 * 查询单产品分析过程状态：get_prod_process_info，body `{ prod }`。
 * 仅应在 Tauri 下调用。
 */
export async function getProdProcessInfo(
  _synapseApiBase: string,
  body: GetProdProcessInfoBody,
): Promise<GetProdProcessInfoResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<GetProdProcessInfoResponse>(
    host,
    RD_UNIFIED_PATHS.getProdProcessInfo,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "get_prod_process_failed");
  }
  return resp;
}

/**
 * GitNexus 初始化：研发统一服务 gitnexus_initialize（异步执行，成功仅表示任务已提交）。
 * 仅应在 Tauri 下调用。
 */
export async function gitNexusInitialize(
  _synapseApiBase: string,
  body: GitNexusInitializeBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.gitNexusInitialize,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "gitnexus_initialize_failed");
  }
  return resp;
}

/**
 * GitNexus 重新分析：研发统一服务 gitnexus_analysis（异步执行，成功仅表示任务已提交）。
 * 仅应在 Tauri 下调用。
 */
export async function gitNexusAnalysis(
  _synapseApiBase: string,
  body: GitNexusAnalysisBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.gitNexusAnalysis,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "gitnexus_analysis_failed");
  }
  return resp;
}

/**
 * 工单分析初始化：研发统一服务 order_initialize（异步执行，成功仅表示任务已提交）。
 * 仅应在 Tauri 下调用。
 */
export async function orderInitialize(
  _synapseApiBase: string,
  body: OrderInitializeBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.orderInitialize,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "order_initialize_failed");
  }
  return resp;
}

/**
 * 文档初始化：研发统一服务 docs_initialize。
 * 仅应在 Tauri 下调用。
 */
export async function docsInitialize(
  _synapseApiBase: string,
  body: DocsInitializeBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.docsInitialize,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "docs_initialize_failed");
  }
  return resp;
}

/**
 * 文档提交：研发统一服务 docs_submit。
 * 仅应在 Tauri 下调用。
 */
export async function docsSubmit(
  _synapseApiBase: string,
  body: DocsSubmitBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.docsSubmit,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "docs_submit_failed");
  }
  return resp;
}

/**
 * 更新产品仓库配置。
 *
 * **路径**：`POST {devservice}:10001/dev/iwhalecloud/synapse/change_repo_info`（见 {@link RD_UNIFIED_PATHS.changeRepoInfo}）
 *
 * **请求体**：
 * - `prod`：产品名称
 * - `repo_info`：`{ repo_url, repo_branch, prod_branch?, code_path?, repo_func, repo_token, repo_master: "Y"|"N" }[]`
 *
 * 成功后可由调用方再调 {@link getProdProcessInfo} 刷新过程状态。
 */
export async function changeRepoInfo(
  _synapseApiBase: string,
  body: ChangeRepoInfoBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.changeRepoInfo,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "change_repo_failed");
  }
  return resp;
}

/**
 * 删除产品：研发统一服务 destroy_prod，body `{ prod }`。
 * 仅应在 Tauri 下调用。
 */
export type ProductKnowledgeGenerateBody = {
  repo_name: string;
  gitnexus_url: string;
  product_desc: string;
  code_path: string;
  core_features: string;
  local_data_path?: string;
};

export type ProductKnowledgeRefineBody = {
  content: string;
  prompt: string;
};

function assertSynapseEnvelope(data: {
  errorcode?: number;
  message?: string;
}): void {
  if (data.errorcode !== 0) {
    throw new Error(data.message || "synapse_api_error");
  }
}

export async function generateProductKnowledge(
  synapseApiBase: string,
  body: ProductKnowledgeGenerateBody,
): Promise<{ task_id: string }> {
  const resp = await proxyFetch(`${synapseApiBase}/api/dev/iwhalecloud/product_knowledge/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: { errorcode?: number; message?: string; data?: { task_id: string } };
  try {
    data = JSON.parse(resp.body) as typeof data;
  } catch {
    throw new Error(resp.status >= 400 ? resp.body || `HTTP ${resp.status}` : "invalid_json");
  }
  assertSynapseEnvelope(data);
  if (!data.data?.task_id) {
    throw new Error("missing_task_id");
  }
  return data.data;
}

export async function getProductKnowledgeStatus(
  synapseApiBase: string,
  taskId: string,
): Promise<{ status: string; data?: { functional_arch?: string; tech_arch?: string; output?: string }; error?: string }> {
  const resp = await proxyFetch(`${synapseApiBase}/api/dev/iwhalecloud/product_knowledge/status/${taskId}`);
  let data: {
    errorcode?: number;
    message?: string;
    data?: { status: string; data?: { functional_arch?: string; tech_arch?: string }; error?: string };
  };
  try {
    data = JSON.parse(resp.body) as typeof data;
  } catch {
    throw new Error(resp.status >= 400 ? resp.body || `HTTP ${resp.status}` : "invalid_json");
  }
  assertSynapseEnvelope(data);
  if (!data.data) {
    throw new Error("missing_status_payload");
  }
  return data.data;
}

export async function refineProductKnowledge(
  synapseApiBase: string,
  body: ProductKnowledgeRefineBody,
): Promise<{ content: string }> {
  const resp = await proxyFetch(`${synapseApiBase}/api/dev/iwhalecloud/product_knowledge/refine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: { errorcode?: number; message?: string; data?: { content: string } };
  try {
    data = JSON.parse(resp.body) as typeof data;
  } catch {
    throw new Error(resp.status >= 400 ? resp.body || `HTTP ${resp.status}` : "invalid_json");
  }
  assertSynapseEnvelope(data);
  if (data.data?.content === undefined) {
    throw new Error("missing_refined_content");
  }
  return data.data;
}
export async function destroyProd(
  _synapseApiBase: string,
  body: DestroyProdBody,
): Promise<DevServiceResponse> {
  if (!IS_TAURI) {
    throw new Error("rd_unified_tauri_only");
  }
  const host = await getDevserviceHost();
  if (!host) {
    throw new Error("missing_devservice_ip");
  }
  const resp = await postRdUnifiedJson<DevServiceResponse>(
    host,
    RD_UNIFIED_PATHS.destroyProd,
    body,
  );
  if (resp.code !== 0) {
    throw new Error(resp.message || "destroy_prod_failed");
  }
  return resp;
}

export type RdProjectItem = {
  projectId: string;
  projectName: string;
  projectCode: string;
};

/**
 * 从 Synapse 后端获取研发云的项目空间列表。
 * 门户 x-csrf-token / Cookie 由后端从 data/iwhalecloud_session.json 读取并在缺失时自动拉取。
 * 任意能访问 Synapse API 的客户端（含浏览器 dev + `synapse serve`）均可调用。
 */
export async function fetchProjectList(synapseApiBase: string): Promise<RdProjectItem[]> {
  return fetchSynapseJson<RdProjectItem[]>(synapseApiBase, "/api/dev/iwhalecloud/get_project_list", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

/** get_module_name_list 单条模块（研发云精简字段） */
export type RdModuleNameItem = {
  productModuleId?: number | string | null;
  moduleChName?: string | null;
  productVersionId?: number | string | null;
  branchVersionId?: number | string | null;
  productVersionCode?: string | null;
  branchName?: string | null;
};

export type GetModuleNameListData = {
  total: number;
  list: RdModuleNameItem[];
};

/** get_zcm_product_list 单条（全量列表中的项） */
export type RdZcmProductItem = {
  productVersionId?: number | string | null;
  productVersionCode?: string | null;
};

export type GetZcmProductListData = {
  content: RdZcmProductItem[];
  size: number;
};

/**
 * ZCM 产品版本全量列表（POST /api/dev/iwhalecloud/get_zcm_product_list，body 可为 `{}`）。
 * 经 Synapse 转发研发云；非 Tauri 环境同样走 HTTP，与 Tauri 一致。
 */
export async function fetchZcmProductList(synapseApiBase: string): Promise<RdZcmProductItem[]> {
  const data = await fetchSynapseJson<GetZcmProductListData>(
    synapseApiBase,
    "/api/dev/iwhalecloud/get_zcm_product_list",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    },
  );
  const content = data?.content;
  return Array.isArray(content) ? content : [];
}

/**
 * 按项目空间与产品版本拉取应用模块列表（POST /api/dev/iwhalecloud/get_module_name_list）。
 * 经 Synapse 转发研发云；非 Tauri 环境同样走 HTTP。
 */
export async function fetchModuleNameList(
  synapseApiBase: string,
  projectId: number,
  productVersionId: number,
): Promise<RdModuleNameItem[]> {
  const data = await fetchSynapseJson<GetModuleNameListData>(
    synapseApiBase,
    "/api/dev/iwhalecloud/get_module_name_list",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, productVersionId }),
    },
  );
  const list = data?.list;
  return Array.isArray(list) ? list : [];
}

/** get_product_branch_list 单条 */
export type RdProductBranchItem = {
  branchVersionId?: number | string | null;
  branchName?: string | null;
};

export type GetProductBranchListData = {
  total: number;
  list: RdProductBranchItem[];
};

/**
 * 按产品版本查询产品分支（POST /api/dev/iwhalecloud/get_product_branch_list）。
 * 仅传 productVersionId，入库格式 branchVersionId|branchName。
 */
export async function fetchProductBranchList(
  synapseApiBase: string,
  productVersionId: number,
): Promise<RdProductBranchItem[]> {
  const data = await fetchSynapseJson<GetProductBranchListData>(
    synapseApiBase,
    "/api/dev/iwhalecloud/get_product_branch_list",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productVersionId }),
    },
  );
  const list = data?.list;
  return Array.isArray(list) ? list : [];
}

/** get_repo_detail_by_prod_branch 单条；入库仓库分支为 repositoryId|destBranchName */
export type RdRepoDetailRow = {
  repositoryId?: number | string | null;
  repoUrl?: string | null;
  branchName?: string | null;
  destBranchName?: string | null;
};

/**
 * 按产品分支版本 ID 拉取模块仓库与 Git 映射（POST /api/dev/iwhalecloud/get_repo_detail_by_prod_branch）。
 * 与 Synapse 本地路由对接，非 Tauri 亦可走 HTTP。
 */
export async function fetchRepoDetailByProdBranch(
  synapseApiBase: string,
  prodBranchVersionId: number,
  projectId: number,
): Promise<RdRepoDetailRow[]> {
  const data = await fetchSynapseJson<RdRepoDetailRow[]>(
    synapseApiBase,
    "/api/dev/iwhalecloud/get_repo_detail_by_prod_branch",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prod_branch: prodBranchVersionId, projectId }),
    },
  );
  return Array.isArray(data) ? data : [];
}

/**
 * 研发云门户会话保活（`whalecloud_heart`）：仅作语义包装，内部仍为
 * `POST /api/dev/iwhalecloud/get_project_list`，触发后端读 `iwhalecloud_session.json` 并维持门户会话。
 * 失败静默，适合定时器调用。
 */
export async function whalecloudHeart(synapseApiBase: string): Promise<void> {
  if (!IS_TAURI) {
    return;
  }
  try {
    await fetchSynapseJson<RdProjectItem[]>(synapseApiBase, "/api/dev/iwhalecloud/get_project_list", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(120_000),
    });
  } catch {
    /* 保活失败忽略 */
  }
}
