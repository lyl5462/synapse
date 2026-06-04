#!/usr/bin/env python3
"""Merge upstream openakita/docs-site into local Synapse fork with branding preserved."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UP = REPO_ROOT.parent / "openakita" / "docs-site"
LOC = REPO_ROOT / "docs-site"
SKIP_DIRS = {"node_modules", "dist", "cache"}

# Local fork keeps Apache footer (upstream uses AGPL).
FOOTER_AGPL = 'message: "基于 AGPL-3.0-only 许可发布"'
FOOTER_APACHE = 'message: "基于 Apache-2.0 许可发布"'


def transform(s: str) -> str:
    s = s.replace("openakita_plugin_sdk", "synapse_plugin_sdk")
    s = s.replace("OPENAKITA_", "SYNAPSE_")
    s = s.replace("OpenAkita", "Synapse")
    s = re.sub(r"\bOPENAKITA\b", "SYNAPSE", s)
    s = s.replace("openakita", "synapse")
    return s


def should_skip(p: Path) -> bool:
    return any(part in SKIP_DIRS for part in p.parts)


def main() -> int:
    if len(sys.argv) >= 3:
        global UP, LOC  # noqa: PLW0603
        UP = Path(sys.argv[1]).resolve()
        LOC = Path(sys.argv[2]).resolve()

    if not UP.is_dir():
        print(f"Upstream docs-site not found: {UP}", file=sys.stderr)
        return 1

    count = 0
    for src in sorted(UP.rglob("*")):
        if not src.is_file() or should_skip(src):
            continue

        rel = src.relative_to(UP)
        dst = LOC / rel
        rel_posix = rel.as_posix()

        if rel_posix == ".vitepress/theme/index.ts":
            text = src.read_text(encoding="utf-8")
            text = text.replace("openakita-navigate", "synapse-navigate")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8", newline="\n")
            count += 1
            continue

        if rel_posix == ".vitepress/config.ts":
            text = transform(src.read_text(encoding="utf-8"))
            text = text.replace(FOOTER_AGPL, FOOTER_APACHE)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8", newline="\n")
            count += 1
            continue

        if rel.suffix in {".md", ".ts", ".json"} or rel.name in {"package.json", "package-lock.json"}:
            text = src.read_text(encoding="utf-8", errors="replace")
            text = transform(text)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8", newline="\n")
            count += 1
        elif rel.suffix in {".png", ".ico", ".woff", ".woff2"}:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            count += 1

    print(f"Merged {count} files from {UP} -> {LOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
