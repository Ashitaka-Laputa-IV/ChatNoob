"""ChatNoob：用 Rich 渲染、带本地持久记忆的最简聊天机器人。"""

from __future__ import annotations

import warnings
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

MODEL = "deepseek:deepseek-chat"
SYSTEM_PROMPT = "你是一个简洁友好的中文助手，回答尽量短小精悍。"

# 记忆（checkpoint）落盘位置，与启动目录无关
DB_PATH = Path.home() / ".chatnoob" / "checkpoints.db"
THREAD_ID = "default"

warnings.filterwarnings("ignore", message="The v3 streaming protocol")

REPLY_LABEL = Text("ChatNoob › ", style="bold magenta")


def main() -> None:
    load_dotenv()

    console = Console()
    model = init_chat_model(MODEL)
    config = {"configurable": {"thread_id": THREAD_ID}}
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        agent = create_agent(
            model,
            system_prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,  # 本地 SQLite 记忆，重启后仍在
            middleware=[
                # 历史超过 20 条消息时把更早的对话压成摘要, 保留最近两条.
                SummarizationMiddleware(
                    model=model,
                    trigger=("messages", 20),
                    keep=("messages", 2),
                ),
            ],
        )

        console.print(Panel.fit(
            "[bold cyan]ChatNoob[/] [dim]· /clear 清空记忆 · /exit 退出[/]",
            border_style="cyan", padding=(0, 1),
        ))
        console.print(f"[dim]记忆保存在 {DB_PATH}[/dim]")

        while True:
            try:
                message = console.input("[bold cyan]你 › [/]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not message:
                continue
            if message == "/exit":
                break
            if message == "/clear":
                checkpointer.delete_thread(THREAD_ID)
                console.print("[dim]记忆已清空[/]")
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
