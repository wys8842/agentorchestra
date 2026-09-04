"""nodes 测试：AgentNode（arun / fallback run）/ RouterNode / MergeNode。"""

import pytest

from agentorchestra.orchestration import AgentNode, FunctionalNode, RouterNode
from agentorchestra.orchestration.graph import NodeContext, NodeOutput


def _ctx(**kw):
    d = dict(graph_id="g", thread_id="t", message_id="m1", from_node=None,
             store=None, inbox=None)
    d.update(kw)
    return NodeContext(**d)


@pytest.mark.asyncio
async def test_agent_node_uses_arun(make_agent_factory):
    calls = []
    node = AgentNode(make_agent_factory(calls, "a", "out"))
    out = await node.run({"task": "hello"}, _ctx())
    assert calls == [("a", "hello")]
    assert out.result == "out"


@pytest.mark.asyncio
async def test_agent_node_fallback_sync_run():
    """无 arun 的 Agent → run_in_executor(run)。"""
    class SyncAgent:
        def run(self, task: str) -> str:
            return f"sync:{task}"

    node = AgentNode(lambda: SyncAgent())
    out = await node.run({"task": "x"}, _ctx())
    assert out.result == "sync:x"


@pytest.mark.asyncio
async def test_router_node_routes():
    node = RouterNode(lambda msg, ctx: "rejected" if msg.get("bad") else "approved")
    out = await node.run({"bad": True}, _ctx())
    assert out.route == "rejected"
    out2 = await node.run({"ok": 1}, _ctx())
    assert out2.route == "approved"


@pytest.mark.asyncio
async def test_functional_node():
    node = FunctionalNode(lambda m, c: NodeOutput.ok(result=m.get("v", 0) * 2))
    out = await node.run({"v": 21}, _ctx())
    assert out.result == 42
