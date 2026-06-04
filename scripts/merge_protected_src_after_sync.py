#!/usr/bin/env python3
"""Merge upstream into PROTECTED src/synapse paths after sync_upstream_src.py."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = Path("D:/github/openakita/src/openakita")
LOC = ROOT / "src" / "synapse"

sys.path.insert(0, str(ROOT / "scripts"))
from brand_synapse_tree import transform_text  # noqa: E402


def _read_up(rel: str) -> str:
    return transform_text((UP / rel).read_text(encoding="utf-8"), ui_dist=False)


def _read_loc(rel: str) -> str:
    return (LOC / rel).read_text(encoding="utf-8")


def _write(rel: str, text: str) -> None:
    p = LOC / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def merge_providers_json() -> None:
    up = json.loads((UP / "llm/registries/providers.json").read_text(encoding="utf-8"))
    loc = json.loads(_read_loc("llm/registries/providers.json"))
    up_slugs = {p.get("slug") for p in up if isinstance(p, dict)}
    merged = list(up)
    for entry in loc:
        if isinstance(entry, dict) and entry.get("slug") == "iwhalecloud":
            if "iwhalecloud" not in up_slugs:
                merged.insert(0, entry)
            break
    _write("llm/registries/providers.json", json.dumps(merged, ensure_ascii=False, indent=2) + "\n")


def _extract_block(text: str, start_marker: str, end_marker: str | None = None) -> str:
    i = text.find(start_marker)
    if i < 0:
        raise ValueError(f"marker not found: {start_marker!r}")
    if end_marker:
        j = text.find(end_marker, i + len(start_marker))
        if j < 0:
            raise ValueError(f"end marker not found: {end_marker!r}")
        return text[i:j]
    return text[i:]


def merge_agent_mode_config() -> None:
    loc_block = _extract_block(
        _read_loc("api/routes/config.py"),
        '@router.get("/api/config/agent-mode")',
        "\n\n# ---------------------------------------------------------------------------",
    )
    up = _read_up("api/routes/config.py")
    pattern = r'@router\.get\("/api/config/agent-mode"\).*?(?=\n\n# -{10,})'
    merged, n = re.subn(pattern, loc_block.rstrip(), up, count=1, flags=re.DOTALL)
    if n != 1:
        raise RuntimeError("agent-mode block replace failed")
    _write("api/routes/config.py", merged)


def merge_gateway_mode_command() -> None:
    loc_block = _extract_block(
        _read_loc("channels/gateway.py"),
        "    async def _handle_mode_command(self, user_text: str) -> str:",
        "\n    def _is_agent_command",
    )
    up = _read_up("channels/gateway.py")
    pattern = (
        r"    async def _handle_mode_command\(self, user_text: str\) -> str:.*?"
        r"(?=\n    def _is_agent_command)"
    )
    merged, n = re.subn(pattern, loc_block.rstrip() + "\n", up, count=1, flags=re.DOTALL)
    if n != 1:
        raise RuntimeError("gateway mode command replace failed")
    _write("channels/gateway.py", merged)


def merge_agent_handler_orchestrator() -> None:
    loc_block = _extract_block(
        _read_loc("tools/handlers/agent.py"),
        "    def _get_orchestrator(self):",
        "\n    def _get_profile_store(self):",
    )
    up = _read_up("tools/handlers/agent.py")
    pattern = r"    def _get_orchestrator\(self\):.*?(?=\n    def _get_profile_store\(self\):)"
    merged, n = re.subn(pattern, loc_block.rstrip() + "\n", up, count=1, flags=re.DOTALL)
    if n != 1:
        raise RuntimeError("agent handler orchestrator replace failed")
    _write("tools/handlers/agent.py", merged)


def merge_agents_route_guards() -> None:
    """Upstream agents.py + manual multi_agent guards (see agents.py after sync)."""
    _write("api/routes/agents.py", _read_up("api/routes/agents.py"))


def merge_identity_fork_bits() -> None:
    loc = _read_loc("api/routes/identity.py")
    up = _read_up("api/routes/identity.py")

    helpers = _extract_block(loc, "# Persona files that must not be removed", "def _get_agent")
    delete_ep = _extract_block(loc, '@router.delete("/file")', '@router.post("/validate")')

    if "# Persona files that must not be removed" not in up:
        anchor = "def _resolve_file(name: str) -> Path:"
        pos = up.find(anchor)
        if pos < 0:
            raise RuntimeError("identity _resolve_file anchor missing")
        up = up[:pos] + helpers + "\n\n" + up[pos:]

    if '@router.delete("/file")' not in up:
        anchor = '@router.post("/validate")'
        pos = up.find(anchor)
        if pos < 0:
            raise RuntimeError("identity validate anchor missing")
        up = up[:pos] + delete_ep + "\n\n" + up[pos:]

    # import_persona uses sanitizer
    if "_sanitize_persona_upload_filename" in loc and "safe_name = _sanitize_persona_upload_filename" in loc:
        up = re.sub(
            r"safe_name\s*=\s*[^\n]+\n",
            "    safe_name = _sanitize_persona_upload_filename(file.filename)\n",
            up,
            count=1,
        )

    _write("api/routes/identity.py", up)


def merge_server_fork_bits() -> None:
    loc = _read_loc("api/server.py")
    up = _read_up("api/server.py")

    extra_imports = """    dev_iwhalecloud,
    meeting_rooms,
    gitnexus,
    work_order_metrics,
    yuque,"""
    for name in ("dev_iwhalecloud", "meeting_rooms", "gitnexus", "work_order_metrics", "yuque"):
        if f"    {name}," not in up:
            up = up.replace("    config,", f"    config,\n    {name},", 1)

    routers = [
        ('    app.include_router(token_stats.router, tags=["统计"])', ""),
        (
            '    app.include_router(orgs.inbox_router, tags=["组织消息中心"])',
            """    app.include_router(yuque.router, tags=["语雀"])
    app.include_router(gitnexus.router, tags=["GitNexus"])
    app.include_router(dev_iwhalecloud.router, tags=["研发云"])
    app.include_router(meeting_rooms.router, tags=["研发会议室"])
    app.include_router(work_order_metrics.router, tags=["工单库指标"])""",
        ),
    ]
    for anchor, block in routers:
        if block and anchor in up and "dev_iwhalecloud.router" not in up:
            up = up.replace(anchor, anchor + "\n" + block, 1)

    if "access_logger = logging.getLogger" not in up and "access_logger = logging.getLogger" in loc:
        up = up.replace(
            "logger = logging.getLogger(__name__)\n",
            "logger = logging.getLogger(__name__)\n"
            '# HTTP 接口访问日志（create_app 中注册中间件：入站/出站各一条，仅 /api 前缀）\n'
            'access_logger = logging.getLogger("synapse.api.access")\n\n',
            1,
        )

    if "access_logger.info" in loc and "access_logger.info" not in up:
        # graft middleware from local create_app
        m = re.search(
            r"@app\.middleware\(\"http\"\)\s+async def log_api_access.*?return response\n",
            loc,
            flags=re.DOTALL,
        )
        if m:
            insert_at = up.find("@app.exception_handler(RequestValidationError)")
            if insert_at > 0:
                up = up[:insert_at] + m.group(0) + "\n\n    " + up[insert_at:]

    if "synapse-api" not in up:
        up = up.replace('thread_name_prefix="openakita-api"', 'thread_name_prefix="synapse-api"')
        up = up.replace('thread_name_prefix="synapse-api"', 'thread_name_prefix="synapse-api"')

    _write("api/server.py", up)


def main() -> None:
    merge_providers_json()
    merge_agent_mode_config()
    merge_gateway_mode_command()
    merge_agent_handler_orchestrator()
    merge_identity_fork_bits()
    merge_server_fork_bits()
    _write("api/auth.py", _read_up("api/auth.py"))
    # schemas/registry: keep local fork versions (success_response, marketplace hosts)
    print("Protected merge complete.")
    print("Kept local: api/schemas.py, skills/registry.py")
    print("Note: re-apply multi_agent guards in api/routes/agents.py if you reset that file from upstream.")


if __name__ == "__main__":
    main()
