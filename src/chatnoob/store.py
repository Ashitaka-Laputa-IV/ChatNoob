"""会话标识与枚举：一个用户下可以有多条会话，thread_id 形如 `alice:1`。"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

# 记忆（checkpoint）落盘位置，与启动目录无关
DB_PATH = Path.home() / ".chatnoob" / "checkpoints.db"

DEFAULT_USER = "default"
HISTORY_LIMIT = 10  # /history 与 GET /sessions/{n}/history 的默认条数

# 旧版本把用户名直接当 thread_id，迁移成该用户的第 1 个会话
MIGRATION_SQL = """
UPDATE checkpoints SET thread_id = thread_id || ':1' WHERE instr(thread_id, ':') = 0;
UPDATE writes      SET thread_id = thread_id || ':1' WHERE instr(thread_id, ':') = 0;
"""

# 新建但还没说话的会话不会有 checkpoint，单独记一行，否则列表里看不到
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chatnoob_sessions (
    user    TEXT NOT NULL,
    session INTEGER NOT NULL,
    PRIMARY KEY (user, session)
);
"""

_LIST_SQL = "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"
_RESERVED_SQL = "SELECT session FROM chatnoob_sessions WHERE user = ?"

_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()
_alloc_guard = asyncio.Lock()


def thread_id(user: str, session: int) -> str:
    return f"{user}:{session}"


def split_thread_id(value: str) -> tuple[str, int] | None:
    user, _, raw = value.rpartition(":")
    if not user or not raw.isdigit():
        return None
    return user, int(raw)


def check_user(user: str) -> str:
    """用户名校验：不能为空，也不能含 ':'（会和 user:session 结构冲突）。"""
    name = user.strip()
    if not name or ":" in name:
        raise ValueError("用户名不能为空或包含 ':'")
    return name


def migrate_sync(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_SQL)
    conn.commit()


async def migrate(conn: Any) -> None:
    await conn.executescript(MIGRATION_SQL)
    await conn.commit()


async def ensure_schema(conn: Any) -> None:
    await conn.executescript(SCHEMA_SQL)
    await conn.commit()


async def sessions(conn: Any, user: str) -> list[tuple[int, str]]:
    """返回该用户的 [(会话编号, 最新 checkpoint_id)]，按编号升序。

    新建但还没发过消息的会话只有预留记录，checkpoint_id 为空字符串。
    """
    rows = await conn.execute_fetchall(_LIST_SQL)
    reserved = await conn.execute_fetchall(_RESERVED_SQL, (user,))
    found: dict[int, str] = {int(number): "" for (number,) in reserved}
    for tid, last in rows:
        parsed = split_thread_id(tid)
        if parsed is not None and parsed[0] == user:
            found[parsed[1]] = last or ""
    return sorted(found.items())


async def latest_session(conn: Any, user: str) -> int | None:
    """最新创建的会话编号（编号在用户内自增，最大的就是最新的）。"""
    found = await sessions(conn, user)
    return found[-1][0] if found else None


async def next_session(conn: Any, user: str) -> int:
    """分配并预留一个新会话编号。"""
    async with _alloc_guard:
        found = await sessions(conn, user)
        number = max((item[0] for item in found), default=0) + 1
        await conn.execute(
            "INSERT INTO chatnoob_sessions (user, session) VALUES (?, ?)",
            (user, number),
        )
        await conn.commit()
        return number


async def release_session(conn: Any, user: str, session: int) -> None:
    await conn.execute(
        "DELETE FROM chatnoob_sessions WHERE user = ? AND session = ?",
        (user, session),
    )
    await conn.commit()


async def lock_for(tid: str) -> asyncio.Lock:
    """同一 thread 的请求串行化，避免并发写导致上下文互相覆盖。"""
    async with _locks_guard:
        lock = _locks.get(tid)
        if lock is None:
            lock = _locks[tid] = asyncio.Lock()
        return lock
