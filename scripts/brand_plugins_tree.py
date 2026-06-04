#!/usr/bin/env python3
"""Apply Synapse branding to plugins/ after copying from upstream openakita."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brand_synapse_tree import brand_tree  # noqa: E402

PLUGINS = ROOT / "plugins"


def main() -> None:
    if not PLUGINS.is_dir():
        raise SystemExit(f"plugins/ not found at {PLUGINS}")
    n = brand_tree(PLUGINS)
    print(f"Branded {n} files under {PLUGINS}")


if __name__ == "__main__":
    main()
