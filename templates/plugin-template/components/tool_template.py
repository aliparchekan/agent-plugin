# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""[TODO: 工具一句话描述。]

继承 ``openjiuwen.core.foundation.tool.Tool``，通过 ``ToolCard`` 描述能力。
约束：无参构造；ToolCard.id / name 必须显式设置；input_params 必须是
合法 JSON Schema（type: object）；禁止通过构造函数注入运行时对象。
"""

from __future__ import annotations

from typing import Any

from openjiuwen.core.foundation.tool import Tool, ToolCard


class {{CLASS_NAME}}(Tool):
    """[TODO: 描述工具的触发场景和效果。]"""

    def __init__(self) -> None:
        super().__init__(
            ToolCard(
                id="{{TOOL_ID}}",
                name="{{TOOL_ID}}",
                description="[TODO: 工具描述：何时用、做什么]",
                input_params={
                    "type": "object",
                    "properties": {
                        "[TODO: param1]": {
                            "type": "string",
                            "description": "[TODO: 参数1描述]",
                        },
                    },
                    "required": ["[TODO: param1]"],
                },
            )
        )

    async def invoke(self, inputs: Any, **kwargs: Any) -> dict[str, Any]:
        # [TODO: 实现工具逻辑；失败时返回 {"success": False, "error": "..."}]
        return {"success": True, "result": "[TODO]"}

    async def stream(self, inputs: Any, **kwargs: Any):
        yield await self.invoke(inputs, **kwargs)
