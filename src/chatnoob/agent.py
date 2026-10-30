"""Agent 装配：模型、系统提示与中间件，CLI 和 HTTP 服务共用。"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.chat_models import init_chat_model

MODEL = "deepseek:deepseek-chat"
SYSTEM_PROMPT = "你是一个简洁友好的中文助手，回答尽量短小精悍。"


def build_agent(checkpointer: Any) -> Any:
    """按给定 checkpointer 组装 agent，同步与异步 saver 都适用。"""
    load_dotenv()  # CLI 与 HTTP 服务都从这里拿到 DEEPSEEK_API_KEY
    model = init_chat_model(MODEL)
    return create_agent(
        model,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[
            # 历史超过 20 条消息时把更早的对话压成摘要, 保留最近两条.
            SummarizationMiddleware(
                model=model,
                trigger=("messages", 20),
                keep=("messages", 2),
            ),
        ],
    )
