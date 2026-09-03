"""Agent 接入 CheckpointStore 测试。

验证 Agent 基类的 _save_checkpoint / resume / interrupt / resume_with 接口。
不要求 SimpleAgent/ReActAgent 等已实现 run() 内调用；本测试直接调基类 API。
"""

import pytest

from agentorchestra.core.agent import Agent
from agentorchestra.core.config import Config
from agentorchestra.tools.registry import ToolRegistry


class _MockLLM:
    """不发起真实调用的 LLM mock。"""
    model = "mock-model"

    async def ainvoke(self, *args, **kwargs):
        return {"content": "mock response"}


class _StubAgent(Agent):
    """测试用 Agent 子类：只实现必要抽象方法。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def run(self, input_text, **kwargs):
        return "stub-result"


def _make_agent(persistence_mode="sqlite"):
    cfg = Config(
        trace_enabled=False,  # 关闭 trace，避免生成 HTML 文件
        ontology_engine_enabled=False,  # 关闭 ontology 简化测试
        subagent_enabled=False,
        todowrite_enabled=False,
        devlog_enabled=False,
        persistence_mode=persistence_mode,
    )
    return _StubAgent(
        name="stub",
        llm=_MockLLM(),  # type: ignore[arg-type]
        config=cfg,
        tool_registry=ToolRegistry(),
    )


@pytest.mark.asyncio
async def test_agent_save_checkpoint(tmp_path, monkeypatch):
    """Agent 基类 _save_checkpoint 能把 state 写入 CheckpointStore。"""
    db_path = tmp_path / "agent.db"
    agent = _make_agent()
    # 强制用临时路径
    monkeypatch.setattr(agent, "_init_checkpoint_store",
                        lambda: _patched_init(agent, str(db_path)))

    await _patched_init(agent, str(db_path))
    assert agent.checkpoint_store is not None
    assert agent._active_thread_id is None

    tid = "test-thread-1"
    cp_id = await agent._save_checkpoint(
        thread_id=tid,
        state={"history": ["a"], "step": 1},
        step=1,
    )
    assert cp_id.startswith("cp-")

    # 验证 checkpoint 已写入
    cp = await agent.checkpoint_store.load_checkpoint(tid, cp_id)
    assert cp.state["step"] == 1


@pytest.mark.asyncio
async def test_agent_resume_returns_state(tmp_path):
    """resume 返回最近 checkpoint 的 state。"""
    agent = _make_agent()
    await _patched_init(agent, str(tmp_path / "agent.db"))

    tid = "t1"
    await agent._save_checkpoint(tid, {"step": 1}, step=1)
    await agent._save_checkpoint(tid, {"step": 2}, step=2)
    await agent._save_checkpoint(tid, {"step": 3}, step=3)

    state = await agent.resume(tid)
    assert state == {"step": 3}


@pytest.mark.asyncio
async def test_agent_resume_specific_checkpoint(tmp_path):
    agent = _make_agent()
    await _patched_init(agent, str(tmp_path / "agent.db"))

    tid = "t1"
    cp1_id = await agent._save_checkpoint(tid, {"step": 1}, step=1)
    await agent._save_checkpoint(tid, {"step": 2}, step=2)
    state = await agent.resume(tid, checkpoint_id=cp1_id)
    assert state == {"step": 1}


@pytest.mark.asyncio
async def test_agent_resume_nonexistent_raises(tmp_path):

    agent = _make_agent()
    await _patched_init(agent, str(tmp_path / "agent.db"))

    with pytest.raises(FileNotFoundError):
        await agent.resume("nonexistent")


@pytest.mark.asyncio
async def test_agent_in_memory_mode(tmp_path):
    """persistence_mode='in_memory' 不引入 DB。"""
    agent = _make_agent(persistence_mode="in_memory")
    agent._init_checkpoint_store()  # 同步模式（in_memory 不需 init）
    assert agent.checkpoint_store is not None
    from agentorchestra.state.backends.memory_backend import InMemoryCheckpointStore
    assert isinstance(agent.checkpoint_store, InMemoryCheckpointStore)

    tid = "mem-t1"
    await agent._save_checkpoint(tid, {"x": 1})
    state = await agent.resume(tid)
    assert state == {"x": 1}


@pytest.mark.asyncio
async def test_agent_resolve_interrupt(tmp_path):
    agent = _make_agent()
    await _patched_init(agent, str(tmp_path / "agent.db"))

    tid = "t-int"
    await agent.checkpoint_store.create_thread(tid)
    # 模拟 interrupt：直接调 store API（interrupt() 会抛异常）
    from agentorchestra.state.interrupt import Interrupt
    await agent.checkpoint_store.create_interrupt(Interrupt(
        token="int-test", thread_id=tid, checkpoint_id="cp-0", reason="r",
    ))
    await agent.resume_with("int-test", {"approved": True})
    intr = await agent.checkpoint_store.get_interrupt("int-test")
    assert intr.status.value == "resumed"
    assert intr.response == {"approved": True}


async def _patched_init(agent, db_path):
    """直接给 agent 装一个 SQLite store（绕过 config）。"""
    from agentorchestra.state.backends.sqlite_backend import SQLiteCheckpointStore
    from agentorchestra.state.thread import ThreadManager

    store = SQLiteCheckpointStore(f"sqlite+aiosqlite:///{db_path}")
    await store.init()
    agent.checkpoint_store = store
    agent._thread_manager = ThreadManager(agent.checkpoint_store)
    agent._wal_flush_target = None
