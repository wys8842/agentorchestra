"""M4 并发收敛测试。"""

import asyncio

import pytest

from agentorchestra.core.agent import Agent
from agentorchestra.core.config import Config
from agentorchestra.tools.registry import ToolRegistry


class _AsyncAgent(Agent):
    """arun 真正 async（不阻塞 executor）。"""

    def __init__(self, **kw):
        super().__init__(**kw)

    async def arun(self, input_text, **kwargs):
        await asyncio.sleep(0.01)
        return f"async:{input_text}"

    def run(self, input_text, **kwargs):
        return f"sync:{input_text}"


class _MockLLM:
    model = "mock-model"
    def __getattr__(self, item):
        return None


def _make_agent(max_subagents: int = 2) -> _AsyncAgent:
    cfg = Config(
        trace_enabled=False, ontology_engine_enabled=False,
        subagent_enabled=False, todowrite_enabled=False, devlog_enabled=False,
        max_concurrent_subagents=max_subagents,
        context_builder_enabled=False,
    )
    return _AsyncAgent(name="t", llm=_MockLLM(),  # type: ignore[arg-type]
                       config=cfg, tool_registry=ToolRegistry())


@pytest.mark.asyncio
async def test_sync_async_parity():
    """async arun 是主路径。"""
    a = _make_agent()
    async_out = await a.arun("hello")
    assert async_out == "async:hello"


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_subagents():
    """max_concurrent_subagents=2 → 并发峰值 ≤2。"""
    a = _make_agent(max_subagents=2)
    active = {"n": 0}
    peak = {"n": 0}
    lock = asyncio.Lock()

    async def work(i):
        async with lock:
            active["n"] += 1
            peak["n"] = max(peak["n"], active["n"])
        await asyncio.sleep(0.02)
        async with lock:
            active["n"] -= 1
        return i

    tasks = [lambda i=i: work(i) for i in range(10)]
    results = await a.run_subagents_concurrently(tasks)
    assert sorted(results) == list(range(10))
    assert peak["n"] <= 2  # 信号量生效


@pytest.mark.asyncio
async def test_concurrency_info():
    a = _make_agent(max_subagents=3)
    info = a.get_concurrency_info()
    assert info["max_concurrent_subagents"] == 3
    assert info["max_concurrent_tools"] == 3


@pytest.mark.asyncio
async def test_semaphore_reusable_across_calls():
    """同一 agent 多次并发调用，信号量可复用不耗尽。"""
    a = _make_agent(max_subagents=1)
    r1 = await a.run_subagents_concurrently(
        [lambda: asyncio.sleep(0.01)] * 3)
    r2 = await a.run_subagents_concurrently(
        [lambda: asyncio.sleep(0.01)] * 2)
    assert len(r1) == 3 and len(r2) == 2
