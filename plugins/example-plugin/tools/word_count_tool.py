# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""示例工具：文本字数统计。

继承 ``openjiuwen.core.foundation.tool.Tool``，通过 ``ToolCard`` 声明能力。
纯函数式实现：无文件写入、无外部依赖、无运行时对象注入。
"""

from __future__ import annotations

from typing import Any

from openjiuwen.core.foundation.tool import Tool, ToolCard


class WordCountTool(Tool):
    """统计给定文本的字符数、非空字符数、单词数与行数。"""

    def __init__(self) -> None:
        super().__init__(
            ToolCard(
                id="word_count",
                name="word_count",
                description=(
                    "文本字数统计工具：给定 text，返回 characters（字符数）、"
                    "characters_no_spaces（非空字符数）、words（单词数）、lines（行数）。"
                    "当需要精确统计文本篇幅时调用，需配合 usage-report skill 使用。"
                ),
                input_params={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "待统计的完整文本",
                        },
                    },
                    "required": ["text"],
                },
            )
        )

    async def invoke(self, inputs: Any, **kwargs: Any) -> dict[str, Any]:
        text = self._extract_text(inputs)
        if text is None:
            return {
                "success": False,
                "error": "缺少必填参数 text：请以 {'text': '<待统计文本>'} 形式传入",
            }
        lines = text.splitlines()
        return {
            "success": True,
            "characters": len(text),
            "characters_no_spaces": len("".join(text.split())),
            "words": len(text.split()),
            "lines": len(lines),
        }

    async def stream(self, inputs: Any, **kwargs: Any):
        yield await self.invoke(inputs, **kwargs)

    @staticmethod
    def _extract_text(inputs: Any) -> str | None:
        if isinstance(inputs, dict):
            raw = inputs.get("text")
        else:
            raw = getattr(inputs, "text", None)
        if not isinstance(raw, str) or not raw:
            return None
        return raw
