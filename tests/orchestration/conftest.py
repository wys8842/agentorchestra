"""orchestration 测试公共 fixtures + 假 Agent。"""

from __future__ import annotations

from typing import AsyncIterator, List

import pytest
import pytest_asyncio

from agentorchestra.state.backends.memory_backend import InMemoryCheckpointStore
from agentorchestra.state.backends.sqlite_backend import SQLiteCheckpointStore


class FakeAgent:
    """记录 arun 调用，返回固定输出。"""

    def __init__(self, name: str, output: str = "ok"):
        self.name = name
        self.output = output
        self.calls: List[str] = []

    async def arun(self, task: str) -> str:
        self.calls.append(str(task))
        return self.output


def _make_agent_factory(calls: list, node: str, output: str = "ok"):
    """返回无参 agent_factory，输出记录到 calls。"""
    def factory():
        agent = FakeAgent(node, output)

        async def arun(task: str) -> str:
            calls.append((node, str(task)))
            return output
        agent.arun = arun  # type: ignore[assignment]
        return agent
    return factory


@pytest.fixture
def make_agent_factory():
    """暴露工厂 helper（返回可带参数调用的函数）。"""
    return _make_agent_factory


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
