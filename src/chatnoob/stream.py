"""统一消费 v3 事件流：回答 token、摘要、工具调用与运行统计。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


async def _collect_stats(
    run: Any, started: float, tool_calls: int
) -> dict[str, Any]:
    """汇总耗时、工具调用次数与 token 用量。"""
    stats: dict[str, Any] = {
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "tool_calls": tool_calls,
    }
    try:
        final = await run.output()
    except Exception:  # noqa: BLE001 - 统计失败不影响回答
        final = None

    messages = final.get("messages", []) if isinstance(final, dict) else []
    for message in reversed(messages):
        usage = getattr(message, "usage_metadata", None)
        if usage and usage.get("total_tokens"):
            stats["tokens"] = usage["total_tokens"]
            break

    logger.info("agent run: %s", stats)
    return stats


async def stream_agent(
    agent: Any,
    input: dict[str, Any],
    config: dict[str, Any],
) -> AsyncIterator[tuple[str, Any]]:
    """按到达顺序产出 `(kind, payload)`。

    kind 取值：`token`（回答增量）、`summary`（摘要增量）、
    `tool_start` / `tool_end`（值为 `ToolCallStream`）、`stats`（运行统计）。
    """
    started = time.perf_counter()
    tool_calls = 0
    run = await agent.astream_events(input, config=config, version="v3")
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    watchers: set[asyncio.Task[None]] = set()

    async def pump_messages() -> None:
        async for chunk in run.messages:
            # 摘要等中间件内部调用不算回答
            kind = "token" if chunk.node == "model" else "summary"
            async for delta in chunk.text:
                await queue.put((kind, delta))

    async def watch_tool(call: Any) -> None:
        # 工具开始后一直读到输出通道关闭，就能拿到最终 output / error
        async for _ in call.output_deltas:
            pass
        await queue.put(("tool_end", call))

    async def pump_tool_calls() -> None:
        nonlocal tool_calls
        async for call in run.tool_calls:
            tool_calls += 1
            await queue.put(("tool_start", call))
            task = asyncio.create_task(watch_tool(call))
            watchers.add(task)
            task.add_done_callback(watchers.discard)

    async def coordinate() -> None:
        try:
            await asyncio.gather(pump_messages(), pump_tool_calls())
            # 两个投影都结束后不会再有新工具调用，等仍在排空输出的工具收尾
            if watchers:
                await asyncio.gather(*list(watchers))
        except BaseException as exc:  # noqa: BLE001 - 交给调用方按 SSE 返回
            await queue.put(("error", exc))
        else:
            await queue.put(("end", None))

    async with run:
        coordinator = asyncio.create_task(coordinate())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "end":
                    break
                if kind == "error":
                    raise payload
                yield kind, payload
            yield ("stats", await _collect_stats(run, started, tool_calls))
        finally:
            coordinator.cancel()
            for task in list(watchers):
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await coordinator
