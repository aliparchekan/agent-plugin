# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""[TODO: Rail 一句话描述。]

继承 ``openjiuwen.harness.rails.base.DeepAgentRail``，通过生命周期钩子监听执行过程。
约束：Rail 由加载器无参构造；只实现需要的钩子；内部状态路径统一使用
``get_workspace()``，禁止写包内路径。
"""

from __future__ import annotations

from typing import Any

from openjiuwen.harness.rails.base import DeepAgentRail


class {{CLASS_NAME}}(DeepAgentRail):
    """[TODO: 描述 Rail 的触发时机和效果。]"""

    def __init__(self) -> None:
        super().__init__()
        self._agent: Any | None = None

    def init(self, agent: Any) -> None:
        self._agent = agent

    def uninit(self, agent: Any) -> None:
        self._agent = None

    # [TODO: 按需实现生命周期钩子，至少一个。可用钩子：
    #   before_invoke / after_invoke
    #   before_model_call / after_model_call
    #   before_tool_call / after_tool_call
    #   before_task_iteration / after_task_iteration
    # 事件数据从 ctx.inputs 读取。]
    def before_invoke(self, ctx: Any) -> None:
        return None
