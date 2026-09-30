#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""PR 质量检查入口 — CI 门禁（.github/workflows/pr-quality.yml）的本地等价命令。

按顺序执行并汇总：

1. 结构检查：plugins/ 扁平一层、目录名 kebab-case、每目录含 manifest.json
2. L0/L1 校验：scripts/validate.py --no-hot-load（FAIL 即门禁失败）
3. catalog 一致性：scripts/catalog.py --check（防目录清单漂移）
4. 密钥扫描：对 git 跟踪文件做保守正则扫描（私钥 / 云厂商 key / token 字面量）
5. 单元测试：pytest tests/（--skip-tests 可跳过；pytest 缺失时记 SKIP 不失败）

L2 热加载不在本门禁内（需 openjiuwen 运行环境）：
    python scripts/validate.py --require-hot-load   # 在具备运行环境的节点执行

Usage:
    pr_check.py
    pr_check.py --skip-tests
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
SCRIPTS_DIR = Path(__file__).resolve().parent

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PEM 私钥", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("AWS AccessKey", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitCode PAT", re.compile(r"\bgitcode_pat_[A-Za-z0-9]{20,}\b")),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    (
        "凭据字面量",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|password|passwd)\b"
            r"['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
        ),
    ),
]
SECRET_SCAN_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".sh", ".cfg", ".ini", ".env", ".ts", ".js"}
# .env.example / .env.template 的后缀是 .example/.template，靠文件名纳入扫描
SECRET_SCAN_NAMES = {".env.example", ".env.template"}
SECRET_SCAN_SKIP_PARTS = {"__pycache__", ".git", "node_modules", ".venv", "dist"}


def write_stdout(text: str) -> None:
    os.write(1, text.encode("utf-8"))


class CheckResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = True
        self.skipped = False
        self.lines: list[str] = []

    def fail(self, msg: str) -> None:
        self.ok = False
        self.lines.append(f"  x {msg}")

    def note(self, msg: str) -> None:
        self.lines.append(f"  . {msg}")

    def skip(self, msg: str) -> None:
        self.skipped = True
        self.lines.append(f"  . SKIP {msg}")


# ---------------------------------------------------------------------------
# 1. 结构检查
# ---------------------------------------------------------------------------


def check_structure() -> CheckResult:
    result = CheckResult("结构检查（plugins/ 扁平 + 命名 + manifest）")
    if not PLUGINS_DIR.is_dir():
        result.fail("plugins/ 目录不存在")
        return result
    found = 0
    for entry in sorted(PLUGINS_DIR.iterdir()):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            result.fail(f"plugins/ 根下不允许出现文件: {entry.name}")
            continue
        found += 1
        if not NAME_RE.match(entry.name):
            result.fail(f"插件目录名必须是 kebab-case: {entry.name!r}")
        if not (entry / "manifest.json").is_file():
            result.fail(f"{entry.name}/manifest.json 不存在")
    if found == 0:
        result.fail("plugins/ 下没有任何插件包")
    else:
        result.note(f"{found} 个插件包")
    return result


# ---------------------------------------------------------------------------
# 4. 密钥扫描
# ---------------------------------------------------------------------------


def _iter_scan_files() -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return [
            REPO_ROOT / rel
            for rel in completed.stdout.splitlines()
            if rel
            and (
                Path(rel).suffix in SECRET_SCAN_SUFFIXES
                or Path(rel).name in SECRET_SCAN_NAMES
            )
        ]
    except (OSError, subprocess.SubprocessError):
        # 非 git 环境（罕见）退化为文件系统扫描
        files = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SECRET_SCAN_SUFFIXES and path.name not in SECRET_SCAN_NAMES:
                continue
            if any(part in SECRET_SCAN_SKIP_PARTS for part in path.parts):
                continue
            files.append(path)
        return files


def scan_secrets() -> CheckResult:
    result = CheckResult("密钥扫描")
    files = _iter_scan_files()
    hits = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                hits += 1
                rel = path.relative_to(REPO_ROOT).as_posix()
                result.fail(f"{rel}: 疑似 {label}（片段: {match.group(0)[:24]}…）")
    if hits == 0:
        result.note(f"扫描 {len(files)} 个文件，未发现密钥（保守规则；建议 CI 叠加 gitleaks）")
    return result


# ---------------------------------------------------------------------------
# 子进程步骤
# ---------------------------------------------------------------------------


def run_step(name: str, cmd: list[str]) -> CheckResult:
    result = CheckResult(name)
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result.fail(f"无法执行 {' '.join(cmd)}: {exc}")
        return result
    tail = (completed.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        result.note(line)
    if completed.returncode != 0:
        result.ok = False
        for line in (completed.stderr or "").strip().splitlines()[-3:]:
            result.lines.append(f"  x {line}")
    return result


def run_tests(skip: bool) -> CheckResult:
    if skip:
        result = CheckResult("单元测试")
        result.skip("已通过 --skip-tests 跳过")
        return result
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        result = CheckResult("单元测试")
        result.skip("pytest 不可用（CI 请先 pip install pytest）")
        return result
    return run_step(
        "单元测试",
        [sys.executable, "-m", "pytest", str(REPO_ROOT / "tests")],
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="PR 质量检查（CI 门禁的本地等价命令）")
    parser.add_argument("--skip-tests", action="store_true", help="跳过单元测试步骤")
    args = parser.parse_args()

    results = [
        check_structure(),
        run_step(
            "L0/L1 校验",
            [sys.executable, str(SCRIPTS_DIR / "validate.py"), "--no-hot-load"],
        ),
        run_step(
            "catalog 一致性",
            [sys.executable, str(SCRIPTS_DIR / "catalog.py"), "--check"],
        ),
        scan_secrets(),
        run_tests(args.skip_tests),
    ]

    write_stdout("\n======== PR Quality Check ========\n")
    for result in results:
        status = "SKIP" if result.skipped else ("PASS" if result.ok else "FAIL")
        write_stdout(f"[{status}] {result.name}\n")
        for line in result.lines:
            write_stdout(line + "\n")

    failed = [r for r in results if not r.ok]
    if failed:
        write_stdout(
            f"\nRESULT: FAIL   {len(failed)} 项未通过"
            "（L2 热加载另需 openjiuwen 环境：scripts/validate.py --require-hot-load）\n"
        )
        return 1
    write_stdout(
        "\nRESULT: PASS   PR 质量门禁通过"
        "（L2 热加载另需 openjiuwen 环境：scripts/validate.py --require-hot-load）\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
