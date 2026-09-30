#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Package builder — 把 plugins/<name>/ 打成 Hub 发布用的 zip。

排除规则与限制对齐 jiuwenswarm 主仓
``server/runtime/marketplace/asset_package_builder.py`` 的 collect_publish_files：
黑名单目录 / 密钥类文件 / .env*（example、template 除外）/ *.key|*.p12|*.pfx、
拒绝 symlink、文件数 / 总大小 / 路径深度上限。

Usage:
    build.py example-plugin            # 打指定插件
    build.py --all                     # 打全部插件
    build.py example-plugin --output dist/

产物（不进 git）：dist/<id>-<version>.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

EXCLUDED_DIRS = {
    ".git",
    ".archive",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "out",
    ".venv",
    "tests",  # 仓库层开发态文件不应进包（不变量：plugins/ = 分发物 1:1）
    ".idea",
}
EXCLUDED_FILES = {
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "token.json",
    "tokens.json",
    ".DS_Store",
}
EXCLUDED_SUFFIXES = (".key", ".p12", ".pfx", ".pyc")
ENV_ALLOWED = {".env.example", ".env.template"}

MAX_FILES = 10_000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_DEPTH = 32
MAX_ZIP_BYTES = 50 * 1024 * 1024

ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def write_stdout(text: str) -> None:
    os.write(1, text.encode("utf-8"))


class BuildError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 环境模板内容校验（对齐主仓 asset_package_builder._validate_environment_template）
#
# .env.example / .env.template 允许进包，但敏感键（token/key/password/secret/
# credential/authorization）只允许空值或 ${VAR} 占位；URL 不得内嵌用户名口令，
# query 里的敏感参数同样只允许占位。
# ---------------------------------------------------------------------------

_ENV_SENSITIVE_KEY_RE = re.compile(
    r"(token|key|password|secret|credential|authorization)", re.I
)
_ENV_PLACEHOLDER_RE = re.compile(r"(?:Bearer )?\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_ENV_QUERY_PLACEHOLDER_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def _validate_environment_template(path: Path) -> None:
    rel = path.name
    with path.open(encoding="utf-8") as stream:
        while True:
            line = stream.readline(65537)
            if not line:
                break
            if len(line) > 65536:
                raise BuildError(f"LIMIT_EXCEEDED: {rel} 存在超长行")
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            value = value.strip().strip("\"'")
            if "://" in value:
                try:
                    parsed = urlsplit(value)
                except ValueError:
                    raise BuildError(
                        f"CREDENTIAL_VALUE: {rel} 中 {key.strip()} 的 URL 无法安全解析"
                    ) from None
                if parsed.username or parsed.password:
                    raise BuildError(f"CREDENTIAL_VALUE: {rel} 中 {key.strip()} 内嵌凭据")
                if any(
                    _ENV_SENSITIVE_KEY_RE.search(k)
                    and v
                    and not _ENV_QUERY_PLACEHOLDER_RE.fullmatch(v)
                    for k, v in parse_qsl(parsed.query)
                ):
                    raise BuildError(
                        f"CREDENTIAL_VALUE: {rel} 中 {key.strip()} 的 URL 参数含凭据值"
                    )
            if _ENV_SENSITIVE_KEY_RE.search(key):
                if value and not _ENV_PLACEHOLDER_RE.fullmatch(value):
                    raise BuildError(
                        f"CREDENTIAL_VALUE: {rel} 中 {key.strip()} 含疑似凭据值"
                        "（模板只允许空值或 ${VAR} 占位）"
                    )


def collect_publish_files(root: Path) -> tuple[list[Path], list[str]]:
    """收集可发布文件；返回 (files, excluded)。对齐主仓 collect_publish_files。"""
    if root.is_symlink() or not root.is_dir():
        raise BuildError("UNSAFE_PATH")

    files: list[Path] = []
    excluded: list[str] = []
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        names.sort()
        for name in dirs[:]:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if name in EXCLUDED_DIRS:
                dirs.remove(name)
                excluded.append(rel + "/")
            elif path.is_symlink():
                raise BuildError(f"UNSAFE_PATH: symlink 目录 {rel}")
        for name in names:
            path = Path(directory) / name
            rel = path.relative_to(root)
            excluded_env = name.startswith(".env") and name not in ENV_ALLOWED
            excluded_name = name in EXCLUDED_FILES or name.endswith(EXCLUDED_SUFFIXES)
            if excluded_name or excluded_env:
                excluded.append(rel.as_posix())
                continue
            if path.is_symlink():
                raise BuildError(f"UNSAFE_PATH: symlink 文件 {rel.as_posix()}")
            info = path.lstat()
            if not (info.st_mode & 0o170000 == 0o100000):  # 必须是普通文件
                raise BuildError(f"UNSAFE_PATH: 非普通文件 {rel.as_posix()}")
            total += info.st_size
            files.append(path)
            if (
                len(files) > MAX_FILES
                or info.st_size > MAX_TOTAL_BYTES
                or total > MAX_TOTAL_BYTES
                or len(rel.parts) > MAX_DEPTH
            ):
                raise BuildError("LIMIT_EXCEEDED")
    return sorted(files), sorted(excluded)


def build_zip(pkg_dir: Path, output_dir: Path) -> Path:
    manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
    plugin_id = str(manifest.get("id") or pkg_dir.name)
    version = str(manifest.get("version") or "")
    if not plugin_id or not version:
        raise BuildError(f"{pkg_dir.name}: manifest 缺少 id / version")

    files, excluded = collect_publish_files(pkg_dir)
    for file_path in files:
        if file_path.name in ENV_ALLOWED:
            _validate_environment_template(file_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{plugin_id}-{version}.zip"

    digest = hashlib.sha256()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            rel = file_path.relative_to(pkg_dir.parent).as_posix()
            info = zipfile.ZipInfo(rel, date_time=ZIP_TIMESTAMP)
            # 手工构造的 ZipInfo 不继承 ZipFile 的压缩方式，必须显式指定
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = file_path.read_bytes()
            digest.update(data)
            archive.writestr(info, data)

    zip_size = zip_path.stat().st_size
    if zip_size > MAX_ZIP_BYTES:
        zip_path.unlink(missing_ok=True)
        raise BuildError(
            f"LIMIT_EXCEEDED: zip {zip_size} 字节超过 Hub 上限 {MAX_ZIP_BYTES}"
        )

    write_stdout(f"built {zip_path.name}: {len(files)} files, {zip_size} bytes\n")
    write_stdout(f"  sha256: {digest.hexdigest()}\n")
    if excluded:
        preview = ", ".join(excluded[:8])
        more = f" … 共 {len(excluded)} 项" if len(excluded) > 8 else ""
        write_stdout(f"  excluded: {preview}{more}\n")
    return zip_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="打包 plugins/<name>/ 为 Hub 发布 zip")
    parser.add_argument("targets", nargs="*", help="插件包名，或 --all")
    parser.add_argument("--all", action="store_true", help="打包全部插件")
    parser.add_argument("--output", default=str(REPO_ROOT / "dist"), help="输出目录（默认 dist/）")
    args = parser.parse_args()

    if args.all:
        targets = sorted(
            p for p in PLUGINS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
    elif args.targets:
        targets = []
        for name in args.targets:
            pkg_dir = PLUGINS_DIR / name
            if not pkg_dir.is_dir():
                write_stdout(f"Error: 找不到插件包目录: {name}\n")
                return 1
            targets.append(pkg_dir)
    else:
        write_stdout("Error: 指定插件包名或 --all\n")
        return 1

    output_dir = Path(args.output).expanduser().resolve()
    try:
        for pkg_dir in targets:
            build_zip(pkg_dir, output_dir)
    except (BuildError, OSError, json.JSONDecodeError) as exc:
        write_stdout(f"Error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
