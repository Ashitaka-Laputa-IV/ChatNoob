"""FastAPI 服务：SSE 聊天与会话管理。"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from . import store
from .agent import build_agent


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
    return {"role": role, "text": message.text or ""}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(store.DB_PATH)) as saver:
        await saver.setup()
        # 写入排队 30 秒，避免多进程同时写时报 database is locked
        await saver.conn.execute("PRAGMA busy_timeout=30000")
        await store.migrate(saver.conn)
        app.state.saver = saver
        app.state.agent = build_agent(saver)
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
    return {
        "session": session,
        "messages": [_serialize(message) for message in messages[-limit:]],
    }


@app.delete("/sessions/{session}")
async def delete_session(
    session: int, user: str = store.DEFAULT_USER
) -> dict[str, str]:
    user = _user(user)
    tid = store.thread_id(user, session)
    await app.state.saver.adelete_thread(tid)
    return {"deleted": tid}


async def _stream(
    agent: Any, lock: Any, tid: str, session: int, message: str
) -> AsyncIterator[str]:
    yield _sse("start", {"session": session})
    try:
        async with lock:
            run = await agent.astream_events(
                {"messages": [{"role": "user", "content": message}]},
                config={"configurable": {"thread_id": tid}},
                version="v3",
            )
            reply = ""
            summary = ""
            async with run:
                async for chunk in run.messages:
                    if chunk.node != "model":
                        # 摘要等中间件内部调用单独走 summary 事件
                        async for delta in chunk.text:
                            summary += delta
                        continue
                    async for delta in chunk.text:
                        reply += delta
                        yield _sse("token", {"text": delta})
        if summary.strip():
            yield _sse("summary", {"text": summary.strip()})
        yield _sse("done", {"session": session, "reply": reply})
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


def serve() -> None:
    uvicorn.run(
        "chatnoob.api:app",
        host=os.getenv("CHATNOOB_HOST", "127.0.0.1"),
        port=int(os.getenv("CHATNOOB_PORT", "8000")),
    )
