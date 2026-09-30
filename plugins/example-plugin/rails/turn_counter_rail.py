# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""示例 Rail：会话轮次计数。

继承 ``openjiuwen.harness.rails.base.DeepAgentRail``，通过生命周期钩子监听执行过程。
最小实现：仅在内存中累计调用轮次，不做文件写入、不注入 prompt，
演示 Rail 的注册 / 钩子 / 清理三段式结构。
"""

from __future__ import annotations

from typing import Any

from openjiuwen.harness.rails.base import DeepAgentRail


class TurnCounterRail(DeepAgentRail):
    """每轮 invoke 前后各触发一次，累计当前实例上的调用轮次。"""

    def __init__(self) -> None:
        super().__init__()
        self._agent: Any | None = None
        self._invoke_count: int = 0

    def init(self, agent: Any) -> None:
        self._agent = agent

    def uninit(self, agent: Any) -> None:
        self._agent = None

    @property
    def invoke_count(self) -> int:
        return self._invoke_count

    def before_invoke(self, ctx: Any) -> None:
        self._invoke_count += 1

    def after_invoke(self, ctx: Any) -> None:
        # 本示例不读取结果；需要汇总/落盘的场景参见 docs/plugin-spec.md 的 Rail 规范。
        return None
