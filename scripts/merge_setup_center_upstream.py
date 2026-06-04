#!/usr/bin/env python3
"""Merge upstream openakita/apps/setup-center into local Synapse fork.

Preserves local-only paths, DIFF.md protected files, and re-applies UI z-index patches.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

UP = Path("D:/github/openakita/apps/setup-center")
LO = Path("D:/github/openakita_jyhk/apps/setup-center")
SKIP_DIRS = {"node_modules", "dist-web", "target", "gen", "dist", ".git"}

# Never overwrite: local-only features, branding assets, docs.
KEEP_LOCAL_PREFIXES = (
    "DIFF.md",
    "android/app/src/main/java/com/synapse/",
    "public/devtoken.mp4",
    "public/iwhalecloud-favicon.ico",
    "src-tauri/icons/",
    "src-tauri/resources/claude-code-init/",
    "src-tauri/resources/claude-code-releases/",
    "src-tauri/resources/synapse-term/",
    "src-tauri/video/",
    "src/assets/logo_b.png",
    "src/api/rdUnifiedService.ts",
    "src/components/product/",
    "src/components/rd-center/",
    "src/components/rd-manage/",
    "src/components/rd-process/",
    "src/components/team-manage/",
    "src/components/WindowsTitleBar.tsx",
    "src/components/ToastContainer.tsx",
    "src/rd-meeting/",
    "src/rd-sop/",
    "src/utils/ownerInfoGuard.ts",
    "src/utils/syncDefaultAgentSkills.ts",
    "src/utils/whalecloudDevToolSkill.ts",
    "src/views/OnboardingCoreAgentPanel.tsx",
    "src/views/OnboardingWhaleSkillsPanel.tsx",
    "src/views/rd-manage/",
    "src/views/workbench/",
    "src-tauri/src/rd_terminal/",
)

# Brand-normalized files with fork-specific behavior — keep local copy.
PROTECTED_FILES = {
    "package.json",
    "package-lock.json",
    "public/manifest.json",
    "src/App.tsx",
    "src/main.tsx",
    "src/constants.ts",
    "src/icons.tsx",
    "src/styles.css",
    "src/hooks/useVersionCheck.ts",
    "src/i18n/en.json",
    "src/i18n/zh.json",
    "src/platform/detect.ts",
    "src/platform/index.ts",
    "src/components/Sidebar.tsx",
    "src/components/CliManager.tsx",
    "src/views/AgentSystemView.tsx",
    "src/views/IdentityView.tsx",
    "src-tauri/Cargo.toml",
    "src-tauri/Cargo.lock",
    "src-tauri/build.rs",
    "src-tauri/tauri.conf.json",
    "src-tauri/capabilities/default.json",
    "src-tauri/src/main.rs",
    "src-tauri/windows/installer.nsi",
    "src-tauri/windows/hooks.nsh",
}

# Upstream-only paths to skip (fork uses Synapse android package).
SKIP_UPSTREAM_ONLY = {
    "android/app/src/main/java/com/openakita/mobile/MainActivity.java",
}

TEXT_SUFFIXES = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".css",
    ".html",
    ".md",
    ".rs",
    ".toml",
    ".nsi",
    ".nsh",
    ".mjs",
    ".yml",
    ".yaml",
    ".svg",
}


def brand_text(content: str) -> str:
    content = content.replace("openakita_plugin_sdk", "synapse_plugin_sdk")
    content = content.replace("OPENAKITA_", "SYNAPSE_")
    content = content.replace("OpenAkita", "Synapse")
    content = re.sub(r"\bOPENAKITA\b", "SYNAPSE", content)
    content = content.replace("com.openakita.mobile", "com.synapse.mobile")
    content = content.replace("openakita-setup-center", "synapse-setup-center")
    content = content.replace("openakita", "synapse")
    return content


def iter_files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in rel.split("/")):
            continue
        out[rel] = path
    return out


def is_keep_local(rel: str) -> bool:
    if rel in PROTECTED_FILES:
        return True
    return any(rel == p or rel.startswith(p) for p in KEEP_LOCAL_PREFIXES)


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def apply_ui_patches(content: str, rel: str) -> str:
    if rel == "src/components/ui/dialog.tsx":
        content = content.replace(" z-50 ", " z-[1210] ")
    elif rel == "src/components/ui/sheet.tsx":
        content = content.replace(" z-50 ", " z-[1200] ")
    elif rel == "src/components/ui/select.tsx":
        content = content.replace("relative z-50 ", "relative z-[1220] ")
    elif rel == "src/components/ui/tooltip.tsx":
        if "showArrow" not in content:
            content = content.replace(
                "  children,\n  ...props\n}: React.ComponentProps<typeof TooltipPrimitive.Content> & {\n  container?: HTMLElement | null;\n}) {",
                "  children,\n  container,\n  showArrow = true,\n  ...props\n}: React.ComponentProps<typeof TooltipPrimitive.Content> & {\n  container?: HTMLElement | null\n  showArrow?: boolean\n}) {",
            )
            content = content.replace(
                "        {children}\n        <TooltipPrimitive.Arrow",
                "        {children}\n        {showArrow ? (\n          <TooltipPrimitive.Arrow",
            )
            content = content.replace(
                '        <TooltipPrimitive.Arrow className="z-50 size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px] bg-foreground fill-foreground" />\n      </TooltipPrimitive.Content>',
                '          <TooltipPrimitive.Arrow className="z-50 size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px] bg-foreground fill-foreground" />\n        ) : null}\n      </TooltipPrimitive.Content>',
            )
    return content


def merge_package_json() -> None:
    local_path = LO / "package.json"
    upstream_path = UP / "package.json"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))

    merged = dict(upstream)
    merged["name"] = local.get("name", "synapse-setup-center")
    merged["description"] = local.get("description", merged.get("description"))
    for section in ("dependencies", "devDependencies"):
        up = upstream.get(section, {})
        loc = local.get(section, {})
        combined = dict(up)
        for key, val in loc.items():
            combined.setdefault(key, val)
        merged[section] = combined

    local_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def copy_upstream_file(rel: str, src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if is_text_file(src):
        text = src.read_text(encoding="utf-8")
        text = brand_text(text)
        text = apply_ui_patches(text, rel)
        dst.write_text(text, encoding="utf-8", newline="\n")
    else:
        shutil.copy2(src, dst)


def main() -> None:
    up_files = iter_files(UP)
    lo_files = iter_files(LO)

    copied = 0
    skipped_keep = 0
    skipped_same = 0

    for rel, src in sorted(up_files.items()):
        if rel in SKIP_UPSTREAM_ONLY:
            continue
        dst = LO / rel.replace("/", "\\") if False else LO / Path(rel)

        if is_keep_local(rel):
            skipped_keep += 1
            continue

        if rel in lo_files and src.read_bytes() == lo_files[rel].read_bytes():
            skipped_same += 1
            continue

        copy_upstream_file(rel, src, dst)
        copied += 1

    merge_package_json()

    print(f"Copied/updated from upstream: {copied}")
    print(f"Skipped (protected/local): {skipped_keep}")
    print(f"Skipped (identical): {skipped_same}")
    print(f"Local-only preserved: {len(set(lo_files) - set(up_files))}")


if __name__ == "__main__":
    main()
