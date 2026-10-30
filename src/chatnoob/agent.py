"""Agent 装配：模型、MCP 工具、系统提示与中间件，CLI 和 HTTP 服务共用。"""

from __future__ import annotations

import logging
import warnings
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, ToolRetryMiddleware
from langchain.chat_models import init_chat_model
from langchain_core._api import LangChainBetaWarning

# langchain.mcp 仍是 beta：导入时只会提示一次，这里直接静音
warnings.filterwarnings("ignore", category=LangChainBetaWarning)
from langchain.mcp import MCPAdapter  # noqa: E402

from .middleware import TurnAwareSummarizationMiddleware

MODEL = "deepseek:deepseek-flash"
SYSTEM_PROMPT = (
    "你是一个简洁友好的中文助手，回答尽量短小精悍。"
    "遇到 LangChain、LangGraph、LangSmith 相关问题时，先用 MCP 工具查文档；"
    "复杂问题可以多次检索、交叉验证，再给出完整答案。"
    "不要只复述工具结果，回答时先给结论，需要时代码用完整可运行的示例。"
)

# 与 opencode.json 里的两个远程 MCP 服务保持一致；MCPConfig 会用服务名给工具加前缀
MCP_SERVERS = {
    "docs": {"url": "https://docs.langchain.com/mcp"},
    "reference": {"url": "https://reference.langchain.com/mcp"},
}

logger = logging.getLogger(__name__)


async def _mcp_tools() -> list[Any]:
    try:
        async with MCPAdapter({"mcpServers": MCP_SERVERS}) as adapter:
            tools = await adapter.list_tools()
        logger.info("已加载 %d 个 MCP 工具", len(tools))
        return tools
    except Exception as exc:  # 网络或服务不可用时退化成纯聊天
        logger.warning("MCP 工具加载失败，本次不启用工具: %s", exc)
        return []


async def build_agent(checkpointer: Any) -> Any:
    """组装 agent；MCP 工具是异步的，因此 checkpointer 需为异步 saver。"""
    load_dotenv()  # CLI 与 HTTP 服务都从这里拿到 DEEPSEEK_API_KEY
    # fastmcp 的代理日志会刷屏，只在真正出问题时再输出
    logging.getLogger("fastmcp").setLevel(logging.WARNING)
    # DeepSeek V4 默认开启思考模式；关掉后首字更快，闲聊场景也用不上推理。
    model = init_chat_model(MODEL, extra_body={"thinking": {"type": "disabled"}})
    return create_agent(
        model,
        tools=await _mcp_tools(),
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[
            # DeepSeek V4.1 Flash 有 1M 上下文；接近上限时才摘要，且
            # 只在新用户轮次触发，避免工具循环把当前问题压掉
            TurnAwareSummarizationMiddleware(
                model=model,
                trigger=("tokens", 600_000),
                keep=("tokens", 200_000),
            ),
            # 网络抖动 / 限流时自动重试，避免一次失败中断长任务
            ModelRetryMiddleware(max_retries=2, initial_delay=1.0, backoff_factor=2.0),
            ToolRetryMiddleware(max_retries=1, initial_delay=1.0, backoff_factor=2.0),
        ],
    )
