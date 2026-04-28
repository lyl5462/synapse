import type { SkillInfo } from "../types";

/** 研发流程工具判定前缀（与 SKILL 声明的 tool_name 对齐，避免合并冲突） */
export const WHALECLOUD_DEV_TOOL_PREFIX = "whalecloud_dev_tool_" as const;

/** 与后端创建的目录名前缀一致（tool_name 缺失时仍可识别） */
export const WHALECLOUD_DEV_TOOL_DIR_PREFIX = "whalecloud-dev-tool-" as const;

/** 产品架构文档生成：推荐默认勾选的架构文档技能 */
export const RD_TOOL_ARCH_CREATE = "whalecloud-dev-tool-arch-create";
/** 产品架构文档生成：推荐默认勾选的图示 / Excalidraw */
export const RD_TOOL_EXCALIDRAW = "whalecloud-dev-tool-excalidraw";
/** 产品架构文档修改（refine）：推荐默认勾选的修改技能 */
export const RD_TOOL_ARCH_MODIFY = "whalecloud-dev-tool-arch-modify";

/** 架构文档生成：推荐默认勾选的技能（用户可取消，也可另选其他技能） */
export const RD_TOOL_GENERATE_REQUIRED = [RD_TOOL_ARCH_CREATE, RD_TOOL_EXCALIDRAW] as const;

/** 架构文档 refine：推荐默认勾选的技能 */
export const RD_TOOL_REFINE_REQUIRED = [RD_TOOL_ARCH_MODIFY, RD_TOOL_EXCALIDRAW] as const;

export const RD_TOOL_GENERATE_REQUIRED_SET = new Set<string>(RD_TOOL_GENERATE_REQUIRED);
export const RD_TOOL_REFINE_REQUIRED_SET = new Set<string>(RD_TOOL_REFINE_REQUIRED);

/** UI 兜底文案（catalog 尚未加载或无对应项时） */
export const RD_TOOL_FALLBACK_LABELS: Record<string, string> = {
  [RD_TOOL_ARCH_CREATE]: "产品架构文档生成工具",
  [RD_TOOL_EXCALIDRAW]: "设计画图工具",
  [RD_TOOL_ARCH_MODIFY]: "产品架构文档修改工具",
};

/** 去重、去空白，保持首次出现顺序 */
export function uniqueRdSkillIds(ids: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of ids) {
    const id = raw.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

/** 无显式入参时：为生成任务提供「推荐默认」技能集（与 UI 首次打开一致） */
export function buildRdSkillIdsForGenerate(optionalSkillIds: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of RD_TOOL_GENERATE_REQUIRED) {
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  for (const raw of optionalSkillIds) {
    const id = raw.trim();
    if (!id || RD_TOOL_GENERATE_REQUIRED_SET.has(id)) continue;
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/** refine：推荐默认 + 额外可选（向后兼容；新 UI 请用 uniqueRdSkillIds） */
export function buildRdSkillIdsForRefine(optionalSkillIds: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of RD_TOOL_REFINE_REQUIRED) {
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  for (const raw of optionalSkillIds) {
    const id = raw.trim();
    if (!id || RD_TOOL_REFINE_REQUIRED_SET.has(id)) continue;
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

export function isWhalecloudDevToolSkill(skill: SkillInfo): boolean {
  const tn = skill.toolName ?? "";
  if (tn.startsWith(WHALECLOUD_DEV_TOOL_PREFIX)) return true;
  if (skill.skillId.startsWith(WHALECLOUD_DEV_TOOL_DIR_PREFIX)) return true;
  const cat = skill.category ?? "";
  if (cat === "研发工具") return true;
  return false;
}

/** 研发工具等在列表/选择器中的展示名：`label` 优先，否则 name_i18n / name（调用 API 仍用 skillId） */
export function rdToolDisplayLabel(skill: SkillInfo, lang?: string): string {
  const lab = skill.label?.trim();
  if (lab) return lab;
  const key = !lang || lang.startsWith("zh") ? "zh" : lang;
  return skill.name_i18n?.[key] || skill.name_i18n?.en || skill.name;
}
