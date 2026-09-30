# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""init.py 单测：脚手架生成与占位符替换。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import init as init_script

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_init(monkeypatch, plugins_dir: Path, argv: list[str]) -> None:
    monkeypatch.setattr(init_script, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(sys, "argv", ["init.py", *argv])
    assert init_script.main() == 0


def test_init_generates_skeleton(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _run_init(monkeypatch, plugins_dir, ["my-plugin"])

    pkg = plugins_dir / "my-plugin"
    assert (pkg / "manifest.json").is_file()
    assert (pkg / "README.md").is_file()
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "my-plugin"
    assert "{{" not in (pkg / "README.md").read_text(encoding="utf-8")


def test_init_with_components(monkeypatch, tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _run_init(
        monkeypatch,
        plugins_dir,
        ["my-plugin", "--skill", "usage-guide", "--tool", "word-count", "--rail", "auditor"],
    )

    pkg = plugins_dir / "my-plugin"
    skill = pkg / "skills" / "usage-guide" / "SKILL.md"
    assert skill.is_file()
    assert "name: usage-guide" in skill.read_text(encoding="utf-8")

    tool = pkg / "tools" / "word_count_tool.py"
    assert tool.is_file()
    tool_text = tool.read_text(encoding="utf-8")
    assert "class WordCountTool(Tool):" in tool_text
    assert 'id="word_count"' in tool_text

    rail = pkg / "rails" / "auditor_rail.py"
    assert rail.is_file()
    assert "class AuditorRail(DeepAgentRail):" in rail.read_text(encoding="utf-8")


def test_init_rejects_bad_name_and_duplicate(monkeypatch, tmp_path: Path, capsys):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    monkeypatch.setattr(init_script, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(sys, "argv", ["init.py", "Bad_Name"])
    assert init_script.main() == 1

    monkeypatch.setattr(sys, "argv", ["init.py", "my-plugin"])
    assert init_script.main() == 0
    monkeypatch.setattr(sys, "argv", ["init.py", "my-plugin"])
    assert init_script.main() == 1


def test_scaffold_fails_validation_until_filled(monkeypatch, tmp_path: Path):
    """脚手架带 [TODO] 占位，必须被 L0 拦截（设计如此，防半成品入库）。"""
    import validate

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _run_init(monkeypatch, plugins_dir, ["my-plugin"])

    quality, static = validate.validate_static(plugins_dir / "my-plugin")
    assert quality.errors, "脚手架的 [TODO] 占位应被 L0 拦截"
