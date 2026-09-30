#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Plugin initializer — 从 templates/plugin-template/ 生成新插件包骨架。

与 jiuwenswarm 主仓 plugin-creator 的 init_plugin.py 输出保持同源
（manifest + README 带 [TODO] 占位，L0 校验会拦截未填充的包）。

Usage:
    init.py my-plugin
    init.py my-plugin --skill usage-guide --tool counter --rail auditor

生成后请阅读 CONTRIBUTING.md 完成填充与校验。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
TEMPLATE_DIR = REPO_ROOT / "templates" / "plugin-template"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def write_stdout(text: str) -> None:
    os.write(1, text.encode("utf-8"))


def _pascal(stem: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_]", stem) if part)


def _snake(stem: str) -> str:
    return re.sub(r"[-]", "_", stem)


def _substitute(text: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="初始化新插件包骨架")
    parser.add_argument("name", help="插件包名（kebab-case，等于 manifest.id 与目录名）")
    parser.add_argument("--skill", metavar="NAME", help="顺带生成 skills/NAME/SKILL.md")
    parser.add_argument("--tool", metavar="NAME", help="顺带生成 tools/NAME_tool.py")
    parser.add_argument("--rail", metavar="NAME", help="顺带生成 rails/NAME_rail.py")
    args = parser.parse_args()

    if not NAME_RE.match(args.name):
        write_stdout(f"Error: 插件名 {args.name!r} 必须是 kebab-case\n")
        return 1
    dest = PLUGINS_DIR / args.name
    if dest.exists():
        write_stdout(f"Error: 插件包已存在: {dest}\n")
        return 1

    mapping = {"PLUGIN_ID": args.name}
    dest.mkdir(parents=True)
    for rel in ("manifest.json", "README.md"):
        text = _substitute((TEMPLATE_DIR / rel).read_text(encoding="utf-8"), mapping)
        (dest / rel).write_text(text, encoding="utf-8")

    components = TEMPLATE_DIR / "components"

    if args.skill:
        skill_name = args.skill
        skill_dir = dest / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        text = _substitute(
            components.joinpath("SKILL.md").read_text(encoding="utf-8"),
            {"SKILL_NAME": skill_name},
        )
        skill_dir.joinpath("SKILL.md").write_text(text, encoding="utf-8")
        write_stdout(f"  + skills/{skill_name}/SKILL.md\n")

    if args.tool:
        stem = _snake(args.tool)
        class_name = f"{_pascal(stem)}Tool"
        tool_id = _snake(stem)
        tool_path = dest / "tools" / f"{stem}_tool.py"
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        text = _substitute(
            components.joinpath("tool_template.py").read_text(encoding="utf-8"),
            {"CLASS_NAME": class_name, "TOOL_ID": tool_id},
        )
        tool_path.write_text(text, encoding="utf-8")
        write_stdout(f"  + tools/{stem}_tool.py（class {class_name}）\n")

    if args.rail:
        stem = _snake(args.rail)
        class_name = f"{_pascal(stem)}Rail"
        rail_path = dest / "rails" / f"{stem}_rail.py"
        rail_path.parent.mkdir(parents=True, exist_ok=True)
        text = _substitute(
            components.joinpath("rail_template.py").read_text(encoding="utf-8"),
            {"CLASS_NAME": class_name},
        )
        rail_path.write_text(text, encoding="utf-8")
        write_stdout(f"  + rails/{stem}_rail.py（class {class_name}）\n")

    write_stdout(f"\n已生成 {dest}\n")
    write_stdout(
        "下一步：\n"
        "  1. 填充 manifest.json / README.md（消灭全部 [TODO]）\n"
        "  2. python scripts/validate.py --only "
        + args.name
        + "   # 默认含 L2 热加载，需 jiuwenswarm 运行环境\n"
        "  3. 补充 tests/plugins/" + args.name + "/ 行为测试\n"
        "  4. python scripts/catalog.py 更新目录清单后提 PR\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
