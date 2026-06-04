#!/usr/bin/env python3
"""Apply Synapse branding to a copied upstream tree (plugins, synapse-plugin-sdk, packages)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "dist",
    ".mypy_cache",
    ".ruff_cache",
}
SKIP_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".mp4",
    ".zip",
    ".exe",
    ".dll",
    ".pdf",
    ".wasm",
    ".min.js.map",
}

_UI_PLACEHOLDERS = {
    "window.OpenAkita": "\x00OA_WIN\x00",
    "OpenAkitaI18n": "\x00OA_I18N\x00",
    "OpenAkitaIcons": "\x00OA_ICONS\x00",
    "openakita:ready": "\x00OA_EVT_READY\x00",
    "openakita:theme-change": "\x00OA_EVT_THEME\x00",
    "openakita:locale-change": "\x00OA_EVT_LOCALE\x00",
    "openakita:event": "\x00OA_EVT_EVENT\x00",
    "__akita_bridge": "\x00OA_BRIDGE\x00",
}


def _is_ui_dist(path: Path) -> bool:
    return "ui" in path.parts and "dist" in path.parts


def transform_text(text: str, *, ui_dist: bool) -> str:
    if ui_dist:
        for orig, ph in _UI_PLACEHOLDERS.items():
            text = text.replace(orig, ph)

    text = text.replace("openakita_plugin_sdk", "synapse_plugin_sdk")
    text = text.replace("openakita-plugin-sdk", "synapse-plugin-sdk")
    text = text.replace("@openakita/plugin-ui-sdk", "@synapse/plugin-ui-sdk")
    text = text.replace("OPENAKITA_", "SYNAPSE_")
    text = text.replace("OpenAkita", "Synapse")
    text = re.sub(r"\bOPENAKITA\b", "SYNAPSE", text)
    text = text.replace("from openakita.", "from synapse.")
    text = text.replace("import openakita.", "import synapse.")
    text = re.sub(r'("openakita"\s*:\s*)', r'"synapse": ', text)
    text = text.replace("MIN_OPENAKITA_VERSION", "MIN_SYNAPSE_VERSION")
    text = text.replace("~/.openakita/", "~/.synapse/")
    text = text.replace("~/.openakita", "~/.synapse")
    text = text.replace("openakita", "synapse")

    if ui_dist:
        rev = {v: k for k, v in _UI_PLACEHOLDERS.items()}
        for ph, orig in rev.items():
            text = text.replace(ph, orig)

    return text


def brand_tree(root: Path) -> int:
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    changed = 0
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(p in SKIP_DIRS for p in path.parts):
            continue
        if path.suffix.lower() in SKIP_EXT:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        new = transform_text(raw, ui_dist=_is_ui_dist(path))
        if new != raw:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="Directories to brand (relative to repo root)")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]

    for rel in args.paths:
        target = (repo / rel).resolve()
        n = brand_tree(target)
        print(f"Branded {n} files under {target}")


if __name__ == "__main__":
    main()
