# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""catalog.py 单测：收集、生成与漂移检测（monkeypatch 到临时目录）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import catalog
import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PLUGIN_DIR = REPO_ROOT / "plugins" / "example-plugin"


def _make_plugin(root: Path, name: str, version: str = "1.0.0") -> Path:
    pkg = root / name
    shutil.copytree(EXAMPLE_PLUGIN_DIR, pkg)
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = name
    manifest["version"] = version
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return pkg


def _patch(monkeypatch, tmp_path: Path) -> Path:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    monkeypatch.setattr(catalog, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(catalog, "CATALOG_PATH", tmp_path / "catalog" / "catalog.json")
    monkeypatch.setattr(catalog, "README_PATH", tmp_path / "README.md")
    return plugins_dir


def test_collect_entries_from_example(monkeypatch, tmp_path: Path):
    _patch(monkeypatch, tmp_path)
    _make_plugin(tmp_path / "plugins", "demo-plugin")

    entries = catalog.collect_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == "demo-plugin"
    assert entry["version"] == "1.0.0"
    assert entry["path"] == "plugins/demo-plugin"
    assert entry["capabilities"]["skills"] == ["usage-report"]
    assert entry["capabilities"]["tools"] == ["WordCountTool"]
    assert entry["capabilities"]["rails"] == ["TurnCounterRail"]


def test_id_mismatch_rejected(monkeypatch, tmp_path: Path):
    plugins_dir = _patch(monkeypatch, tmp_path)
    pkg = _make_plugin(plugins_dir, "demo-plugin")
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = "wrong-id"
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    try:
        catalog.collect_entries()
        raised = False
    except ValueError as exc:
        raised = "必须等于包目录名" in str(exc)
    assert raised


def test_cross_package_duplicate_id_impossible(monkeypatch, tmp_path: Path):
    """id == 目录名的强制约束使跨包重复 id 在结构上不可达：伪装重复 id
    会被 id 校验先行拦截（防御深度由 collect_entries 的 seen_ids 兜底）。"""
    plugins_dir = _patch(monkeypatch, tmp_path)
    _make_plugin(plugins_dir, "demo-plugin")
    pkg = _make_plugin(plugins_dir, "demo-plugin-2")
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = "demo-plugin"
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    try:
        catalog.collect_entries()
        raised = False
    except ValueError as exc:
        raised = "必须等于包目录名" in str(exc)
    assert raised


def test_readme_table_rendered_between_anchors(monkeypatch, tmp_path: Path):
    _patch(monkeypatch, tmp_path)
    _make_plugin(tmp_path / "plugins", "demo-plugin")
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Title\n\n<!-- catalog:begin -->\nold\n<!-- catalog:end -->\n",
        encoding="utf-8",
    )

    entries = catalog.collect_entries()
    assert catalog.sync_readme(entries)
    text = readme.read_text(encoding="utf-8")
    assert "[demo-plugin](./plugins/demo-plugin)" in text
    assert "old" not in text.split("catalog:begin")[1].split("catalog:end")[0]


def test_real_repo_catalog_in_sync():
    """集成测试：真实仓库的 catalog/catalog.json 必须与 plugins/ 一致。"""
    entries = catalog.collect_entries()
    rendered = catalog.render_catalog(entries)
    assert catalog.CATALOG_PATH.is_file(), "catalog/catalog.json 缺失，先运行 scripts/catalog.py"
    assert catalog.CATALOG_PATH.read_text(encoding="utf-8") == rendered
