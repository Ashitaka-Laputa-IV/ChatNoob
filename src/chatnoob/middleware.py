"""ChatNoob 专用中间件：只在新的用户轮次压缩历史。"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage


class TurnAwareSummarizationMiddleware(SummarizationMiddleware):
    """只在新用户轮次开始时压缩历史。

    工具循环的中间状态（最后一条是 ToolMessage）不压缩，否则当前问题会被
    摘要掉，模型就只能反问“你想问什么”。DeepSeek V4.1 Flash 有 1M 上下文，
    正常情况下几乎不会触发；这里只是长任务的安全阀。
    """

    def _should_summarize(self, messages: list[Any], total_tokens: int) -> bool:
        if not messages or not isinstance(messages[-1], HumanMessage):
            return False
        return super()._should_summarize(messages, total_tokens)

    @staticmethod
    def _build_new_messages(summary: str) -> list[HumanMessage]:
        return [
            HumanMessage(
                content=f"以下是此前对话的摘要：\n\n{summary}",
                additional_kwargs={"lc_source": "summarization"},
            )
        ]
