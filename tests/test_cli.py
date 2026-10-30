"""__init__.py：CLI 渲染与命令循环。"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import chatnoob


class FakeAgent:
    def __init__(self, messages=None) -> None:
        self.messages = messages or []

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": self.messages})


def test_tool_line_formats_args() -> None:
    call = SimpleNamespace(tool_name="docs_search", input={"query": "memory"})
    assert chatnoob._tool_line(call) == "⚙ docs_search(query='memory') 调用中…"

    bare = SimpleNamespace(tool_name="ping", input=None)
    assert chatnoob._tool_line(bare) == "⚙ ping 调用中…"

    empty = SimpleNamespace(tool_name="ping", input={})
    assert chatnoob._tool_line(empty) == "⚙ ping 调用中…"


async def test_chat_renders_reply_tools_and_summary(monkeypatch, console) -> None:
    ok = SimpleNamespace(
        tool_call_id="c1",
        tool_name="docs_search",
        input={"query": "x"},
        error=None,
    )
    bad = SimpleNamespace(tool_call_id="c2", tool_name="broken", input=None, error="boom")

    async def fake_stream(agent, input, config):
        yield ("token", "答案")
        yield ("tool_start", ok)
        yield ("tool_end", ok)
        yield ("tool_start", bad)
        yield ("tool_end", bad)
        # 没有对应 start 的 end：只更新状态，不应报错
        yield ("tool_end", SimpleNamespace(tool_call_id="missing", tool_name="x", error=None))
        yield ("ignored", None)
        yield ("summary", "摘要内容")

    monkeypatch.setattr(chatnoob, "stream_agent", fake_stream)

    await chatnoob._chat(object(), {}, "hi", console)

    text = console.file.getvalue()
    assert "答案" in text
    assert "docs_search" in text
    assert "✓ docs_search 完成" in text
    assert "✗ broken 失败: boom" in text
    assert "摘要内容" in text


async def test_run_handles_commands(monkeypatch, console, tmp_path) -> None:
    messages = [
        HumanMessage(content="你好"),
        AIMessage(content=""),  # 工具调用产生的空消息，历史里应跳过
        ToolMessage(content="t" * 600, tool_call_id="1"),
        ToolMessage(content="short", tool_call_id="2"),
        AIMessage(content="回答"),
        HumanMessage(content="摘要", additional_kwargs={"lc_source": "summarization"}),
        SystemMessage(content="系统"),
    ]
    agent = FakeAgent(messages)

    async def fake_build(checkpointer):
        return agent

    async def fake_stream(agent, input, config):
        yield ("token", "回答")

    monkeypatch.setattr(chatnoob, "build_agent", fake_build)
    monkeypatch.setattr(chatnoob, "stream_agent", fake_stream)
    monkeypatch.setattr(chatnoob.store, "DB_PATH", tmp_path / "checkpoints.db")

    inputs = iter(
        [
            "/switch bob",
            "/history 10",
            "/history abc",
            "/clear bob",
            "/nope",
            "hello",
            "/exit",
        ]
    )
    monkeypatch.setattr(console, "input", lambda prompt="": next(inputs))

    await chatnoob._run(console)

    text = console.file.getvalue()
    assert "已切换到 bob" in text
    assert "工具 ? ›" in text  # ToolMessage 没有 name
    assert "…" in text
    assert "条数需要是正整数" in text
    assert "已清空 bob" in text
    assert "未知命令 /nope" in text
    assert "回答" in text


async def test_run_without_history(monkeypatch, console, tmp_path) -> None:
    async def fake_build(checkpointer):
        return FakeAgent()

    monkeypatch.setattr(chatnoob, "build_agent", fake_build)
    monkeypatch.setattr(chatnoob.store, "DB_PATH", tmp_path / "checkpoints.db")

    values = iter(["/history", ""])

    def fake_input(prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(console, "input", fake_input)

    await chatnoob._run(console)

    assert "暂无历史消息" in console.file.getvalue()


def test_main_runs_async_entrypoint(monkeypatch) -> None:
    closed = {}

    def fake_run(coro):
        closed["closed"] = True
        coro.close()

    monkeypatch.setattr(chatnoob.asyncio, "run", fake_run)
    monkeypatch.setattr(chatnoob, "load_dotenv", lambda: None)

    chatnoob.main()

    assert closed["closed"] is True
