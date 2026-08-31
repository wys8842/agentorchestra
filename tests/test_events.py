"""core 事件系统/流式/会话/响应模型测试"""

from symphony.core.lifecycle import AgentEvent, EventType, ExecutionContext
from symphony.core.llm_response import LLMResponse
from symphony.core.streaming import (
    StreamBuffer,
    StreamEvent,
    StreamEventType,
    stream_to_json,
    stream_to_sse,
)


class TestAgentEvent:
    def test_create(self):
        event = AgentEvent.create(EventType.TOOL_CALL, "agent1",
                                  tool_name="Read", step=1)
        assert event.type == EventType.TOOL_CALL
        assert event.agent_name == "agent1"
        assert event.data["tool_name"] == "Read"
        assert event.timestamp > 0

    def test_to_dict(self):
        event = AgentEvent.create(EventType.AGENT_START, "a", input="x")
        data = event.to_dict()
        assert data["type"] == "agent_start"
        assert data["agent_name"] == "a"

    def test_str(self):
        event = AgentEvent.create(EventType.AGENT_FINISH, "a")
        assert "[agent_finish]" in str(event)


class TestStreamEvent:
    def test_create_and_to_dict(self):
        event = StreamEvent.create(StreamEventType.LLM_CHUNK, "a", chunk="hello")
        data = event.to_dict()
        assert data["type"] == "llm_chunk"
        assert data["data"]["chunk"] == "hello"

    def test_to_sse(self):
        event = StreamEvent.create(StreamEventType.LLM_CHUNK, "a", chunk="hi")
        sse = event.to_sse()
        assert sse.startswith("event: llm_chunk")
        assert 'data: {"type"' in sse


class TestStreamBuffer:
    def test_add_and_get(self):
        buf = StreamBuffer(max_buffer_size=5)
        for i in range(5):
            buf.add(StreamEvent.create(StreamEventType.LLM_CHUNK, "a", chunk=str(i)))
        assert len(buf.get_all()) == 5

    def test_backpressure(self):
        buf = StreamBuffer(max_buffer_size=2)
        for i in range(4):
            buf.add(StreamEvent.create(StreamEventType.LLM_CHUNK, "a", chunk=str(i)))
        # 背压：只保留最近 2 个
        assert len(buf.get_all()) == 2

    def test_filter_by_type(self):
        buf = StreamBuffer()
        buf.add(StreamEvent.create(StreamEventType.LLM_CHUNK, "a"))
        buf.add(StreamEvent.create(StreamEventType.AGENT_START, "a"))
        filtered = buf.filter_by_type(StreamEventType.LLM_CHUNK)
        assert len(filtered) == 1


class TestStreamHelpers:
    async def test_stream_to_sse(self):
        async def gen():
            yield StreamEvent.create(StreamEventType.AGENT_START, "a")

        result = []
        async for sse in stream_to_sse(gen()):
            result.append(sse)
        assert len(result) == 1
        assert result[0].startswith("event: agent_start")

    async def test_stream_to_json(self):
        async def gen():
            yield StreamEvent.create(StreamEventType.AGENT_START, "a")

        result = []
        async for js in stream_to_json(gen()):
            result.append(js)
        assert len(result) == 1
        assert '"agent_start"' in result[0]


class TestLLMResponse:
    def test_response_model(self):
        resp = LLMResponse(content="hello", model="gpt-4o",
                           usage={"total_tokens": 10})
        assert resp.content == "hello"
        assert resp.model == "gpt-4o"
        assert resp.usage["total_tokens"] == 10

    def test_reasoning_content(self):
        resp = LLMResponse(content="answer", model="r1",
                           reasoning_content="thinking...")
        assert resp.reasoning_content == "thinking..."

    def test_to_dict(self):
        resp = LLMResponse(content="hi", model="gpt-4o")
        data = resp.to_dict()
        assert data["content"] == "hi"


class TestExecutionContext:
    def test_increment_step(self):
        ctx = ExecutionContext(input_text="hi")
        ctx.increment_step()
        ctx.increment_step()
        assert ctx.current_step == 2

    def test_add_tokens(self):
        ctx = ExecutionContext(input_text="hi")
        ctx.add_tokens(100)
        ctx.add_tokens(50)
        assert ctx.total_tokens == 150

    def test_metadata(self):
        ctx = ExecutionContext(input_text="hi")
        ctx.set_metadata("agent", "a")
        assert ctx.get_metadata("agent") == "a"
        assert ctx.get_metadata("missing", "default") == "default"
