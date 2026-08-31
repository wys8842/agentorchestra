"""Agent 异步路径测试（mock LLM）"""


from agentorchestra.core.config import Config
from agentorchestra.core.lifecycle import AgentEvent, EventType
from agentorchestra.core.message import Message


class MockLLM:
    """最小 mock LLM"""

    def __init__(self, model="mock-model"):
        self.model = model

    def invoke(self, messages, **kwargs):
        return SimpleResponse("mock answer")

    def invoke_with_tools(self, messages, tools=None, tool_choice="auto", **kwargs):
        return SimpleChoice("直接回复，不调用工具")

    async def astream_invoke(self, messages, **kwargs):
        for chunk in ["mock ", "answer"]:
            yield chunk


class SimpleResponse:
    def __init__(self, content):
        self.content = content
        self.usage = {"total_tokens": 10}
        self.latency_ms = 5
        self.reasoning_content = None


class SimpleChoice:
    """mock invoke_with_tools 响应（无 tool_calls）"""

    def __init__(self, content):
        self.choices = [SimpleMessage(content)]


class SimpleMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class TestSimpleAgentAsync:
    def _make_agent(self):
        from agentorchestra.agents.simple_agent import SimpleAgent
        agent = SimpleAgent(
            name="async-agent",
            llm=MockLLM(),
            system_prompt="你是助手",
            config=Config(trace_enabled=False),
        )
        return agent

    async def test_arun_basic(self):
        agent = self._make_agent()
        result = await agent.arun("你好")
        assert "mock answer" in result

    async def test_arun_with_hooks(self):
        agent = self._make_agent()
        events = []

        async def on_start(event: AgentEvent):
            events.append(event.type)

        async def on_finish(event: AgentEvent):
            events.append(event.type)

        result = await agent.arun("hi", on_start=on_start, on_finish=on_finish)
        assert "mock answer" in result
        assert EventType.AGENT_START in events
        assert EventType.AGENT_FINISH in events

    async def test_arun_stream(self):
        agent = self._make_agent()
        event_types = []
        async for event in agent.arun_stream("hi"):
            event_types.append(event.type.value)
        assert "agent_start" in event_types
        assert "agent_finish" in event_types


class TestAgentMessageHistory:
    def test_add_message_updates_token_count(self):
        from agentorchestra.agents.simple_agent import SimpleAgent
        agent = SimpleAgent(
            name="h-agent",
            llm=MockLLM(),
            system_prompt="s",
            config=Config(trace_enabled=False),
        )
        assert agent._history_token_count == 0
        agent.add_message(Message("你好", "user"))
        assert agent._history_token_count > 0
        assert len(agent.get_history()) == 1

    def test_clear_history(self):
        from agentorchestra.agents.simple_agent import SimpleAgent
        agent = SimpleAgent(
            name="c-agent",
            llm=MockLLM(),
            system_prompt="s",
            config=Config(trace_enabled=False),
        )
        agent.add_message(Message("你好", "user"))
        agent.clear_history()
        assert len(agent.get_history()) == 0
        assert agent._history_token_count == 0
