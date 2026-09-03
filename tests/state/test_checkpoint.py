"""Checkpoint 测试。"""

import pytest

from agentorchestra.state.checkpoint import Checkpoint


@pytest.mark.asyncio
async def test_save_load_checkpoint(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    cp = Checkpoint(
        thread_id="thr-1",
        checkpoint_id="cp-1",
        state={"history": ["a", "b"], "step": 1},
    )
    await sqlite_store.save_checkpoint(cp)

    loaded = await sqlite_store.load_checkpoint("thr-1", "cp-1")
    assert loaded is not None
    assert loaded.state == {"history": ["a", "b"], "step": 1}
    assert loaded.checkpoint_id == "cp-1"


@pytest.mark.asyncio
async def test_checkpoint_parent_chain(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    cp1 = Checkpoint(thread_id="thr-1", checkpoint_id="cp-1", state={"s": 1})
    cp2 = Checkpoint(thread_id="thr-1", checkpoint_id="cp-2", state={"s": 2},
                     parent_id="cp-1")
    cp3 = Checkpoint(thread_id="thr-1", checkpoint_id="cp-3", state={"s": 3},
                     parent_id="cp-2")
    await sqlite_store.save_checkpoint(cp1)
    await sqlite_store.save_checkpoint(cp2)
    await sqlite_store.save_checkpoint(cp3)

    cps = await sqlite_store.list_checkpoints("thr-1")
    assert len(cps) == 3
    assert cps[0].checkpoint_id == "cp-3"  # 最新在前


@pytest.mark.asyncio
async def test_latest_checkpoint(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    await sqlite_store.save_checkpoint(Checkpoint(thread_id="thr-1", checkpoint_id="cp-1", state={}))
    await sqlite_store.save_checkpoint(Checkpoint(thread_id="thr-1", checkpoint_id="cp-2", state={}))
    cp = await sqlite_store.latest_checkpoint("thr-1")
    assert cp is not None
    assert cp.checkpoint_id == "cp-2"


@pytest.mark.asyncio
async def test_save_checkpoint_overwrite(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    cp1 = Checkpoint(thread_id="thr-1", checkpoint_id="cp-1", state={"v": 1})
    cp2 = Checkpoint(thread_id="thr-1", checkpoint_id="cp-1", state={"v": 2})
    await sqlite_store.save_checkpoint(cp1)
    await sqlite_store.save_checkpoint(cp2)
    loaded = await sqlite_store.load_checkpoint("thr-1", "cp-1")
    assert loaded.state == {"v": 2}


@pytest.mark.asyncio
async def test_checkpoint_metadata(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    cp = Checkpoint(
        thread_id="thr-1", checkpoint_id="cp-1",
        state={"h": 1},
        metadata={"tokens": 100, "tools": ["calc"]},
    )
    await sqlite_store.save_checkpoint(cp)
    loaded = await sqlite_store.load_checkpoint("thr-1", "cp-1")
    assert loaded.metadata == {"tokens": 100, "tools": ["calc"]}
