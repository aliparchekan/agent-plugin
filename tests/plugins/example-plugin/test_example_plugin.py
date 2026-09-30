# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""example-plugin 行为测试：真实导入 openjiuwen 运行时并执行 tool / rail。

无 openjiuwen 环境时整体跳过（CI 的 hot-load 节点负责全量执行）。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("openjiuwen")

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = REPO_ROOT / "plugins" / "example-plugin" / "tools" / "word_count_tool.py"
RAIL_PATH = REPO_ROOT / "plugins" / "example-plugin" / "rails" / "turn_counter_rail.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool_module():
    return _load_module(TOOL_PATH, "word_count_tool_under_test")


@pytest.fixture(scope="module")
def rail_module():
    return _load_module(RAIL_PATH, "turn_counter_rail_under_test")


def test_word_count_counts(tool_module):
    tool = tool_module.WordCountTool()
    result = asyncio.run(tool.invoke({"text": "hello world"}))
    assert result == {
        "success": True,
        "characters": 11,
        "characters_no_spaces": 10,
        "words": 2,
        "lines": 1,
    }


def test_word_count_multiline(tool_module):
    tool = tool_module.WordCountTool()
    result = asyncio.run(tool.invoke({"text": "第一行\nsecond line"}))
    assert result["lines"] == 2
    assert result["words"] == 3


def test_word_count_missing_text_degrades(tool_module):
    tool = tool_module.WordCountTool()
    result = asyncio.run(tool.invoke({}))
    assert result["success"] is False
    assert "error" in result


def test_word_count_is_real_tool(tool_module):
    from openjiuwen.core.foundation.tool import Tool

    tool = tool_module.WordCountTool()
    assert isinstance(tool, Tool)


def test_rail_counts_turns(rail_module):
    from openjiuwen.harness.rails.base import DeepAgentRail

    rail = rail_module.TurnCounterRail()
    assert isinstance(rail, DeepAgentRail)

    ctx = SimpleNamespace(inputs=SimpleNamespace(query="hello"))
    rail.before_invoke(ctx)
    rail.before_invoke(ctx)
    rail.after_invoke(ctx)
    assert rail.invoke_count == 2


def test_rail_hooks_are_overridden(rail_module):
    """钩子必须是子类真正实现的（覆盖基类默认行为），否则热加载会拒绝。"""
    from openjiuwen.harness.rails.base import DeepAgentRail

    rail = rail_module.TurnCounterRail()
    for hook in ("before_invoke", "after_invoke"):
        base_impl = getattr(DeepAgentRail, hook, None)
        assert getattr(type(rail), hook, None) is not base_impl
