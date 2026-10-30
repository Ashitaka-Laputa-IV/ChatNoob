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

_LIST_SQL = "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"

_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


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


async def sessions(conn: Any, user: str) -> list[tuple[int, str]]:
    """返回该用户的 [(会话编号, 最新 checkpoint_id)]，按编号升序。"""
    rows = await conn.execute_fetchall(_LIST_SQL)
    found = []
    for tid, last in rows:
        parsed = split_thread_id(tid)
        if parsed is not None and parsed[0] == user:
            found.append((parsed[1], last or ""))
    found.sort()
    return found


async def latest_session(conn: Any, user: str) -> int | None:
    """最近活跃的会话编号；checkpoint_id 单调递增，取最大的即可。"""
    found = await sessions(conn, user)
    if not found:
        return None
    return max(found, key=lambda item: item[1])[0]


async def next_session(conn: Any, user: str) -> int:
    found = await sessions(conn, user)
    return max((number for number, _ in found), default=0) + 1


async def lock_for(tid: str) -> asyncio.Lock:
    """同一 thread 的请求串行化，避免并发写导致上下文互相覆盖。"""
    async with _locks_guard:
        lock = _locks.get(tid)
        if lock is None:
            lock = _locks[tid] = asyncio.Lock()
        return lock
