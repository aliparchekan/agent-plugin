# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""build.py 单测：打包、排除规则与 symlink 拒绝。"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

import build as build_script

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PLUGIN_DIR = REPO_ROOT / "plugins" / "example-plugin"


@pytest.fixture()
def pkg(tmp_path: Path) -> Path:
    dest = tmp_path / "example-plugin"
    shutil.copytree(EXAMPLE_PLUGIN_DIR, dest)
    return dest


def test_build_zip_contains_package(pkg: Path, tmp_path: Path):
    out = tmp_path / "dist"
    zip_path = build_script.build_zip(pkg, out)

    assert zip_path.name == "example-plugin-1.0.0.zip"
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert "example-plugin/manifest.json" in names
    assert "example-plugin/tools/word_count_tool.py" in names
    assert "example-plugin/skills/usage-report/SKILL.md" in names


def test_secret_and_dev_files_excluded(pkg: Path, tmp_path: Path):
    (pkg / "id_rsa").write_text("FAKE KEY", encoding="utf-8")
    (pkg / "credentials.json").write_text("{}", encoding="utf-8")
    (pkg / ".env").write_text("TOKEN=x", encoding="utf-8")
    (pkg / "tests").mkdir()
    (pkg / "tests" / "test_dev.py").write_text("# dev only", encoding="utf-8")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "x.pyc").write_text("", encoding="utf-8")

    out = tmp_path / "dist"
    zip_path = build_script.build_zip(pkg, out)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()

    assert not any("id_rsa" in n for n in names)
    assert not any("credentials.json" in n for n in names)
    assert not any("/.env" in n for n in names)
    assert not any("/tests/" in n for n in names)
    assert not any("__pycache__" in n for n in names)


def test_env_example_is_kept(pkg: Path, tmp_path: Path):
    (pkg / ".env.example").write_text("TOKEN=", encoding="utf-8")

    out = tmp_path / "dist"
    zip_path = build_script.build_zip(pkg, out)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert "example-plugin/.env.example" in names


def test_symlink_rejected(pkg: Path, tmp_path: Path):
    link = pkg / "manifest.json.bak"
    link.symlink_to(pkg / "manifest.json")

    with pytest.raises(build_script.BuildError):
        build_script.build_zip(pkg, tmp_path / "dist")


def test_zip_entries_are_deflated(pkg: Path, tmp_path: Path):
    """手工构造的 ZipInfo 必须显式 ZIP_DEFLATED——否则条目按 STORE 存储。"""
    payload = pkg / "assets" / "big.txt"
    payload.parent.mkdir()
    payload.write_text("abcd1234" * 131072, encoding="utf-8")  # 1 MiB 高重复文本

    zip_path = build_script.build_zip(pkg, tmp_path / "dist")
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo("example-plugin/assets/big.txt")
        assert info.compress_type == zipfile.ZIP_DEFLATED
        assert info.compress_size < info.file_size // 10


def test_env_template_credential_rejected(pkg: Path, tmp_path: Path):
    (pkg / ".env.template").write_text(
        "API_KEY=real-looking-secret-value-123456\n", encoding="utf-8"
    )

    with pytest.raises(build_script.BuildError, match="CREDENTIAL_VALUE"):
        build_script.build_zip(pkg, tmp_path / "dist")


def test_env_template_placeholder_allowed(pkg: Path, tmp_path: Path):
    (pkg / ".env.example").write_text(
        "# 留空或 ${VAR} 占位均可\n"
        "API_KEY=\n"
        "API_SECRET=${API_SECRET}\n"
        'BEARER="Bearer ${HUB_TOKEN}"\n'
        "ENDPOINT=https://api.example.com/v1?token=${ACCESS_TOKEN}\n",
        encoding="utf-8",
    )

    zip_path = build_script.build_zip(pkg, tmp_path / "dist")
    with zipfile.ZipFile(zip_path) as archive:
        assert "example-plugin/.env.example" in archive.namelist()


def test_env_template_url_basic_auth_rejected(pkg: Path, tmp_path: Path):
    (pkg / ".env.example").write_text(
        "ENDPOINT=https://user:pass@api.example.com/v1\n", encoding="utf-8"
    )

    with pytest.raises(build_script.BuildError, match="CREDENTIAL_VALUE"):
        build_script.build_zip(pkg, tmp_path / "dist")
