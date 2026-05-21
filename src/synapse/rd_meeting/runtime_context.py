"""会议室运行时系统参数自动注入（无需在 meeting_room_config 人工配置）。

设计参考 ``dev_iwhalecloud_prompt.build_knowledge_generation_user_prompt`` 的路径/服务
约定段，但字段集合与解析逻辑随会议室场景独立演进。

TODO(jyhk): 从部署 settings、工单快照、产品绑定自动解析并注入：
  - SYNAPSE_URL（Synapse API 基址）
  - GITNEXUS_URL（GitNexus 服务地址）
  - REPO_NAME / repo_url（主仓库，与 GitNexus 一致）
  - GNX_CACHE_DIR（GitNexus materialize 缓存根）
  - WORK_ORDER_DIR / ARCHIVE_DIR（工单 work 目录与节点归档目录）
  解析失败时留空并标注「待运行时解析」，禁止智能体臆造。
"""

from __future__ import annotations

from typing import Any

from synapse.rd_meeting.paths import archive_root, scope_dir
from synapse.rd_sop.nodes import stage_id_for_node_id


def build_meeting_runtime_context_section(
    *,
    scope_type: str,
    scope_id: str,
    ticket_title: str = "",
    node_id: str = "",
    stage_id: int | None = None,
) -> str:
    """生成注入 host/worker prompt 的运行时系统参数段（当前为最小集 + TODO 占位）。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    stg = int(stage_id if stage_id is not None else (stage_id_for_node_id(nid) if nid else 0))
    work_dir = str(scope_dir(sid)) if sid else ""
    archive_dir = ""
    if sid and nid:
        archive_dir = str(archive_root(sid) / str(stg) / nid)

    synapse_url = _resolve_synapse_url()
    gitnexus_url = _resolve_gitnexus_url(scope_type=scope_type, scope_id=sid)

    lines = [
        "## 运行时系统参数（自动注入，勿臆造）",
        f"- SCOPE: {scope_type}/{sid}" if sid else "- SCOPE: （未解析）",
    ]
    if ticket_title:
        lines.append(f"- TICKET_TITLE: {ticket_title}")
    if work_dir:
        lines.append(f"- WORK_ORDER_DIR: {work_dir}")
    if archive_dir:
        lines.append(f"- ARCHIVE_DIR: {archive_dir}")
    lines.append(f"- SYNAPSE_URL: {synapse_url or '（TODO: 待从部署配置自动解析）'}")
    lines.append(f"- GITNEXUS_URL: {gitnexus_url or '（TODO: 待从部署/产品绑定自动解析）'}")
    lines.append("- REPO_NAME: （TODO: 待从工单/产品仓库信息自动解析）")
    lines.append("- GNX_CACHE_DIR: （TODO: 待由 REPO_NAME 推导 GitNexus 缓存路径）")
    return "\n".join(lines)


def _resolve_synapse_url() -> str:
    # TODO: settings.api_host / api_port 或环境变量
    try:
        from synapse.config import settings

        host = str(getattr(settings, "api_host", "") or "127.0.0.1").strip()
        port = int(getattr(settings, "api_port", 0) or 16185)
        return f"http://{host}:{port}"
    except Exception:
        return ""


def _resolve_gitnexus_url(*, scope_type: str, scope_id: str) -> str:
    del scope_type, scope_id
    # TODO: 产品/工单级 GitNexus 端点
    return ""


def runtime_context_for_binding(
    binding: dict[str, Any],
    *,
    scope_type: str,
    scope_id: str,
    ticket_title: str = "",
) -> str:
    node_id = str(binding.get("node_id") or "")
    stage_id = int(binding.get("stage_id") or 0)
    return build_meeting_runtime_context_section(
        scope_type=scope_type,
        scope_id=scope_id,
        ticket_title=ticket_title,
        node_id=node_id,
        stage_id=stage_id or None,
    )
