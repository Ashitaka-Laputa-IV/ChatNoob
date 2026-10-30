"""middleware.py：只在新用户轮次压缩历史。"""

from __future__ import annotations

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chatnoob import middleware


class FakeModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="x"))])


def build_middleware() -> middleware.TurnAwareSummarizationMiddleware:
    return middleware.TurnAwareSummarizationMiddleware(
        model=FakeModel(),
        trigger=("messages", 3),
        keep=("messages", 1),
    )


def test_skips_summarization_in_the_middle_of_a_tool_loop() -> None:
    watcher = build_middleware()
    history = [
        HumanMessage(content="如何实现一个完备的 agent？"),
        AIMessage(
            content="",
            tool_calls=[{"name": "docs_search", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content="很长的文档结果", tool_call_id="c1"),
    ]

    # 普通 SummarizationMiddleware 在达到 3 条消息时会触发
    stock = SummarizationMiddleware(
        model=FakeModel(), trigger=("messages", 3), keep=("messages", 1)
    )
    assert stock._should_summarize(history, 10) is True
    assert watcher._should_summarize(history[:1], 10) is False
    assert watcher._should_summarize(history, 10) is False


def test_summarizes_at_the_start_of_a_new_turn() -> None:
    watcher = build_middleware()
    history = [
        HumanMessage(content="旧问题"),
        AIMessage(content="旧回答"),
        HumanMessage(content="新问题"),
    ]

    assert watcher._should_summarize(history, 10) is True


def test_no_summarization_below_threshold() -> None:
    watcher = build_middleware()

    assert watcher._should_summarize([HumanMessage(content="只有一个问题")], 10) is False
    assert watcher._should_summarize([], 10) is False


def test_summary_message_keeps_summarization_source() -> None:
    messages = middleware.TurnAwareSummarizationMiddleware._build_new_messages("SUM")

    assert len(messages) == 1
    assert messages[0].text == "以下是此前对话的摘要：\n\nSUM"
    assert messages[0].additional_kwargs["lc_source"] == "summarization"
