"""FastAPI 服务：SSE 聊天与会话管理。"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from . import store
from .agent import build_agent
from .stream import stream_agent


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _truncate(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def _serialize(message: BaseMessage) -> dict[str, str]:
    if message.type == "ai":
        role = "assistant"
    elif message.type == "human":
        # SummarizationMiddleware 生成的摘要也是 HumanMessage
        role = (
            "summary"
            if message.additional_kwargs.get("lc_source") == "summarization"
            else "user"
        )
    elif message.type == "tool":
        role = "tool"
    else:
        role = "system"
    text = message.text or ""
    # 工具结果可能是整页文档，历史里只留可读的开头
    if role == "tool":
        text = _truncate(text)
    return {"role": role, "text": text}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(store.DB_PATH)) as saver:
        await saver.setup()
        # 写入排队 30 秒，避免多进程同时写时报 database is locked
        await saver.conn.execute("PRAGMA busy_timeout=30000")
        await store.migrate(saver.conn)
        await store.ensure_schema(saver.conn)
        app.state.saver = saver
        app.state.agent = await build_agent(saver)
        yield


app = FastAPI(title="ChatNoob", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    user: str = store.DEFAULT_USER
    session: int | None = None


class SessionIn(BaseModel):
    user: str = store.DEFAULT_USER


def _user(value: str) -> str:
    try:
        return store.check_user(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions")
async def create_session(body: SessionIn) -> dict[str, int]:
    user = _user(body.user)
    session = await store.next_session(app.state.saver.conn, user)
    return {"session": session}


@app.get("/sessions")
async def list_sessions(user: str = store.DEFAULT_USER) -> list[dict[str, Any]]:
    user = _user(user)
    saver = app.state.saver
    found = []
    for session, last_active in await store.sessions(saver.conn, user):
        tid = store.thread_id(user, session)
        state = await saver.aget_tuple({"configurable": {"thread_id": tid}})
        messages = (
            state.checkpoint.get("channel_values", {}).get("messages", [])
            if state is not None
            else []
        )
        found.append(
            {"session": session, "messages": len(messages), "last_active": last_active}
        )
    return found


@app.get("/sessions/{session}/history")
async def read_history(
    session: int,
    user: str = store.DEFAULT_USER,
    limit: int = Query(store.HISTORY_LIMIT, ge=1),
) -> dict[str, Any]:
    user = _user(user)
    tid = store.thread_id(user, session)
    state = await app.state.agent.aget_state({"configurable": {"thread_id": tid}})
    messages = state.values.get("messages", [])
    serialized = [_serialize(message) for message in messages]
    # 带工具调用的 AI 消息正文为空，历史里不显示空气泡
    serialized = [
        item
        for item in serialized
        if item["role"] != "assistant" or item["text"].strip()
    ]
    return {"session": session, "messages": serialized[-limit:]}


@app.delete("/sessions/{session}")
async def delete_session(
    session: int, user: str = store.DEFAULT_USER
) -> dict[str, str]:
    user = _user(user)
    tid = store.thread_id(user, session)
    await app.state.saver.adelete_thread(tid)
    await store.release_session(app.state.saver.conn, user, session)
    return {"deleted": tid}


async def _stream(
    agent: Any, lock: Any, tid: str, session: int, message: str
) -> AsyncIterator[str]:
    yield _sse("start", {"session": session})
    try:
        async with lock:
            reply = ""
            summary = ""
            stats: dict[str, Any] = {}
            async for kind, payload in stream_agent(
                agent,
                {"messages": [{"role": "user", "content": message}]},
                {"configurable": {"thread_id": tid}},
            ):
                if kind == "token":
                    reply += payload
                    yield _sse("token", {"text": payload})
                elif kind == "summary":
                    summary += payload
                elif kind == "tool_start":
                    yield _sse("tool", {
                        "id": payload.tool_call_id,
                        "name": payload.tool_name,
                        "input": payload.input,
                        "status": "start",
                    })
                elif kind == "tool_end":
                    data: dict[str, Any] = {
                        "id": payload.tool_call_id,
                        "name": payload.tool_name,
                        "status": "error" if payload.error else "done",
                    }
                    if payload.error:
                        data["error"] = str(payload.error)
                    yield _sse("tool", data)
                elif kind == "stats":
                    stats = payload
        if summary.strip():
            yield _sse("summary", {"text": summary.strip()})
        yield _sse("done", {"session": session, "reply": reply, "stats": stats})
    except Exception as exc:  # 流内异常只能作为事件返回
        yield _sse("error", {"detail": str(exc)})


@app.post("/chat")
async def chat(body: ChatIn) -> StreamingResponse:
    user = _user(body.user)
    saver, agent = app.state.saver, app.state.agent
    session = body.session
    if session is None:
        session = await store.latest_session(saver.conn, user)
    if session is None:
        session = await store.next_session(saver.conn, user)
    tid = store.thread_id(user, session)
    lock = await store.lock_for(tid)
    return StreamingResponse(
        _stream(agent, lock, tid, session, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def serve() -> None:
    uvicorn.run(
        "chatnoob.api:app",
        host=os.getenv("CHATNOOB_HOST", "127.0.0.1"),
        port=int(os.getenv("CHATNOOB_PORT", "8000")),
    )
