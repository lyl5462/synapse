"""研发工具技能判定工具函数（与前端 whalecloudDevToolSkill.ts 保持一致）。"""

from __future__ import annotations

_WHALECLOUD_DEV_TOOL_PREFIX = "whalecloud_dev_tool_"
_WHALECLOUD_DEV_TOOL_DIR_PREFIX = "whalecloud-dev-tool-"


def is_whalecloud_dev_tool_skill_id(skill_id: str) -> bool:
    """判断一个技能 id 是否属于研发工具类别。

    与前端 isWhalecloudDevToolSkill 逻辑对齐：
    - tool_name 以 whalecloud_dev_tool_ 开头
    - 或 skill_id 以 whalecloud-dev-tool- 开头
    """
    s = (skill_id or "").strip()
    return s.startswith(_WHALECLOUD_DEV_TOOL_PREFIX) or s.startswith(_WHALECLOUD_DEV_TOOL_DIR_PREFIX)
