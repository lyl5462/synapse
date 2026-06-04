#!/usr/bin/env python3
"""Sync src/openakita from upstream clone into src/synapse (Synapse branding).

Preserves fork-only trees and paths listed in PROTECTED / LOCAL_ONLY.
Does not delete local-only files.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_SRC = Path("D:/github/openakita/src/openakita")
LOCAL_SRC = ROOT / "src" / "synapse"

# Align with scripts/resolve_upstream_merge_synapse.py + DIFF.md + fork conventions.
PROTECTED: set[str] = {
    "api/server.py",
    "api/routes/identity.py",
    "api/auth.py",
    "api/schemas.py",
    "llm/registries/providers.json",
    "skills/registry.py",
    "api/routes/config.py",
    "channels/gateway.py",
    "api/routes/agents.py",
    "tools/handlers/agent.py",
}

LOCAL_ONLY_PREFIXES: tuple[str, ...] = (
    "rd_meeting/",
    "api/routes/dev_iwhalecloud",
    "api/routes/gitnexus.py",
    "api/routes/yuque.py",
    "api/routes/meeting_rooms.py",
    "api/routes/work_order_metrics.py",
    "api/routes/dev_iwhalecloud_knowledge.py",
    "api/routes/dev_iwhalecloud_prompt.py",
)

LOCAL_ONLY_FILES: set[str] = {
    "core/policy.py",
    "core/sop_tracking.py",
    "mcp_servers/web_search.py",
    "api/routes/token_stats.py",
    "api/routes/qqbot_onboard.py",
    "Untitled",
}


def _is_local_only(rel: str) -> bool:
    if rel in LOCAL_ONLY_FILES:
        return True
    return any(rel.startswith(p) for p in LOCAL_ONLY_PREFIXES)


def _import_brand():
    sys.path.insert(0, str(ROOT / "scripts"))
    from brand_synapse_tree import transform_text  # noqa: E402

    return transform_text


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _should_brand(path: Path) -> bool:
    if path.suffix in {".py", ".json", ".txt", ".md", ".yaml", ".yml", ".toml"}:
        return True
    return "Dockerfile" in path.name


def sync(*, dry_run: bool = False) -> tuple[int, int, list[str]]:
    if not UPSTREAM_SRC.is_dir():
        raise SystemExit(f"Missing upstream tree: {UPSTREAM_SRC}")

    transform_text = _import_brand()
    copied = 0
    skipped = 0
    skipped_paths: list[str] = []

    for src in sorted(UPSTREAM_SRC.rglob("*")):
        if not src.is_file():
            continue
        if "__pycache__" in src.parts:
            continue

        rel = _rel(src, UPSTREAM_SRC)
        if _is_local_only(rel):
            continue
        if rel in PROTECTED:
            skipped += 1
            skipped_paths.append(rel)
            continue

        dst = LOCAL_SRC / rel
        if dry_run:
            copied += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if _should_brand(dst):
            raw = src.read_text(encoding="utf-8")
            dst.write_text(transform_text(raw, ui_dist=False), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(src, dst)
        copied += 1

    return copied, skipped, skipped_paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Count files only")
    args = parser.parse_args()

    copied, skipped, skipped_paths = sync(dry_run=args.dry_run)
    mode = "would copy" if args.dry_run else "copied"
    print(f"{mode} {copied} files from {UPSTREAM_SRC}")
    print(f"skipped {skipped} protected paths")
    if skipped_paths:
        for p in sorted(skipped_paths):
            print(f"  - {p}")


if __name__ == "__main__":
    main()
