#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Builtin sync — 把本仓插件同步到 jiuwenswarm 主仓 built_in 装备目录。

内置通道按需使用：建议仅 example-plugin 与少量旗舰插件走 built_in，
其余走 Hub 在线分发（见 docs/design/repo-structure-design.md §7 开放问题 1）。

Usage:
    sync_builtin.py --repo ../jiuwenswarm --only example-plugin
    sync_builtin.py --repo ../jiuwenswarm --all
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
BUILTIN_RELPATH = Path(
    "jiuwenswarm/resources/agent/workspace/plugins/plugin_packages/built_in"
)


def write_stdout(text: str) -> None:
    os.write(1, text.encode("utf-8"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="同步插件到主仓 built_in 目录")
    parser.add_argument("--repo", required=True, help="jiuwenswarm 主仓路径")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--only", help="逗号分隔的插件名列表")
    group.add_argument("--all", action="store_true", help="同步全部插件")
    parser.add_argument("--force", action="store_true", help="目标已存在时先删除再同步")
    args = parser.parse_args()

    main_repo = Path(args.repo).expanduser().resolve()
    builtin_root = main_repo / BUILTIN_RELPATH
    if not main_repo.is_dir():
        write_stdout(f"Error: 主仓路径不存在: {main_repo}\n")
        return 1
    if not (main_repo / ".git").exists():
        write_stdout(f"Error: {main_repo} 不是 git 仓库\n")
        return 1

    if args.all:
        names = sorted(
            p.name for p in PLUGINS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
    else:
        names = [n.strip() for n in args.only.split(",") if n.strip()]

    builtin_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = PLUGINS_DIR / name
        if not src.is_dir():
            write_stdout(f"Error: 找不到插件包目录: {name}\n")
            return 1
        dest = builtin_root / name
        if dest.exists():
            if not args.force:
                write_stdout(f"Error: 目标已存在（--force 覆盖）: {dest}\n")
                return 1
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        write_stdout(f"synced {name} -> {dest}\n")

    write_stdout(
        f"\n完成 {len(names)} 个插件。请在主仓走正常代码评审流程提交，"
        "不要直接 push。\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
