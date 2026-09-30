# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""validate.py 的 L0/L1 检查单测：以 example-plugin 为正确基线，
在 tmp_path 上制造各类破损，断言对应的错误信息出现。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PLUGIN_DIR = REPO_ROOT / "plugins" / "example-plugin"


@pytest.fixture()
def good_pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / "example-plugin"
    shutil.copytree(EXAMPLE_PLUGIN_DIR, pkg)
    return pkg


def _layers(pkg: Path):
    quality, static = validate.validate_static(pkg)
    return quality, static


def _messages(layer) -> list[str]:
    return [msg for msg, _ in layer.errors]


def test_good_package_passes(good_pkg: Path):
    quality, static = _layers(good_pkg)
    assert quality.errors == []
    assert static.errors == []


def test_todo_residue_blocked(good_pkg: Path):
    (good_pkg / "README.md").write_text(
        (good_pkg / "README.md").read_text(encoding="utf-8") + "\n[TODO: 待填]\n",
        encoding="utf-8",
    )
    quality, _ = _layers(good_pkg)
    assert any("TODO" in msg for msg in _messages(quality))


def test_missing_readme_blocked(good_pkg: Path):
    (good_pkg / "README.md").unlink()
    quality, _ = _layers(good_pkg)
    assert any("README.md 不存在" in msg for msg in _messages(quality))


def test_id_must_equal_dir_name(good_pkg: Path):
    manifest = json.loads((good_pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = "other-id"
    (good_pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    _, static = _layers(good_pkg)
    assert any("必须等于包目录名" in msg for msg in _messages(static))


def test_empty_capability_array_blocked(good_pkg: Path):
    manifest = json.loads((good_pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["rails"] = []
    (good_pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    _, static = _layers(good_pkg)
    assert any("rails 是空数组" in msg for msg in _messages(static))


def test_forbidden_root_keys_blocked(good_pkg: Path):
    manifest = json.loads((good_pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["persona"] = "someone"
    manifest["mcps"] = [{"name": "x"}]
    (good_pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    quality, static = _layers(good_pkg)
    quality_msgs = _messages(quality)
    static_msgs = _messages(static)
    assert any("禁止声明 'persona'" in msg for msg in quality_msgs + static_msgs)
    assert any("mcps" in msg for msg in static_msgs)


def test_default_init_input_must_match_first_quick_input(good_pkg: Path):
    manifest = json.loads((good_pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["default_init_input"]["zh"] = "不一致的引导语"
    (good_pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    quality, _ = _layers(good_pkg)
    assert any("quick_inputs[0]" in msg for msg in _messages(quality))


def test_declared_class_must_exist(good_pkg: Path):
    manifest = json.loads((good_pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["tools"][0]["class"] = "NoSuchTool"
    (good_pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    _, static = _layers(good_pkg)
    assert any("找不到 class 'NoSuchTool'" in msg for msg in _messages(static))


def test_tool_no_arg_init_required(good_pkg: Path):
    (good_pkg / "tools" / "word_count_tool.py").write_text(
        "from openjiuwen.core.foundation.tool import Tool, ToolCard\n\n\n"
        "class WordCountTool(Tool):\n"
        "    def __init__(self, dependency) -> None:\n"
        "        super().__init__(None)\n\n"
        "    async def invoke(self, inputs, **kwargs):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    _, static = _layers(good_pkg)
    assert any("必须能无参构造" in msg for msg in _messages(static))


def test_skill_frontmatter_name_must_equal_dir(good_pkg: Path):
    skill_md = good_pkg / "skills" / "usage-report" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace("name: usage-report", "name: other"),
        encoding="utf-8",
    )
    _, static = _layers(good_pkg)
    assert any("必须等于目录名" in msg for msg in _messages(static))


def test_at_least_one_capability(good_pkg: Path):
    manifest = json.loads((good_pkg / "manifest.json").read_text(encoding="utf-8"))
    for key in ("skills", "tools", "rails"):
        manifest.pop(key)
    (good_pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    _, static = _layers(good_pkg)
    assert any("至少声明一类能力组件" in msg for msg in _messages(static))


# ---------------------------------------------------------------------------
# 路径策略：open() 写入检测（内置 open 与 Path.open 都要拦）
# ---------------------------------------------------------------------------


def _write_tool(pkg: Path, body: str) -> None:
    (pkg / "tools" / "word_count_tool.py").write_text(
        "from pathlib import Path\n"
        "from openjiuwen.core.foundation.tool import Tool, ToolCard\n\n\n"
        "class WordCountTool(Tool):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(None)\n\n"
        "    async def invoke(self, inputs, **kwargs):\n"
        + body
        + "        return {}\n",
        encoding="utf-8",
    )


def test_builtin_open_write_blocked(good_pkg: Path):
    _write_tool(
        good_pkg,
        '        p = Path(__file__).parent / "state.json"\n'
        '        with open(p, "w") as f:\n'
        '            f.write("x")\n',
    )
    _, static = _layers(good_pkg)
    assert any("禁止用包内路径写运行时文件" in msg for msg in _messages(static))


def test_path_open_write_blocked(good_pkg: Path):
    _write_tool(
        good_pkg,
        '        p = Path(__file__).parent / "state.json"\n'
        '        p.open("w").write("x")\n',
    )
    _, static = _layers(good_pkg)
    assert any("禁止用包内路径写运行时文件" in msg for msg in _messages(static))


def test_open_read_allowed(good_pkg: Path):
    _write_tool(
        good_pkg,
        '        p = Path(__file__).parent / "data.json"\n'
        '        with open(p, "r") as f:\n'
        "            f.read()\n"
        "        p.open().close()\n",
    )
    _, static = _layers(good_pkg)
    assert not any("禁止用包内路径写运行时文件" in msg for msg in _messages(static))


# ---------------------------------------------------------------------------
# 目标解析：位置参数 + --only 汇总去重；无显式目标才扫全仓
# ---------------------------------------------------------------------------


def _args(targets=None, only=None):
    import argparse

    return argparse.Namespace(targets=targets or [], only=only)


def test_resolve_targets_only_does_not_widen(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(EXAMPLE_PLUGIN_DIR, plugins_dir / "example-plugin")
    (plugins_dir / "broken-plugin").mkdir()  # 无 manifest 的破损包
    monkeypatch.setattr(validate, "PLUGINS_DIR", plugins_dir)

    targets = validate.resolve_targets(_args(only=["example-plugin"]))
    assert [p.name for p in targets] == ["example-plugin"]


def test_resolve_targets_dedupes(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(EXAMPLE_PLUGIN_DIR, plugins_dir / "example-plugin")
    monkeypatch.setattr(validate, "PLUGINS_DIR", plugins_dir)

    targets = validate.resolve_targets(
        _args(targets=["example-plugin"], only=["example-plugin"])
    )
    assert [p.name for p in targets] == ["example-plugin"]


def test_resolve_targets_default_scans_all(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(EXAMPLE_PLUGIN_DIR, plugins_dir / "example-plugin")
    (plugins_dir / "broken-plugin").mkdir()
    monkeypatch.setattr(validate, "PLUGINS_DIR", plugins_dir)

    targets = validate.resolve_targets(_args())
    assert [p.name for p in targets] == ["broken-plugin", "example-plugin"]
