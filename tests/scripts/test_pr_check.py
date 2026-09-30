# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""pr_check.py 单测：结构检查与密钥扫描。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pr_check

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PLUGIN_DIR = REPO_ROOT / "plugins" / "example-plugin"


# ---------------------------------------------------------------------------
# 结构检查
# ---------------------------------------------------------------------------


def test_structure_ok_on_real_repo():
    result = pr_check.check_structure()
    assert result.ok, result.lines


def test_structure_rejects_file_at_plugins_root(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    shutil.copytree(EXAMPLE_PLUGIN_DIR, plugins_dir / "example-plugin")
    (plugins_dir / "stray.txt").write_text("not allowed", encoding="utf-8")

    monkeypatch.setattr(pr_check, "PLUGINS_DIR", plugins_dir)
    result = pr_check.check_structure()
    assert not result.ok
    assert any("stray.txt" in line for line in result.lines)


def test_structure_rejects_bad_name_and_missing_manifest(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "Bad_Name").mkdir()
    (plugins_dir / "incomplete").mkdir()

    monkeypatch.setattr(pr_check, "PLUGINS_DIR", plugins_dir)
    result = pr_check.check_structure()
    assert not result.ok
    assert any("Bad_Name" in line for line in result.lines)
    assert any("incomplete" in line for line in result.lines)


# ---------------------------------------------------------------------------
# 密钥扫描
#
# 注意：本文件中的模拟凭据一律在运行时拼接，源码里不得出现完整的密钥字面量，
# 否则门禁的密钥扫描会命中本测试文件自身（扫描范围覆盖 tests/）。
# ---------------------------------------------------------------------------


def _scan_text(text: str) -> list[str]:
    hits: list[str] = []
    for label, pattern in pr_check.SECRET_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def test_secret_scan_detects_private_key():
    pem_sample = (
        "-----BEGIN " + "RSA PRIVATE KEY-----\n"
        "MIIEow...\n"
        "-----END " + "RSA PRIVATE KEY-----"
    )
    assert "PEM 私钥" in _scan_text(pem_sample)


def test_secret_scan_detects_cloud_tokens():
    aws_sample = "aws_key = 'AKIA" + "IOSFODNN7EXAMPLE'"
    assert "AWS AccessKey" in _scan_text(aws_sample)
    assert "GitHub Token" in _scan_text("token: ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")


def test_secret_scan_detects_credential_literal():
    credential_sample = 'config = {"api_key": "' + "abcdef01" + '23456789abcdef"}'
    assert "凭据字面量" in _scan_text(credential_sample)


def test_secret_scan_clean_on_examples():
    """example-plugin 的真实代码不应触发任何规则（防误报回归）。"""
    for path in EXAMPLE_PLUGIN_DIR.rglob("*"):
        if path.is_file() and path.suffix in pr_check.SECRET_SCAN_SUFFIXES:
            assert _scan_text(path.read_text(encoding="utf-8")) == [], path


def test_secret_scan_allows_short_placeholder_tokens():
    """文档/模板中的短占位（如 TOKEN=x）不应被误报。"""
    assert _scan_text("TOKEN=x\nPASSWORD=change-me\n") == []


def test_secret_scan_passes_on_repo():
    """整仓扫描必须通过——含本文件的模拟凭据（运行时拼接，源码无完整字面量）。"""
    result = pr_check.scan_secrets()
    assert result.ok, result.lines


def test_secret_scan_covers_env_templates(monkeypatch, tmp_path: Path):
    """.env.example/.env.template 的后缀不在 SUFFIXES 中，必须按文件名纳入扫描。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / ".env.example").write_text(
        "AWS_KEY=AKIA" + "IOSFODNN7EXAMPLE\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)

    monkeypatch.setattr(pr_check, "REPO_ROOT", repo)
    result = pr_check.scan_secrets()
    assert not result.ok
    assert any(".env.example" in line for line in result.lines)
