#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Catalog generator — 扫描 plugins/ 生成 catalog/catalog.json。

catalog 是生成物（lockfile 式，发布时提交）：README 插件目录表格、
产品内置同步清单、Hub 发布对账共用；禁止手改。

Usage:
    catalog.py                 # 生成 catalog/catalog.json（并同步 README 表格）
    catalog.py --check         # 校验已提交的 catalog 与 plugins/ 一致，漂移则退出 1
    catalog.py --no-readme     # 只生成 catalog.json，不动 README
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
CATALOG_PATH = REPO_ROOT / "catalog" / "catalog.json"
README_PATH = REPO_ROOT / "README.md"
SCHEMA_VERSION = 1
CATALOG_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

README_BEGIN = "<!-- catalog:begin -->"
README_END = "<!-- catalog:end -->"


def write_stdout(text: str) -> None:
    os.write(1, text.encode("utf-8"))


def _skill_names(manifest: dict[str, Any]) -> list[str]:
    names = []
    for item in manifest.get("skills") or []:
        if isinstance(item, dict) and isinstance(item.get("dir"), str):
            names.append(Path(item["dir"]).name)
        elif isinstance(item, str):
            names.append(Path(item).name)
    return names


def _class_names(manifest: dict[str, Any], key: str) -> list[str]:
    return [
        str(item.get("class"))
        for item in (manifest.get(key) or [])
        if isinstance(item, dict) and item.get("class")
    ]


def collect_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for pkg_dir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
        manifest_path = pkg_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"{pkg_dir.name}: 缺少 manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{pkg_dir.name}/manifest.json: JSON 解析失败: {exc}") from exc

        plugin_id = str(manifest.get("id") or "")
        if plugin_id != pkg_dir.name:
            raise ValueError(
                f"{pkg_dir.name}: manifest.id ({plugin_id!r}) 必须等于包目录名"
            )
        if plugin_id in seen_ids:
            raise ValueError(f"插件 id 重复: {plugin_id}")
        seen_ids.add(plugin_id)

        version = str(manifest.get("version") or "")
        if not CATALOG_RE.match(version):
            raise ValueError(
                f"{pkg_dir.name}: version ({version!r}) 必须是 X.Y.Z 形式"
            )
        if manifest.get("package_type") != "plugin":
            raise ValueError(
                f"{pkg_dir.name}: package_type 必须是 'plugin'"
            )

        display_name = manifest.get("display_name") or {}
        display_description = manifest.get("display_description") or {}
        entries.append(
            {
                "id": plugin_id,
                "version": version,
                "display_name": display_name if isinstance(display_name, dict) else {},
                "display_description": (
                    display_description if isinstance(display_description, dict) else {}
                ),
                "category": str(manifest.get("category") or ""),
                "tags": manifest.get("tags") if isinstance(manifest.get("tags"), list) else [],
                "capabilities": {
                    "skills": _skill_names(manifest),
                    "tools": _class_names(manifest, "tools"),
                    "rails": _class_names(manifest, "rails"),
                },
                "path": f"plugins/{plugin_id}",
            }
        )
    return entries


def render_catalog(entries: list[dict[str, Any]]) -> str:
    payload = {"schema_version": SCHEMA_VERSION, "plugins": entries}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_readme_table(entries: list[dict[str, Any]]) -> str:
    header = (
        "| 插件 | 版本 | 分类 | 能力组成 | 简介 |\n"
        "| --- | --- | --- | --- | --- |"
    )
    rows = []
    for entry in entries:
        caps = entry["capabilities"]
        parts = []
        if caps["skills"]:
            parts.append(f"{len(caps['skills'])} skill")
        if caps["tools"]:
            parts.append(f"{len(caps['tools'])} tool")
        if caps["rails"]:
            parts.append(f"{len(caps['rails'])} rail")
        rows.append(
            "| [{id}](./{path}) | {version} | {category} | {caps} | {desc} |".format(
                id=entry["id"],
                path=entry["path"],
                version=entry["version"],
                category=entry["category"] or "-",
                caps=" + ".join(parts) or "-",
                desc=str(entry["display_description"].get("zh") or ""),
            )
        )
    return "\n".join([header, *rows])


def sync_readme(entries: list[dict[str, Any]]) -> bool:
    """把表格写入 README 的 catalog 锚点之间；返回是否有改动。"""
    if not README_PATH.is_file() or README_BEGIN not in README_PATH.read_text(encoding="utf-8"):
        return False
    text = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(README_BEGIN) + r".*?" + re.escape(README_END), re.DOTALL
    )
    replacement = README_BEGIN + "\n" + render_readme_table(entries) + "\n" + README_END
    new_text = pattern.sub(replacement, text, count=1)
    if new_text == text:
        return False
    README_PATH.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="生成 / 校验 catalog/catalog.json")
    parser.add_argument("--check", action="store_true", help="校验已提交 catalog 是否漂移")
    parser.add_argument("--no-readme", action="store_true", help="不同步 README 表格")
    args = parser.parse_args()

    try:
        entries = collect_entries()
    except ValueError as exc:
        write_stdout(f"Error: {exc}\n")
        return 1

    rendered = render_catalog(entries)

    if args.check:
        if not CATALOG_PATH.is_file():
            write_stdout("Error: catalog/catalog.json 不存在，先运行 scripts/catalog.py 生成\n")
            return 1
        committed = CATALOG_PATH.read_text(encoding="utf-8")
        if committed != rendered:
            write_stdout(
                "Error: catalog/catalog.json 与 plugins/ 不一致（漂移）。\n"
                "  修复：python scripts/catalog.py 后提交生成的 catalog\n"
            )
            return 1
        write_stdout(f"catalog OK: {len(entries)} 个插件，无漂移\n")
        return 0

    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(rendered, encoding="utf-8")
    write_stdout(f"已生成 {CATALOG_PATH}（{len(entries)} 个插件）\n")

    if not args.no_readme:
        if sync_readme(entries):
            write_stdout("已同步 README.md 插件目录表格\n")
        else:
            write_stdout("README.md 无 catalog 锚点或无改动，跳过\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
