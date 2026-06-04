#!/usr/bin/env python3
"""Sync skills/ from upstream openakita into the Synapse fork.

Preserves local-only skill trees (whalecloud-dev-tool-*, product-knowledge-from-bundle).
Applies Synapse branding after copy via brand_synapse_tree.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path("D:/github/openakita")
SKILLS_SRC = UPSTREAM / "skills"
SKILLS_DST = ROOT / "skills"

LOCAL_ONLY_PREFIXES = ("whalecloud-dev-tool-",)
LOCAL_ONLY_DIRS = frozenset({"product-knowledge-from-bundle"})

# Upstream sidecar names → Synapse runtime (loader.py, i18n.py, bridge.py)
SIDECAR_RENAMES = {
    ".openakita-i18n.json": ".synapse-i18n.json",
    ".openakita-source": ".synapse-source",
    ".openakita-origin.json": ".synapse-origin.json",
}


def _is_local_only(name: str) -> bool:
    if name in LOCAL_ONLY_DIRS:
        return True
    return any(name.startswith(p) for p in LOCAL_ONLY_PREFIXES)


def _robocopy(src: Path, dst: Path) -> int:
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
    proc = subprocess.run(cmd, check=False)
    # robocopy: 0-7 success, >=8 error
    return proc.returncode


def _rename_sidecars() -> None:
    for path in SKILLS_DST.rglob("*"):
        if not path.is_file():
            continue
        for old_name, new_name in SIDECAR_RENAMES.items():
            if path.name != old_name:
                continue
            dest = path.with_name(new_name)
            if dest.exists():
                path.unlink()
            else:
                path.rename(dest)
            break


def _sync_shared_skills() -> None:
    if not SKILLS_SRC.is_dir():
        raise SystemExit(f"Missing upstream skills: {SKILLS_SRC}")

    for child in sorted(SKILLS_SRC.iterdir()):
        if not child.is_dir():
            continue
        if _is_local_only(child.name):
            continue
        code = _robocopy(child, SKILLS_DST / child.name)
        if code >= 8:
            raise SystemExit(f"robocopy failed ({code}) for {child.name}")

    # Root-level files under skills/ (e.g. ATTRIBUTION.md)
    for item in SKILLS_SRC.iterdir():
        if item.is_file():
            dest = SKILLS_DST / item.name
            dest.write_bytes(item.read_bytes())


def main() -> None:
    _sync_shared_skills()

    brand = ROOT / "scripts" / "brand_synapse_tree.py"
    subprocess.run(
        [sys.executable, str(brand), "skills"],
        cwd=ROOT,
        check=True,
    )
    _rename_sidecars()

    preserved = sorted(
        d.name
        for d in SKILLS_DST.iterdir()
        if d.is_dir() and _is_local_only(d.name)
    )
    print(f"Synced from {SKILLS_SRC}")
    print(f"Preserved local-only dirs ({len(preserved)}): {', '.join(preserved)}")


if __name__ == "__main__":
    main()
