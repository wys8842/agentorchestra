"""state/ 测试公共 fixtures。"""

from __future__ import annotations

import os
import tempfile
from typing import AsyncIterator

import pytest_asyncio

from agentorchestra.state.backends.memory_backend import InMemoryCheckpointStore
from agentorchestra.state.backends.sqlite_backend import SQLiteCheckpointStore


@pytest_asyncio.fixture
async def sqlite_store() -> AsyncIterator[SQLiteCheckpointStore]:
    """每个测试用临时文件 SQLite，互不污染。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    store = SQLiteCheckpointStore(f"sqlite+aiosqlite:///{path}")
    await store.init()
    try:
        yield store
    finally:
        await store.close()
        if os.path.exists(path):
            os.unlink(path)


@pytest_asyncio.fixture
async def memory_store() -> AsyncIterator[InMemoryCheckpointStore]:
    store = InMemoryCheckpointStore()
    await store.init()
    yield store
    await store.close()
