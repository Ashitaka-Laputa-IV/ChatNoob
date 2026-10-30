"""测试公共配置与小工具。"""

from __future__ import annotations

import asyncio
import io
import os

import pytest
from rich.console import Console

# 部分模块在构造模型时会读取 API Key；测试里不需要真实调用
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")


@pytest.fixture(autouse=True)
def reset_store_globals(monkeypatch):
    """每个测试用新的锁，避免 asyncio.Lock 绑定到上一个事件循环。"""
    from chatnoob import store

    monkeypatch.setattr(store, "_locks_guard", asyncio.Lock())
    monkeypatch.setattr(store, "_alloc_guard", asyncio.Lock())
    monkeypatch.setattr(store, "_locks", {})


@pytest.fixture
def console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=100)
