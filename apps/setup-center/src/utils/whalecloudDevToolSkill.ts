import type { SkillInfo } from "../types";

/** 研发流程工具判定前缀（与 SKILL 声明的 tool_name 对齐，避免合并冲突） */
export const WHALECLOUD_DEV_TOOL_PREFIX = "whalecloud_dev_tool_" as const;

/** 与后端创建的目录名前缀一致（tool_name 缺失时仍可识别） */
export const WHALECLOUD_DEV_TOOL_DIR_PREFIX = "whalecloud-dev-tool-" as const;

export function isWhalecloudDevToolSkill(skill: SkillInfo): boolean {
  const tn = skill.toolName ?? "";
  if (tn.startsWith(WHALECLOUD_DEV_TOOL_PREFIX)) return true;
  if (skill.skillId.startsWith(WHALECLOUD_DEV_TOOL_DIR_PREFIX)) return true;
  const cat = skill.category ?? "";
  if (cat === "研发工具") return true;
  return false;
}
