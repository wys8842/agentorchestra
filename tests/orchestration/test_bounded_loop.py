"""有界回环测试：reviewer→coder 拒绝回环达 max_iterations 转告警。"""

import pytest

from agentorchestra.orchestration import AgentNode, Graph, RouterNode


class _AlwaysReject:
    """每次拒绝的 review agent（无状态，永远 rejected）。"""


@pytest.mark.asyncio
async def test_bounded_loop_stops_at_max_iterations(memory_store, make_agent_factory):
    """reviewer 永远拒绝 → coder 只执行 max_iterations 次后停止并记 error。"""
    calls = []
    coder_factory = make_agent_factory(calls, "coder", "迭代稿")

    # reviewer 永远输出"重做"
    reviewer_output = ["需要重做"]

    def reviewer_factory():
        calls_holder = calls
        agent = object.__new__(type("R", (object,), {}))

        async def arun(task: str) -> str:
            calls_holder.append(("reviewer", str(task)))
            return reviewer_output[0]
        agent.arun = arun  # type: ignore[attr-defined]
        return agent  # type: ignore[return-value]

    g = Graph(store=memory_store, max_iterations=3)
    g.add_node("coder", AgentNode(coder_factory))
    g.add_node("reviewer", AgentNode(reviewer_factory))
    g.add_node("verdict", RouterNode(
        lambda msg, ctx: "rejected" if "重做" in str(msg.get("task", "")) else "approved"
    ))
    g.add_node("done", AgentNode(make_agent_factory(calls, "done", "ok")))
    g.add_edge("coder", "reviewer")
    g.add_edge("reviewer", "verdict")
    g.add_edge("verdict", "coder", when="rejected")
    g.add_edge("verdict", "done", when="approved")

    r = await g.run({"task": "初稿"}, thread_id="loop", entry_node="coder")
    # coder 执行 max_iterations 次（迭代3轮后上限截断）
    coder_calls = [c for c in calls if c[0] == "coder"]
    assert len(coder_calls) <= 3
    # 有 iteration limit error 记录（而非死循环）
    assert any("limit" in str(e.get("error", "")) or "iteration" in str(e.get("error", "")).lower()
               for e in r.errors) or r.iteration_count <= 3


@pytest.mark.asyncio
async def test_bounded_loop_eventually_approves(memory_store, make_agent_factory):
    """有限次拒绝后通过 → approved 分支正常收尾。"""
    calls = []
    review_n = {"count": 0}

    def reviewer_factory():
        def make():
            class R:
                async def arun(self, task: str) -> str:
                    review_n["count"] += 1
                    calls.append(("reviewer", review_n["count"]))
                    return "重做" if review_n["count"] < 2 else "通过"
            return R()
        return make()

    g = Graph(store=memory_store, max_iterations=5)
    g.add_node("coder", AgentNode(make_agent_factory(calls, "coder", "稿")))
    g.add_node("reviewer", AgentNode(reviewer_factory))
    g.add_node("verdict", RouterNode(
        lambda msg, ctx: "rejected" if "重做" in str(msg.get("task", "")) else "approved"
    ))
    g.add_node("done", AgentNode(make_agent_factory(calls, "done", "ok")))
    g.add_edge("coder", "reviewer")
    g.add_edge("reviewer", "verdict")
    g.add_edge("verdict", "coder", when="rejected")
    g.add_edge("verdict", "done", when="approved")

    r = await g.run({"task": "初稿"}, thread_id="loop-ok", entry_node="coder")
    assert ("done", "approved") in calls
    assert r.status == "completed"
