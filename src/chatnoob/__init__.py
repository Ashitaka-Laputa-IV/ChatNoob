"""ChatNoob：用 Rich 渲染、带本地持久记忆与 MCP 工具的最简聊天机器人。"""

from __future__ import annotations

import asyncio
import warnings

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from . import store
from .agent import build_agent
from .stream import stream_agent

warnings.filterwarnings("ignore", message="The v3 streaming protocol")

REPLY_LABEL = Text("ChatNoob › ", style="bold magenta")


def _tool_line(call: object) -> str:
    args = getattr(call, "input", None)
    if isinstance(args, dict) and args:
        detail = ", ".join(f"{key}={value!r}" for key, value in args.items())
        return f"⚙ {getattr(call, 'tool_name', '?')}({detail}) 调用中…"
    return f"⚙ {getattr(call, 'tool_name', '?')} 调用中…"


async def _chat(agent: object, config: dict, message: str, console: Console) -> None:
    reply = ""
    summary = ""
    tool_rows: dict[str, Text] = {}
    status: list[Text] = []

    def render() -> Group:
        body = Markdown(reply) if reply else Text("思考中…", style="dim")
        return Group(*status, REPLY_LABEL, body)

    with Live(
        render(),
        console=console,
        refresh_per_second=15,
        vertical_overflow="visible",
    ) as live:
        async for kind, payload in stream_agent(
            agent,
            {"messages": [{"role": "user", "content": message}]},
            config,
        ):
            if kind == "token":
                reply += payload
            elif kind == "summary":
                summary += payload
            elif kind == "tool_start":
                row = Text(_tool_line(payload), style="dim")
                tool_rows[payload.tool_call_id] = row
                status.append(row)
            elif kind == "tool_end":
                row = tool_rows.get(payload.tool_call_id)
                if row is not None:
                    name = getattr(payload, "tool_name", "?")
                    if payload.error:
                        row.plain = f"✗ {name} 失败: {payload.error}"
                    else:
                        row.plain = f"✓ {name} 完成"
            live.update(render())

    console.print()
    if summary.strip():
        console.print(Panel(
            Markdown(summary.strip()),
            title="[dim]较早的对话已压缩为摘要[/]",
            border_style="dim",
            style="dim",
            padding=(0, 1),
        ))


async def _run(console: Console) -> None:
    # CLI 只用每个用户的第 1 个会话，多会话走 HTTP 服务
    user = store.DEFAULT_USER  # 每次启动都从 default 开始，不记住上次的用户
    config = {"configurable": {"thread_id": store.thread_id(user, 1)}}
    store.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(store.DB_PATH)) as checkpointer:
        await checkpointer.setup()
        await store.migrate(checkpointer.conn)
        await store.ensure_schema(checkpointer.conn)
        agent = await build_agent(checkpointer)  # 本地 SQLite 记忆，重启后仍在

        console.print(Panel.fit(
            "[bold cyan]ChatNoob[/] [dim]· /switch 切换用户 · /history 历史"
            " · /clear 清空 · /exit 退出[/]",
            border_style="cyan", padding=(0, 1),
        ))
        console.print(f"[dim]记忆保存在 {store.DB_PATH}[/dim]")

        while True:
            try:
                message = console.input(f"[bold cyan]{user} › [/]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not message:
                continue

            if message.startswith("/"):
                cmd, *args = message.split()

                if cmd == "/exit":
                    break

                if cmd == "/switch":
                    user = args[0] if args else store.DEFAULT_USER
                    config = {"configurable": {"thread_id": store.thread_id(user, 1)}}
                    console.print(f"[dim]已切换到 {user}[/]")

                elif cmd == "/clear":
                    target = args[0] if args else user
                    await checkpointer.adelete_thread(store.thread_id(target, 1))
                    console.print(f"[dim]已清空 {target} 的记忆[/]")

                elif cmd == "/history":
                    count = store.HISTORY_LIMIT
                    if args:
                        if args[0].isdigit() and int(args[0]) > 0:
                            count = int(args[0])
                        else:
                            console.print("[dim]条数需要是正整数，按默认值处理[/]")
                    state = await agent.aget_state(config)
                    history = state.values.get("messages", [])
                    if not history:
                        console.print("[dim]暂无历史消息[/]")
                    else:
                        console.print()
                        for past in history[-count:]:
                            text = past.text or ""
                            if past.type == "ai" and not text.strip():
                                # 带工具调用的 AI 消息正文为空，历史里跳过
                                continue
                            if past.type == "ai":
                                label = REPLY_LABEL
                            elif past.type == "tool":
                                label = Text(f"工具 {past.name or '?'} › ", style="dim")
                                # 工具结果可能是整页文档，历史里只留开头
                                if len(text) > 500:
                                    text = f"{text[:500]}…"
                            elif past.type == "human" and past.additional_kwargs.get(
                                "lc_source"
                            ) == "summarization":
                                # SummarizationMiddleware 生成的摘要也是 HumanMessage
                                label = Text("摘要 › ", style="dim")
                            elif past.type == "human":
                                label = Text(f"{user} › ", style="bold cyan")
                            else:
                                label = Text("系统 › ", style="dim")
                            console.print(Group(label, Markdown(text)))
                        console.print()

                else:
                    console.print(
                        f"[dim]未知命令 {cmd}，可用：/switch /clear /history /exit[/]"
                    )
                continue

            console.rule(style="dim")
            await _chat(agent, config, message, console)


def main() -> None:
    load_dotenv()
    asyncio.run(_run(Console()))
