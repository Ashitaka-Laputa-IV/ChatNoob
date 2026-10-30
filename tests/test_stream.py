"""stream.py：v3 事件流的合并与异常处理。"""

from __future__ import annotations

import asyncio

import pytest

from chatnoob.stream import stream_agent


class FakeChunk:
    def __init__(self, node: str, pieces: list[str]) -> None:
        self.node = node
        self._pieces = pieces

    @property
    def text(self):
        async def gen():
            for piece in self._pieces:
                await asyncio.sleep(0)
                yield piece

        return gen()


class FakeCall:
    def __init__(
        self,
        call_id: str = "c1",
        name: str = "docs_search",
        error: str | None = None,
        delta_error: Exception | None = None,
    ) -> None:
        self.tool_call_id = call_id
        self.tool_name = name
        self.input = {"query": "memory"}
        self.output = "ok"
        self.error = error
        self._delta_error = delta_error

    @property
    def output_deltas(self):
        async def gen():
            await asyncio.sleep(0)
            if self._delta_error is not None:
                raise self._delta_error
            yield "partial"

        return gen()


class FakeRun:
    def __init__(
        self,
        messages=None,
        tool_calls=None,
        message_error: Exception | None = None,
        final=None,
        output_error: Exception | None = None,
    ) -> None:
        self._messages = messages or []
        self._tool_calls = tool_calls or []
        self._message_error = message_error
        self._final = final
        self._output_error = output_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def output(self):
        if self._output_error is not None:
            raise self._output_error
        return self._final if self._final is not None else {"messages": []}

    @property
    def messages(self):
        async def gen():
            for chunk in self._messages:
                yield chunk
            if self._message_error is not None:
                raise self._message_error

        return gen()

    @property
    def tool_calls(self):
        async def gen():
            for call in self._tool_calls:
                await asyncio.sleep(0)
                yield call

        return gen()


class FakeAgent:
    def __init__(self, run=None, error: Exception | None = None) -> None:
        self._run = run
        self._error = error

    async def astream_events(self, input, config=None, version="v3"):
        if self._error is not None:
            raise self._error
        return self._run


async def collect(agent) -> list[tuple[str, object]]:
    return [event async for event in stream_agent(agent, {}, {})]


async def test_stream_merges_tokens_summary_and_tools() -> None:
    call = FakeCall()
    run = FakeRun(
        messages=[
            FakeChunk("model", ["答案是 "]),
            FakeChunk("SummarizationMiddleware.before_model", ["SUM"]),
            FakeChunk("model", ["42"]),
        ],
        tool_calls=[call],
    )

    events = await collect(FakeAgent(run))

    kinds = [kind for kind, _ in events]
    assert kinds.count("token") == 2
    assert "summary" in kinds
    assert "tool_start" in kinds
    assert "tool_end" in kinds
    tool_end = next(payload for kind, payload in events if kind == "tool_end")
    assert tool_end.output == "ok"

    stats = next(payload for kind, payload in events if kind == "stats")
    assert stats["tool_calls"] == 1
    assert stats["duration_ms"] >= 0
    assert "tokens" not in stats


async def test_stream_reports_tool_error() -> None:
    call = FakeCall(error="boom")
    run = FakeRun(tool_calls=[call])

    events = await collect(FakeAgent(run))

    tool_end = next(payload for kind, payload in events if kind == "tool_end")
    assert tool_end.error == "boom"


async def test_stream_propagates_agent_error() -> None:
    with pytest.raises(RuntimeError, match="cannot connect"):
        await collect(FakeAgent(error=RuntimeError("cannot connect")))


async def test_stream_propagates_pump_error() -> None:
    run = FakeRun(messages=[FakeChunk("model", ["x"])], message_error=RuntimeError("boom"))

    generator = stream_agent(FakeAgent(run), {}, {})
    assert await anext(generator) == ("token", "x")
    with pytest.raises(RuntimeError, match="boom"):
        await anext(generator)


async def test_stream_propagates_tool_watcher_error() -> None:
    call = FakeCall(delta_error=RuntimeError("tool broke"))
    run = FakeRun(tool_calls=[call])

    with pytest.raises(RuntimeError, match="tool broke"):
        await collect(FakeAgent(run))


async def test_stream_can_close_early() -> None:
    run = FakeRun(messages=[FakeChunk("model", ["a", "b"])])

    generator = stream_agent(FakeAgent(run), {}, {})
    assert await anext(generator) == ("token", "a")
    await asyncio.wait_for(generator.aclose(), timeout=2)


class FakeMessage:
    def __init__(self, total_tokens: int) -> None:
        self.usage_metadata = {"total_tokens": total_tokens}


async def test_stream_stats_include_reported_tokens() -> None:
    run = FakeRun(final={"messages": [FakeMessage(123), FakeMessage(0)]})

    events = await collect(FakeAgent(run))

    stats = next(payload for kind, payload in events if kind == "stats")
    assert stats["tokens"] == 123


async def test_stream_stats_survive_missing_output() -> None:
    run = FakeRun(output_error=RuntimeError("no final state"))

    events = await collect(FakeAgent(run))

    stats = next(payload for kind, payload in events if kind == "stats")
    assert "tokens" not in stats
