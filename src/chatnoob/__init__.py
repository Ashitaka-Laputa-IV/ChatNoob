"""ChatNoob：用 Rich 渲染、带内存记忆的最简聊天机器人。"""

from __future__ import annotations

import warnings
from uuid import uuid4

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

MODEL = "deepseek:deepseek-chat"
SYSTEM_PROMPT = "你是一个简洁友好的中文助手，回答尽量短小精悍。"

warnings.filterwarnings("ignore", message="The v3 streaming protocol")

REPLY_LABEL = Text("ChatNoob › ", style="bold magenta")


def main() -> None:
    load_dotenv()

    console = Console()
    agent = create_agent(
        init_chat_model(MODEL),
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),  # 内存版记忆，进程退出即消失
    )
    config = {"configurable": {"thread_id": str(uuid4())}}

    console.print(Panel.fit(
        "[bold cyan]ChatNoob[/] [dim]· /clear 清空记忆 · /exit 退出[/]",
        border_style="cyan", padding=(0, 1),
    ))

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
            config = {"configurable": {"thread_id": str(uuid4())}}
            console.print("[dim]记忆已清空[/]")
            continue

        console.rule(style="dim")
        stream = agent.stream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            version="v3",
        )
        reply = ""
        with Live(
            Group(REPLY_LABEL, Text("思考中…", style="dim")),
            console=console,
            refresh_per_second=15,
            vertical_overflow="visible",
        ) as live:
            for ai_message in stream.messages:
                for delta in ai_message.text:
                    reply += delta
                    live.update(Group(REPLY_LABEL, Markdown(reply)))
        console.print()
