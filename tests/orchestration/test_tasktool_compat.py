"""TaskTool 兼容与迁移适配器测试。"""

import pytest

from agentorchestra.orchestration import AgentNode, Graph, TaskToolGraphAdapter


class _FakeTaskAgent:
    def __init__(self, tag):
        self.tag = tag

    async def arun(self, task: str) -> str:
        calls.append((self.tag, task))
        return f"{self.tag}:{task}"


calls = []


def _tasktool_style_factory(agent_type: str):
    """与 TaskTool.agent_factory 相同签名。"""
    return _FakeTaskAgent(agent_type)


@pytest.mark.asyncio
async def test_tasktool_graph_adapter(memory_store):
    adapter = TaskToolGraphAdapter(_tasktool_style_factory, agent_type="react")
    g = Graph(store=memory_store)
    g.add_node("coder", adapter.make_node())
    r = await g.run({"task": "写代码"}, thread_id="adapt")
    assert r.status == "completed"
    assert ("react", "写代码") in calls


def test_guide_exists():
    from agentorchestra.orchestration import migration

    assert "TaskTool" in migration.GUIDE
    assert "Graph" in migration.GUIDE


def test_adapter_make_node_is_agent_node():
    adapter = TaskToolGraphAdapter(_tasktool_style_factory, agent_type="react")
    node = adapter.make_node()
    assert isinstance(node, AgentNode)
