"""ChatNoob：用 Rich 渲染、带本地持久记忆的最简聊天机器人。"""

from __future__ import annotations

import warnings

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from . import store
from .agent import build_agent

warnings.filterwarnings("ignore", message="The v3 streaming protocol")

REPLY_LABEL = Text("ChatNoob › ", style="bold magenta")


def main() -> None:
    load_dotenv()

    console = Console()
    # CLI 只用每个用户的第 1 个会话，多会话走 HTTP 服务
    user = store.DEFAULT_USER  # 每次启动都从 default 开始，不记住上次的用户
    config = {"configurable": {"thread_id": store.thread_id(user, 1)}}
    store.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(str(store.DB_PATH)) as checkpointer:
        store.migrate_sync(checkpointer.conn)
        agent = build_agent(checkpointer)  # 本地 SQLite 记忆，重启后仍在

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
                    checkpointer.delete_thread(store.thread_id(target, 1))
                    console.print(f"[dim]已清空 {target} 的记忆[/]")

                elif cmd == "/history":
                    count = store.HISTORY_LIMIT
                    if args:
                        if args[0].isdigit() and int(args[0]) > 0:
                            count = int(args[0])
                        else:
                            console.print("[dim]条数需要是正整数，按默认值处理[/]")
                    history = agent.get_state(config).values.get("messages", [])
                    if not history:
                        console.print("[dim]暂无历史消息[/]")
                    else:
                        console.print()
                        for past in history[-count:]:
                            if past.type == "ai":
                                label = REPLY_LABEL
                            elif past.type == "tool":
                                label = Text(f"工具 {past.name or '?'} › ", style="dim")
                            elif past.type == "human" and past.additional_kwargs.get(
                                "lc_source"
                            ) == "summarization":
                                # SummarizationMiddleware 生成的摘要也是 HumanMessage
                                label = Text("摘要 › ", style="dim")
                            elif past.type == "human":
                                label = Text(f"{user} › ", style="bold cyan")
                            else:
                                label = Text("系统 › ", style="dim")
                            console.print(Group(label, Markdown(past.text or "")))
                        console.print()

                else:
                    console.print(
                        f"[dim]未知命令 {cmd}，可用：/switch /clear /history /exit[/]"
                    )
                continue

            console.rule(style="dim")
            stream = agent.stream_events(
                {"messages": [{"role": "user", "content": message}]},
                config=config,
                version="v3",
            )
            reply = ""
            summary = ""
            with Live(
                Group(REPLY_LABEL, Text("思考中…", style="dim")),
                console=console,
                refresh_per_second=15,
                vertical_overflow="visible",
            ) as live:
                for ai_message in stream.messages:
                    if ai_message.node != "model":
                        # 摘要等中间件内部调用单独打印，不混进回答
                        summary += "".join(ai_message.text)
                        continue
                    for delta in ai_message.text:
                        reply += delta
                        live.update(Group(REPLY_LABEL, Markdown(reply)))
            console.print()
            if summary.strip():
                console.print(Panel(
                    Markdown(summary.strip()),
                    title="[dim]较早的对话已压缩为摘要[/]",
                    border_style="dim",
                    style="dim",
                    padding=(0, 1),
                ))
