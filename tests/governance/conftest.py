"""governance 测试公共 fixtures。"""

from __future__ import annotations

from typing import AsyncIterator

import pytest_asyncio

from agentorchestra.state.backends.memory_backend import InMemoryCheckpointStore
from agentorchestra.state.backends.sqlite_backend import SQLiteCheckpointStore


@pytest_asyncio.fixture
async def memory_store() -> AsyncIterator[InMemoryCheckpointStore]:
    store = InMemoryCheckpointStore()
    await store.init()
    yield store
    await store.close()


@pytest_asyncio.fixture
async def sqlite_store() -> AsyncIterator[SQLiteCheckpointStore]:
    import os
    import tempfile

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


def make_order_store():
    """构造带 Order 类型与系统字段的对象存储。"""
    from agentorchestra.ontology.semantic.object_type import ObjectType
    from agentorchestra.ontology.storage.object_store import ObjectStore
    from agentorchestra.tools.base import ToolParameter

    ot = ObjectType(
        api_name="Order",
        primary_key="id",
        properties=[
            ToolParameter(name="id", type="string", description=""),
            ToolParameter(name="amount", type="number", description=""),
            ToolParameter(name="customer", type="string", description=""),
        ],
    )
    store = ObjectStore()
    store.register_type(ot)
    return store
