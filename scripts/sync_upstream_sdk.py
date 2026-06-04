#!/usr/bin/env python3
"""Sync openakita-plugin-sdk and packages/plugin-ui-sdk from upstream openakita."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path("D:/github/openakita")
SDK_SRC = UPSTREAM / "openakita-plugin-sdk"
UI_SRC = UPSTREAM / "packages" / "plugin-ui-sdk"
SDK_DST = ROOT / "synapse-plugin-sdk"
UI_DST = ROOT / "packages" / "synapse-plugin-ui-sdk"


def _robocopy(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        "robocopy",
        str(src),
        str(dst),
        "/E",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/nc",
        "/ns",
        "/np",
    ]
    subprocess.run(cmd, check=False)


def _copy_sdk() -> None:
    if not SDK_SRC.is_dir():
        raise SystemExit(f"Missing upstream SDK: {SDK_SRC}")

    (SDK_DST / "src" / "synapse_plugin_sdk").mkdir(parents=True, exist_ok=True)
    (SDK_DST / "docs").mkdir(parents=True, exist_ok=True)

    pkg_src = SDK_SRC / "src" / "openakita_plugin_sdk"
    _robocopy(pkg_src, SDK_DST / "src" / "synapse_plugin_sdk")
    _robocopy(SDK_SRC / "docs", SDK_DST / "docs")

    for name in ("README.md", "pyproject.toml"):
        shutil.copy2(SDK_SRC / name, SDK_DST / name)

    stray = SDK_DST / "src" / "openakita_plugin_sdk"
    if stray.is_dir():
        shutil.rmtree(stray)


def _copy_ui_sdk() -> None:
    if not UI_SRC.is_dir():
        raise SystemExit(f"Missing upstream UI SDK: {UI_SRC}")

    if UI_DST.exists():
        shutil.rmtree(UI_DST)
    shutil.copytree(UI_SRC, UI_DST)


def main() -> None:
    _copy_sdk()
    _copy_ui_sdk()
    brand = ROOT / "scripts" / "brand_synapse_tree.py"
    subprocess.run(
        [sys.executable, str(brand), "synapse-plugin-sdk", "packages/synapse-plugin-ui-sdk"],
        cwd=ROOT,
        check=True,
    )

    pkg_json = UI_DST / "package.json"
    if pkg_json.is_file():
        text = pkg_json.read_text(encoding="utf-8")
        fixed = text.replace(
            '"directory": "packages/plugin-ui-sdk"',
            '"directory": "packages/synapse-plugin-ui-sdk"',
        )
        if fixed != text:
            pkg_json.write_text(fixed, encoding="utf-8", newline="\n")

    print("Sync complete: synapse-plugin-sdk, packages/synapse-plugin-ui-sdk")


if __name__ == "__main__":
    main()
