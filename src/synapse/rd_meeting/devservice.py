"""产品公共服务：读取 ``devservice.ip`` 并生成固定端口 URL。"""

from __future__ import annotations

import re
from pathlib import Path
from synapse.api.routes.dev_iwhalecloud import _devservice_ip_path, _devservice_ip_path_legacy
from synapse.config import settings

RD_UNIFIED_PORT = 10001
GITNEXUS_SERVER_PORT = 11011

_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def read_devservice_host() -> str | None:
    """读取 ``synapse_home/devservice.ip``（一行 IP/主机名）；旧路径回退。"""
    for path in (_devservice_ip_path(), _devservice_ip_path_legacy()):
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw:
            return raw.splitlines()[0].strip()
    return None


def format_host_authority(host_raw: str) -> str | None:
    """规范为 URL 可用的 host（IPv6 加 ``[]``）。"""
    h = (host_raw or "").strip()
    if not h:
        return None
    if "://" in h:
        from urllib.parse import urlparse

        try:
            return format_host_authority(urlparse(h).hostname or "")
        except Exception:
            return None
    bare = h.strip("[]")
    if _IPV4_RE.match(bare):
        return bare
    if ":" in bare:
        return f"[{bare}]"
    return bare


def unified_service_base_url() -> str:
    """研发统一服务 ``http://{host}:10001``。"""
    host = read_devservice_host()
    auth = format_host_authority(host or "")
    if not auth:
        return ""
    return f"http://{auth}:{RD_UNIFIED_PORT}"


def gitnexus_service_base_url() -> str:
    """GitNexus 后端 ``http://{host}:11011``。"""
    host = read_devservice_host()
    auth = format_host_authority(host or "")
    if not auth:
        return ""
    return f"http://{auth}:{GITNEXUS_SERVER_PORT}"


def gnx_cache_base_dir() -> str:
    """GitNexus 缓存根目录；访问具体仓库时再拼接 ``repo_name``。"""
    try:
        return str(settings.synapse_home / "tmp" / "gitnexus")
    except Exception:
        return ""


def gnx_cache_dir_for_repo(repo_name: str) -> str:
    """按仓库名拼接缓存目录（运行时拉代码/分析用）。"""
    base = gnx_cache_base_dir()
    name = (repo_name or "").strip()
    if not base or not name:
        return ""
    return str(Path(base) / name)
