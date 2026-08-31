"""第二轮完善修复回归测试"""

from agentorchestra.tools.base import Tool, ToolParameter
from agentorchestra.tools.registry import ToolRegistry
from agentorchestra.tools.response import ToolResponse


class TestSimpleAgentSummaryFilter:
    """L7: SimpleAgent 过滤 summary 角色"""

    def test_summary_roles_filtered(self):
        from agentorchestra.agents.simple_agent import SimpleAgent
        from agentorchestra.core.message import Message

        # 构造带 summary 历史的最小 agent
        agent = SimpleAgent.__new__(SimpleAgent)
        agent.system_prompt = "system"
        from agentorchestra.context.history import HistoryManager
        hm = HistoryManager()
        hm.append(Message("旧摘要", "summary"))
        hm.append(Message("你好", "user"))
        agent.history_manager = hm

        # 通过 property 设置 _history
        agent._history = hm.get_history()

        messages = agent._build_messages("新问题")
        roles = [m["role"] for m in messages]
        # summary 不应作为独立消息
        assert "summary" not in roles
        # summary 内容以 system 形式注入
        assert any("旧摘要" in m["content"] for m in messages if m["role"] == "system")


class TestReActToolTruncation:
    """M9: 同步路径工具输出截断（截断器集成验证）"""

    def test_truncator_configuration(self):
        from agentorchestra.context.truncator import ObservationTruncator
        truncator = ObservationTruncator(max_lines=1, max_bytes=10)
        result = truncator.truncate("Long", "x" * 100)
        assert result["truncated"] is True
        assert len(result["preview"]) <= 10

    def test_run_impl_uses_truncator(self):
        """验证 _run_impl 中截断逻辑存在（静态检查）"""
        import inspect

        from agentorchestra.agents.react_agent import ReActAgent
        source = inspect.getsource(ReActAgent._run_impl)
        # 同步主循环中应调用 truncator
        assert "self.truncator" in source or "truncate" in source


class TestCircuitBreaker:
    """M8: 熔断器对 Tool 对象生效"""

    def test_circuit_breaker_blocks_tool(self):
        from agentorchestra.agents.react_agent import ReActAgent
        from agentorchestra.tools.circuit_breaker import CircuitBreaker

        class FailTool(Tool):
            def __init__(self):
                super().__init__(name="Fail", description="总是失败", expandable=False)

            def get_parameters(self):
                return [ToolParameter(name="x", type="string", description="x", required=True)]

            def run(self, parameters):
                return ToolResponse.error(code="X", message="失败")

        registry = ToolRegistry()
        # 配置熔断：失败 1 次就开启
        registry.circuit_breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout=300)
        registry.register_tool(FailTool())

        agent = ReActAgent.__new__(ReActAgent)
        agent.tool_registry = registry

        # 第一次调用 → 失败，记录
        r1 = agent._execute_tool_call("Fail", {"x": "a"})
        assert "错误" in r1

        # 熔断已开启 → 第二次被拦截
        r2 = agent._execute_tool_call("Fail", {"x": "a"})
        assert "CIRCUIT_OPEN" in r2 or "禁用" in r2


class TestGraphNodeProps:
    """GraphStore merge_node 显式 name 不冲突"""

    def test_name_field_conflict(self):
        from agentorchestra.ontology.storage.graph_store import GraphStore
        g = GraphStore()
        # 业务字段含 name，但节点名显式指定
        g.merge_node("customer", {"name": "张三", "id": "c1"}, name="customer:c1")
        assert "customer:c1" in g.list_nodes()
        assert g.get_node("customer:c1")["props"]["name"] == "张三"
