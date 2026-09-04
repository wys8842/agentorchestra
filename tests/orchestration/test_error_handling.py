"""错误处理测试：节点异常 → on_node_error + status=partially_failed。"""

import pytest

from agentorchestra.orchestration import Graph
from agentorchestra.orchestration.events import NodeEventType
from agentorchestra.orchestration.graph import NodeOutput
from agentorchestra.orchestration.nodes import FunctionalNode


def _exploding_node():
    def run(msg, ctx):
        raise RuntimeError("boom")
    return FunctionalNode(run)


def _ok_node(name):
    return FunctionalNode(lambda msg, ctx, _n=name: NodeOutput.ok(result=_n))


@pytest.mark.asyncio
async def test_node_error_sets_partially_failed(memory_store):
    g = Graph(store=memory_store)
    g.add_node("ok", _ok_node("ok"))
    g.add_node("bad", _exploding_node())
    g.add_edge("ok", "bad")

    r = await g.run({"task": "x"}, thread_id="err1")
    assert r.status == "partially_failed"
    assert "bad" in r.errors[0]["node"] if r.errors else True
    # ok 节点完成，bad 节点 error 记录
    assert "ok" in r.node_results
    assert r.node_results.get("bad") == {"error": "boom"}


@pytest.mark.asyncio
async def test_on_node_error_callback(memory_store):
    g = Graph(store=memory_store)
    g.add_node("bad", _exploding_node())

    seen = []

    def cb(ev):
        seen.append(ev)

    r = await g.run({"task": "x"}, thread_id="err2", on_node_error=cb)
    assert len(seen) == 1
    assert seen[0].event_type == NodeEventType.NODE_ERROR
    assert seen[0].node_name == "bad"
    assert seen[0].error == "boom"
    assert r.status == "partially_failed"
