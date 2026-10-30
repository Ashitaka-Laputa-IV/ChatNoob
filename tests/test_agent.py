"""agent.py：MCP 工具加载与 agent 组装。"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from chatnoob import agent


class FakeModel(BaseChatModel):
    responses: list = []
    index: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.responses[self.index]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


@tool
def echo(text: str) -> str:
    """Echo text."""
    return text


class FakeAdapter:
    def __init__(self, tools=None, error=None):
        self.tools = tools or []
        self.error = error
        self.config = None

    async def __aenter__(self):
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_tools(self):
        return self.tools


async def test_mcp_tools_loads_both_servers(monkeypatch) -> None:
    adapter = FakeAdapter(tools=[echo])
    seen = {}

    def factory(config):
        seen.update(config)
        return adapter

    monkeypatch.setattr(agent, "MCPAdapter", factory)

    tools = await agent._mcp_tools()

    assert tools == [echo]
    assert seen == {"mcpServers": agent.MCP_SERVERS}
    assert agent.MCP_SERVERS["docs"]["url"] == "https://docs.langchain.com/mcp"


async def test_mcp_tools_degrades_on_error(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        agent, "MCPAdapter", lambda config: FakeAdapter(error=OSError("offline"))
    )

    with caplog.at_level(logging.WARNING):
        tools = await agent._mcp_tools()

    assert tools == []
    assert "MCP 工具加载失败" in caplog.text


async def test_build_agent_wires_model_tools_and_middleware(monkeypatch) -> None:
    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return FakeModel()

    async def fake_tools():
        return [echo]

    monkeypatch.setattr(agent, "init_chat_model", fake_init)
    monkeypatch.setattr(agent, "_mcp_tools", fake_tools)
    monkeypatch.setattr(agent, "load_dotenv", lambda: None)

    built = await agent.build_agent(InMemorySaver())

    assert captured["model"] == agent.MODEL
    assert captured["kwargs"] == {"extra_body": {"thinking": {"type": "disabled"}}}
    assert "tools" in built.get_graph().nodes
    assert logging.getLogger("fastmcp").level == logging.WARNING


async def test_build_agent_without_tools(monkeypatch) -> None:
    async def fake_tools():
        return []

    monkeypatch.setattr(agent, "init_chat_model", lambda model, **kwargs: FakeModel())
    monkeypatch.setattr(agent, "_mcp_tools", fake_tools)
    monkeypatch.setattr(agent, "load_dotenv", lambda: None)

    built = await agent.build_agent(InMemorySaver())

    assert type(built).__name__ == "CompiledStateGraph"


def test_system_prompt_mentions_mcp() -> None:
    assert "MCP" in agent.SYSTEM_PROMPT
