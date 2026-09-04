"""图执行器测试：3 节点按依赖执行 + 条件边路由。"""

import pytest

from agentorchestra.orchestration import (
    AgentNode,
    FunctionalNode,
    Graph,
    RouterNode,
)
from agentorchestra.orchestration.graph import NodeOutput


@pytest.mark.asyncio
async def test_chain_executes_in_order(memory_store, make_agent_factory):
    """coder → reviewer → tester 链：按依赖顺序执行。"""
    calls = []
    g = Graph(store=memory_store)
    g.add_node("coder", AgentNode(make_agent_factory(calls, "coder", "coded")))
    g.add_node("reviewer", AgentNode(make_agent_factory(calls, "reviewer", "reviewed")))
    g.add_node("tester", AgentNode(make_agent_factory(calls, "tester", "tested")))
    g.add_edge("coder", "reviewer")
    g.add_edge("reviewer", "tester")

    r = await g.run({"task": "hello"}, thread_id="t1")
    assert r.status == "completed"
    assert calls == [("coder", "hello"), ("reviewer", "coded"), ("tester", "reviewed")]
    assert set(r.node_results.keys()) == {"coder", "reviewer", "tester"}


@pytest.mark.asyncio
async def test_conditional_router(memory_store, make_agent_factory):
    """router 分流 approved → tester / rejected → rework。"""
    calls = []
    g = Graph(store=memory_store)
    g.add_node("gen", AgentNode(make_agent_factory(calls, "gen", "内容")))
    g.add_node("router", RouterNode(
        lambda msg, ctx: "approved" if "ok" in str(msg.get("task", "")) else "rejected"
    ))
    g.add_node("tester", AgentNode(make_agent_factory(calls, "tester", "tested")))
    g.add_node("rework", AgentNode(make_agent_factory(calls, "rework", "fixed")))
    g.add_edge("gen", "router")
    g.add_edge("router", "tester", when="approved")
    g.add_edge("router", "rework", when="rejected")

    # gen 输出 "内容"（无 ok）→ router 判 rejected；rework 收到 router 的 result
    r = await g.run({"task": "needs review"}, thread_id="t2")
    assert ("rework", "rejected") in calls
    assert ("tester", "approved") not in calls
    assert r.node_results["router"] == "rejected"


@pytest.mark.asyncio
async def test_conditional_approved_branch(memory_store, make_agent_factory):
    """ok 关键词 → approved 分支。"""
    calls = []
    g = Graph(store=memory_store)
    g.add_node("gen", AgentNode(make_agent_factory(calls, "gen", "ok content")))
    g.add_node("router", RouterNode(
        lambda msg, ctx: "approved" if "ok" in str(msg.get("task", "")) else "rejected"
    ))
    g.add_node("tester", AgentNode(make_agent_factory(calls, "tester", "tested")))
    g.add_edge("gen", "router")
    g.add_edge("router", "tester", when="approved")

    r = await g.run({"task": "x"}, thread_id="t3")
    assert ("tester", "approved") in calls
    assert r.status == "completed"


@pytest.mark.asyncio
async def test_merge_node_combines(memory_store):
    """多上游可发往汇聚节点；上游节点均执行。"""
    g = Graph(store=memory_store)

    g.add_node("a", FunctionalNode(lambda m, c: NodeOutput.ok(result={"a": 1})))
    g.add_node("b", FunctionalNode(lambda m, c: NodeOutput.ok(result={"b": 2})))
    g.add_node("merge", FunctionalNode(lambda m, c: NodeOutput.ok(result={"combined": True})))
    g.add_edge("a", "merge")
    g.add_edge("b", "merge")

    # a、b 都执行（真实 fan-in 汇聚由专用 MergeNode 逻辑负责，此处只验执行链）
    r = await g.run({"task": "m"}, thread_id="t4")
    assert "a" in r.node_results and "b" in r.node_results
    assert "merge" in r.node_results
    assert r.status == "completed"


@pytest.mark.asyncio
async def test_run_requires_no_store(make_agent_factory):
    """不传 store（in-memory 兜底）也可执行。"""
    calls = []
    g = Graph()
    g.add_node("n", AgentNode(make_agent_factory(calls, "n", "x")))
    r = await g.run({"task": "t"}, thread_id="no-store")
    assert r.status == "completed"
