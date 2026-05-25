# -*- coding: utf-8 -*-
"""
将工程内所有文本文件转换为 UTF-8 编码（无 BOM）。
用法: python convert_to_utf8.py [目录路径]
不传参数则转换脚本所在目录及其子目录。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 尝试的源编码顺序（先 UTF-8 则已为 UTF-8 的不重写也可，这里统一写回 UTF-8 无 BOM）
ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'cp936', 'latin-1', 'cp1252']

# 视为二进制、不转换的扩展名
BINARY_EXT = {
    '.exe', '.dll', '.so', '.dylib', '.a', '.lib', '.o', '.obj',
    '.pyc', '.pyo', '.class', '.jar', '.war',
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.ttf', '.otf', '.woff', '.woff2', '.eot',
    '.bin', '.dat', '.db', '.sqlite',
}

# 可跳过的目录名
SKIP_DIRS = {'.git', '.svn', '__pycache__', 'node_modules', '.idea', '.vs', 'x64', 'x86', 'Debug', 'Release'}


def is_binary(path):
    base, ext = os.path.splitext(path)
    return ext.lower() in BINARY_EXT


def read_with_encoding(path):
    raw = None
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except Exception as e:
        return None, None, str(e)
    if not raw:
        return '', 'utf-8', None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
            return text, enc, None
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None, '无法识别编码'


def convert_file(path, dry_run=False):
    if is_binary(path):
        return 'skip_binary', None
    text, used_enc, err = read_with_encoding(path)
    if err:
        return 'error', err
    if used_enc == 'utf-8' and not (text and text.startswith('\ufeff')):
        return 'already_utf8', None
    if dry_run:
        return 'would_convert', used_enc
    try:
        with open(path, 'w', encoding='utf-8', newline='', errors='strict') as f:
            f.write(text)
        return 'converted', used_enc
    except Exception as e:
        return 'error', str(e)


def convert_directory_to_utf8(
    root: str | Path,
    *,
    dry_run: bool = False,
    reporter: Callable[[str, str, Any], None] | None = None,
) -> dict[str, Any]:
    """递归将目录内文本文件转为 UTF-8（无 BOM）。返回统计摘要。"""
    root_abs = os.path.abspath(str(root))
    stats: dict[str, int] = {"converted": 0, "already_utf8": 0, "skip_binary": 0, "error": 0}
    errors: list[tuple[str, str]] = []

    if not os.path.isdir(root_abs):
        return {"root": root_abs, "stats": stats, "errors": [("", "目录不存在")]}

    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root_abs)
            status, detail = convert_file(path, dry_run=dry_run)
            if status == "would_convert":
                stats["converted"] = stats.get("converted", 0) + 1
            else:
                stats[status] = stats.get(status, 0) + 1
            if status == "error":
                errors.append((rel, str(detail or "")))
            if reporter and status in {"converted", "would_convert", "error"}:
                reporter(rel, status, detail)

    return {"root": root_abs, "stats": stats, "errors": errors}


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(__file__))
    dry_run = '--dry-run' in sys.argv or '-n' in sys.argv
    if dry_run:
        print('【试运行，不写文件】\n')
    print('根目录:', root)
    print('编码尝试顺序:', ', '.join(ENCODINGS))
    print()

    def _report(rel: str, status: str, detail: Any) -> None:
        if status in {'converted', 'would_convert'}:
            print(rel, '-> 从', detail, '转为 UTF-8')
        elif status == 'error':
            print(rel, '-> 失败:', detail)

    result = convert_directory_to_utf8(root, dry_run=dry_run, reporter=_report)
    stats = result["stats"]
    errors = result["errors"]

    print()
    print('统计: 已转换/将转换', stats.get('converted', 0),
          ', 已是 UTF-8', stats.get('already_utf8', 0),
          ', 跳过(二进制)', stats.get('skip_binary', 0),
          ', 失败', stats.get('error', 0))
    if errors:
        print('\n失败文件:')
        for rel, msg in errors:
            print(' ', rel, msg)


if __name__ == '__main__':
    main()
