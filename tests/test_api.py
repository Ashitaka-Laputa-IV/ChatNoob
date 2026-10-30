"""api.py：SSE、会话接口与序列化。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from chatnoob import api


class FakeAgent:
    def __init__(self, messages=None) -> None:
        self.messages = messages or []

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": self.messages})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api.store, "DB_PATH", tmp_path / "checkpoints.db")
    agent = FakeAgent()

    async def fake_build(checkpointer):
        return agent

    monkeypatch.setattr(api, "build_agent", fake_build)
    with TestClient(api.app) as test_client:
        yield test_client


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        name = "message"
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if data is not None:
            events.append((name, data))
    return events


def test_health_index_and_static(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}

    index = client.get("/")
    assert index.status_code == 200
    assert "ChatNoob" in index.text

    assert client.get("/static/app.js").status_code == 200


def test_serialize_roles() -> None:
    assert api._serialize(AIMessage(content="a")) == {"role": "assistant", "text": "a"}
    assert api._serialize(HumanMessage(content="u")) == {"role": "user", "text": "u"}
    summary = HumanMessage(
        content="s", additional_kwargs={"lc_source": "summarization"}
    )
    assert api._serialize(summary) == {"role": "summary", "text": "s"}
    tool = ToolMessage(content="t" * 600, tool_call_id="1")
    serialized = api._serialize(tool)
    assert serialized["role"] == "tool"
    assert serialized["text"].endswith("…")
    assert len(serialized["text"]) == 501
    assert api._serialize(SystemMessage(content="sys")) == {
        "role": "system",
        "text": "sys",
    }


def test_truncate_and_sse() -> None:
    assert api._truncate("short") == "short"
    assert api._truncate("x" * 10, limit=3) == "xxx…"
    assert api._sse("ping", {"a": "中"}) == (
        'event: ping\ndata: {"a": "中"}\n\n'
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/sessions?user=", None),
        ("get", "/sessions?user=a%3Ab", None),
        ("post", "/sessions", {"user": "a:b"}),
        ("post", "/chat", {"user": "a:b", "message": "hi"}),
        ("get", "/sessions/1/history?user=a%3Ab", None),
        ("delete", "/sessions/1?user=a%3Ab", None),
    ],
)
def test_invalid_user_returns_422(client, method: str, path: str, body) -> None:
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code == 422


def test_sessions_crud(client) -> None:
    created = client.post("/sessions", json={"user": "alice"})
    assert created.json() == {"session": 1}

    listed = client.get("/sessions", params={"user": "alice"}).json()
    assert len(listed) == 1
    assert listed[0]["session"] == 1
    assert listed[0]["messages"] == 0

    deleted = client.delete("/sessions/1", params={"user": "alice"})
    assert deleted.json() == {"deleted": "alice:1"}
    assert client.get("/sessions", params={"user": "alice"}).json() == []


def test_history_filters_empty_ai_and_truncates_tools(client) -> None:
    agent = client.app.state.agent
    agent.messages = [
        HumanMessage(content="hi"),
        AIMessage(content=""),
        ToolMessage(content="t" * 600, tool_call_id="1"),
        AIMessage(content="answer"),
        HumanMessage(content="sum", additional_kwargs={"lc_source": "summarization"}),
        SystemMessage(content="sys"),
    ]

    response = client.get(
        "/sessions/1/history", params={"user": "alice", "limit": 100}
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [item["role"] for item in messages] == [
        "user",
        "tool",
        "assistant",
        "summary",
        "system",
    ]
    assert messages[1]["text"].endswith("…")
    assert messages[2]["text"] == "answer"


def test_history_rejects_bad_limit(client) -> None:
    response = client.get("/sessions/1/history", params={"user": "alice", "limit": 0})
    assert response.status_code == 422


def test_chat_streams_events_and_reuses_latest_session(client, monkeypatch) -> None:
    async def fake_stream(agent, input, config):
        call = SimpleNamespace(
            tool_call_id="c1",
            tool_name="docs_search",
            input={"query": "memory"},
            error=None,
        )
        yield ("token", "你")
        yield ("tool_start", call)
        yield ("tool_end", call)
        yield ("ignored", None)
        yield ("summary", "摘要")
        yield ("token", "好")
        yield ("stats", {"duration_ms": 5, "tool_calls": 1})

    monkeypatch.setattr(api, "stream_agent", fake_stream)

    first = client.post("/chat", json={"user": "alice", "message": "hi"})
    events = parse_sse(first.text)
    assert events[0] == ("start", {"session": 1})
    assert ("token", {"text": "你"}) in events
    assert (
        "tool",
        {
            "id": "c1",
            "name": "docs_search",
            "input": {"query": "memory"},
            "status": "start",
        },
    ) in events
    assert ("tool", {"id": "c1", "name": "docs_search", "status": "done"}) in events
    assert ("summary", {"text": "摘要"}) in events
    assert events[-1] == (
        "done",
        {
            "session": 1,
            "reply": "你好",
            "stats": {"duration_ms": 5, "tool_calls": 1},
        },
    )

    # 第二次不传 session 时会复用最近一个
    second = client.post("/chat", json={"user": "alice", "message": "again"})
    assert parse_sse(second.text)[0] == ("start", {"session": 1})


def test_chat_reports_tool_error(client, monkeypatch) -> None:
    async def fake_stream(agent, input, config):
        call = SimpleNamespace(
            tool_call_id="c2", tool_name="boom", input=None, error="bad"
        )
        yield ("tool_start", call)
        yield ("tool_end", call)

    monkeypatch.setattr(api, "stream_agent", fake_stream)

    response = client.post(
        "/chat", json={"user": "alice", "session": 7, "message": "hi"}
    )
    events = parse_sse(response.text)
    assert events[0] == ("start", {"session": 7})
    assert (
        "tool",
        {"id": "c2", "name": "boom", "status": "error", "error": "bad"},
    ) in events


def test_chat_reports_stream_error(client, monkeypatch) -> None:
    async def failing_stream(agent, input, config):
        if False:  # pragma: no cover - 让它成为异步生成器
            yield
        raise RuntimeError("model down")

    monkeypatch.setattr(api, "stream_agent", failing_stream)

    response = client.post("/chat", json={"user": "alice", "message": "hi"})
    events = parse_sse(response.text)
    assert ("error", {"detail": "model down"}) in events


def test_serve_reads_env(monkeypatch) -> None:
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(api.uvicorn, "run", fake_run)
    monkeypatch.setenv("CHATNOOB_HOST", "0.0.0.0")
    monkeypatch.setenv("CHATNOOB_PORT", "9999")

    api.serve()

    assert captured == {
        "app": "chatnoob.api:app",
        "host": "0.0.0.0",
        "port": 9999,
    }


def test_serve_defaults(monkeypatch) -> None:
    captured = {}
    monkeypatch.delenv("CHATNOOB_HOST", raising=False)
    monkeypatch.delenv("CHATNOOB_PORT", raising=False)
    monkeypatch.setattr(
        api.uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs)
    )

    api.serve()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
