"""store.py：thread id、用户校验、会话枚举与锁。"""

from __future__ import annotations

import contextlib
import sqlite3

import aiosqlite
import pytest

from chatnoob import store

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (thread_id TEXT, checkpoint_id TEXT);
CREATE TABLE IF NOT EXISTS writes (thread_id TEXT);
"""


@pytest.fixture
async def conn(tmp_path):
    async with aiosqlite.connect(tmp_path / "store.db") as connection:
        await connection.executescript(BASE_SCHEMA)
        await connection.executescript(store.SCHEMA_SQL)
        yield connection


def test_thread_id_round_trip() -> None:
    assert store.thread_id("alice", 3) == "alice:3"
    assert store.split_thread_id("alice:3") == ("alice", 3)
    assert store.split_thread_id("a:b:4") == ("a:b", 4)


@pytest.mark.parametrize("value", ["alice", ":1", "alice:x", "", "alice:"])
def test_split_thread_id_rejects_bad_values(value: str) -> None:
    assert store.split_thread_id(value) is None


def test_check_user_strips_and_rejects() -> None:
    assert store.check_user("  alice ") == "alice"
    with pytest.raises(ValueError):
        store.check_user("   ")
    with pytest.raises(ValueError):
        store.check_user("a:b")


def test_migrate_sync_adds_session_suffix(tmp_path) -> None:
    db = tmp_path / "sync.db"
    with contextlib.closing(sqlite3.connect(db)) as connection:
        connection.executescript(BASE_SCHEMA)
        connection.execute("INSERT INTO checkpoints VALUES ('alice', 'c1')")
        connection.execute("INSERT INTO checkpoints VALUES ('bob:2', 'c2')")
        connection.execute("INSERT INTO writes VALUES ('alice')")
        store.migrate_sync(connection)
        rows = connection.execute(
            "SELECT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()
        writes = connection.execute("SELECT thread_id FROM writes").fetchall()
    assert rows == [("alice:1",), ("bob:2",)]
    assert writes == [("alice:1",)]


async def test_migrate_async_adds_session_suffix(conn) -> None:
    await conn.execute("INSERT INTO checkpoints VALUES ('alice', 'c1')")
    await conn.execute("INSERT INTO writes VALUES ('alice')")
    await conn.commit()

    await store.migrate(conn)

    rows = await conn.execute_fetchall("SELECT thread_id FROM checkpoints")
    writes = await conn.execute_fetchall("SELECT thread_id FROM writes")
    assert rows == [("alice:1",)]
    assert writes == [("alice:1",)]


async def test_ensure_schema_creates_table(conn) -> None:
    await conn.execute("DROP TABLE chatnoob_sessions")
    await store.ensure_schema(conn)
    rows = await conn.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'chatnoob_sessions'"
    )
    assert rows == [("chatnoob_sessions",)]


async def test_sessions_merges_checkpoints_and_reservations(conn) -> None:
    await conn.executemany(
        "INSERT INTO checkpoints VALUES (?, ?)",
        [
            ("alice:1", "c1"),
            ("alice:1", "c2"),
            ("alice:2", "c3"),
            ("bob:1", "c4"),
            ("broken", "c5"),
            ("carol:x", "c6"),
        ],
    )
    await conn.execute(
        "INSERT INTO chatnoob_sessions (user, session) VALUES ('alice', 3)"
    )
    await conn.commit()

    found = await store.sessions(conn, "alice")

    # 保留记录里没有 checkpoint 的会话显示为空串
    assert found == [(1, "c2"), (2, "c3"), (3, "")]


async def test_latest_session(conn) -> None:
    assert await store.latest_session(conn, "alice") is None

    await conn.executemany(
        "INSERT INTO chatnoob_sessions (user, session) VALUES (?, ?)",
        [("alice", 1), ("alice", 4), ("bob", 9)],
    )
    await conn.commit()
    assert await store.latest_session(conn, "alice") == 4


async def test_next_session_increments_per_user(conn) -> None:
    assert await store.next_session(conn, "alice") == 1
    assert await store.next_session(conn, "alice") == 2
    assert await store.next_session(conn, "bob") == 1

    found = await store.sessions(conn, "alice")
    assert [number for number, _ in found] == [1, 2]


async def test_release_session_removes_reservation(conn) -> None:
    number = await store.next_session(conn, "alice")
    await store.release_session(conn, "alice", number)
    assert await store.sessions(conn, "alice") == []


async def test_lock_for_is_per_thread() -> None:
    first = await store.lock_for("alice:1")
    second = await store.lock_for("alice:1")
    other = await store.lock_for("bob:1")

    assert first is second
    assert first is not other
