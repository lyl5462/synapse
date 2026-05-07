/** 与 Synapse 接口 `data` 字段一致：研发子单 */
export interface OwnedWorkItem {
  task_no: string;
  task_title: string;
  task_desc: string;
  created_date: string;
  sccb_work_hours: number | null;
  stage_name?: string;
  product_module_id: number | null;
  product_module_name: string;
  repo_url: string;
  /** 该研发单当前 SOP 节点（中文名或节点 id）；为空时回退到需求单 sop_node */
  sop_node?: string;
}

/** 与 Synapse 接口 `data.list[]` 一致：需求单 */
export interface DemandListItem {
  demand_no: string;
  demand_title: string;
  demand_desc: string;
  demand_create_time: string;
  /** 已处理时长等展示文案 */
  demand_deal_time?: string;
  demand_finish_time: string;
  demand_sccb_work_minutes: number;
  demand_status: string;
  demand_impact: string;
  demand_designer: string;
  product_version_id: number | null;
  product_version_code: string;
  /** 当前 SOP 节点名或 id；待处理时必为「等待调度」；预备中/全人工时必为空串 */
  sop_node: string;
  /** 预备中 | 待处理 | 处理中 | 全人工 等 */
  local_process_state: string;
  owned_work_items: OwnedWorkItem[];
}

export interface RdManageDemandsPayload {
  list: DemandListItem[];
  updated_at?: string;
}

/**
 * 前端 Mock：与真实接口 `data` 形状一致。
 * 规则：待处理 → sop_node 必为「等待调度」；预备中 / 全人工 → sop_node 必为空串。
 */
export function getRdManageDemandsMockPayload(): RdManageDemandsPayload {
  return {
    updated_at: new Date().toISOString(),
    list: [
      {
        demand_no: "21812816",
        demand_title:
          "【BSS3.0-账务中心】-甘肃- MDB一键限流功能需求：支持全集群/IP/应用名称限流及RESTful API接入b",
        demand_desc:
          "【拷贝自需求 #21731949 】\n在MDB中新增一键限流功能，支持全集群/IP/应用名称限流及 RESTful API。",
        demand_create_time: "2026-03-02 09:22:13",
        demand_deal_time: "59天9小时",
        demand_finish_time: "",
        demand_sccb_work_minutes: 0,
        demand_status: "待处理",
        demand_impact: "",
        demand_designer: "",
        product_version_id: null,
        product_version_code: "",
        sop_node: "等待调度",
        local_process_state: "待处理",
        owned_work_items: [],
      },
      {
        demand_no: "21878317",
        demand_title: "【北京电信】信控预占后增加写提醒MQ的功能--优化",
        demand_desc:
          "基于需求#21862731进行优化：由账务触发的预占，信控预占完成后发 MQ 给账务。",
        demand_create_time: "2026-04-29 16:37:45",
        demand_deal_time: "1天2小时",
        demand_finish_time: "",
        demand_sccb_work_minutes: 960,
        demand_status: "需求开发",
        demand_impact: "",
        demand_designer: "叶彬彬[0027008730]",
        product_version_id: 13590,
        product_version_code: "CBOSS_BSS_RATECTR_V3.1",
        sop_node: "环境预生成",
        local_process_state: "处理中",
        owned_work_items: [
          {
            task_no: "11879580",
            task_title: "【北京电信】信控预占后增加写提醒MQ的功能--优化",
            task_desc:
              "方案详见：\nhttps://alidocs.dingtalk.com/i/nodes/oP0MALyR8k795XrxcKyPRpMz83bzYmDO?utm_scene=team_space\n 三.系统设计",
            created_date: "2026-04-30 09:17:43",
            sccb_work_hours: null,
            stage_name: "开发中",
            product_module_id: 18598,
            product_module_name: "RATECTR-ZXBilling",
            repo_url: "https://git-nj.iwhalecloud.com/xmjfbss/RATECTR-ZXBilling.git",
            sop_node: "差异分析",
          },
          {
            task_no: "11879581",
            task_title: "【北京电信】MQ 流框字段对齐与单测",
            task_desc: "对齐缴费变更通知 Format_id 与单测补充。",
            created_date: "2026-04-30 10:05:00",
            sccb_work_hours: 4,
            stage_name: "开发中",
            product_module_id: 18598,
            product_module_name: "RATECTR-ZXBilling",
            repo_url: "https://git-nj.iwhalecloud.com/xmjfbss/RATECTR-ZXBilling.git",
            sop_node: "环境预生成",
          },
        ],
      },
      {
        demand_no: "21899999",
        demand_title: "【全人工】仅人工处理需求单",
        demand_desc: "无研发子单或子单不参与智能流水线时，右侧展示人工说明。",
        demand_create_time: "2026-04-20 09:00:00",
        demand_deal_time: "5天",
        demand_finish_time: "",
        demand_sccb_work_minutes: 200,
        demand_status: "需求开发",
        demand_impact: "",
        demand_designer: "赵六",
        product_version_id: 13590,
        product_version_code: "CBOSS_BSS_RATECTR_V3.1",
        sop_node: "",
        local_process_state: "全人工",
        owned_work_items: [],
      },
      {
        demand_no: "PREPARE-2026-0001",
        demand_title: "【预备】统一计费规则预研",
        demand_desc: "产品侧预研单，尚未进入智能研发流水线。",
        demand_create_time: "2026-04-28 10:00:00",
        demand_deal_time: "",
        demand_finish_time: "",
        demand_sccb_work_minutes: 120,
        demand_status: "草稿",
        demand_impact: "",
        demand_designer: "张三",
        product_version_id: 10001,
        product_version_code: "CBOSS_BSS_CORE_V2.0",
        sop_node: "",
        local_process_state: "预备中",
        owned_work_items: [],
      },
      {
        demand_no: "PROC-2026-0002",
        demand_title: "【处理中】多研发单拆分示例",
        demand_desc: "同一需求下挂两条研发单，用于左侧虚线分组展示。",
        demand_create_time: "2026-04-25 14:00:00",
        demand_deal_time: "3天",
        demand_finish_time: "",
        demand_sccb_work_minutes: 480,
        demand_status: "需求开发",
        demand_impact: "",
        demand_designer: "李四",
        product_version_id: 13590,
        product_version_code: "CBOSS_BSS_RATECTR_V3.1",
        sop_node: "方案评审",
        local_process_state: "处理中",
        owned_work_items: [
          {
            task_no: "TASK-PROC-01",
            task_title: "子单 A：接口层改造",
            task_desc: "REST 限流网关接入",
            created_date: "2026-04-26 09:00:00",
            sccb_work_hours: 16,
            stage_name: "开发中",
            product_module_id: 20001,
            product_module_name: "gateway-module",
            repo_url: "https://git.example.com/org/gateway.git",
            sop_node: "方案评审",
          },
          {
            task_no: "TASK-PROC-02",
            task_title: "子单 B：配置中心下发",
            task_desc: "限流策略动态下发",
            created_date: "2026-04-26 10:30:00",
            sccb_work_hours: 12,
            stage_name: "开发中",
            product_module_id: 20002,
            product_module_name: "config-service",
            repo_url: "https://git.example.com/org/config.git",
            sop_node: "沙箱构建",
          },
        ],
      },
      {
        demand_no: "DONE-2026-0003",
        demand_title: "【已完成】示例归档单",
        demand_desc: "用于展示已完成态流水线。",
        demand_create_time: "2026-03-01 08:00:00",
        demand_deal_time: "30天",
        demand_finish_time: "2026-04-01 18:00:00",
        demand_sccb_work_minutes: 3200,
        demand_status: "已完成",
        demand_impact: "",
        demand_designer: "王五",
        product_version_id: 13590,
        product_version_code: "CBOSS_BSS_RATECTR_V3.1",
        sop_node: "研发组长评审",
        local_process_state: "已完成",
        owned_work_items: [],
      },
    ],
  };
}

const OWNER_ORDER_SNAPSHOT_PATH = "/api/dev/iwhalecloud/owner_order_snapshot";

/** 将快照 `data` 规范为看板可用的 {@link RdManageDemandsPayload} */
function normalizeOwnerOrderSnapshotData(raw: unknown): RdManageDemandsPayload {
  if (!raw || typeof raw !== "object") {
    return { list: [] };
  }
  const o = raw as Record<string, unknown>;
  const listRaw = o.list;
  const list = Array.isArray(listRaw) ? listRaw : [];
  const out: DemandListItem[] = [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const d = row as Record<string, unknown>;
    const wi = d.owned_work_items;
    const owned = Array.isArray(wi) ? wi : [];
    out.push({
      ...(d as unknown as DemandListItem),
      owned_work_items: owned as OwnedWorkItem[],
    });
  }
  return {
    list: out,
    updated_at: typeof o.updated_at === "string" ? o.updated_at : undefined,
  };
}

type SynapseWire = {
  errorcode?: number;
  message?: string;
  data?: unknown;
};

/**
 * 拉取智能任务看板数据：读取 Synapse 落地的负责人需求快照（`userwork.json`）。
 *
 * - 成功：`GET /api/dev/iwhalecloud/owner_order_snapshot` → `data` 与 {@link RdManageDemandsPayload} 一致。
 * - 404（尚未调用 `get_demand_by_user` 生成快照）：返回空列表。
 * - 其它网络/服务端错误：回退前端 Mock，便于离线联调 UI。
 */
export async function fetchRdManageDemands(synapseApiBase: string): Promise<RdManageDemandsPayload> {
  const base = synapseApiBase.replace(/\/$/, "");
  try {
    const res = await fetch(`${base}${OWNER_ORDER_SNAPSHOT_PATH}`, {
      signal: AbortSignal.timeout(60_000),
    });
    const j = (await res.json()) as SynapseWire;
    if (j.errorcode !== 0) {
      if (j.errorcode === 404) {
        return { list: [], updated_at: undefined };
      }
      throw new Error(j.message || "owner_order_snapshot_error");
    }
    return normalizeOwnerOrderSnapshotData(j.data);
  } catch {
    return getRdManageDemandsMockPayload();
  }
}
