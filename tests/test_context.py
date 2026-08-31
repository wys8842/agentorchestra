"""context 上下文工程测试"""

from symphony.context.builder import ContextBuilder, ContextConfig, ContextPacket
from symphony.context.history import HistoryManager
from symphony.context.token_counter import TokenCounter
from symphony.context.truncator import ObservationTruncator
from symphony.core.message import Message


class TestHistoryManager:
    def test_append_and_get(self):
        hm = HistoryManager(min_retain_rounds=2)
        hm.append(Message("q1", "user"))
        hm.append(Message("a1", "assistant"))
        history = hm.get_history()
        assert len(history) == 2
        assert history[0].role == "user"

    def test_estimate_rounds(self):
        hm = HistoryManager()
        hm.append(Message("q1", "user"))
        hm.append(Message("a1", "assistant"))
        hm.append(Message("q2", "user"))
        assert hm.estimate_rounds() == 2

    def test_compress_keeps_recent(self):
        hm = HistoryManager(min_retain_rounds=1)
        # 3 轮
        for i in range(3):
            hm.append(Message(f"q{i}", "user"))
            hm.append(Message(f"a{i}", "assistant"))
        assert len(hm.get_history()) == 6

        hm.compress("总结")
        history = hm.get_history()
        # 压缩后: summary + 最近1轮(2条)
        assert len(history) == 3
        assert history[0].role == "summary"
        assert "总结" in history[0].content


class TestTokenCounter:
    def test_count_message(self):
        counter = TokenCounter(model="gpt-4")
        msg = Message("hello world", "user")
        tokens = counter.count_message(msg)
        assert tokens > 0

    def test_count_messages(self):
        counter = TokenCounter(model="gpt-4")
        msgs = [Message("hello", "user"), Message("world", "assistant")]
        total = counter.count_messages(msgs)
        assert total > 0

    def test_cache(self):
        counter = TokenCounter(model="gpt-4")
        msg = Message("cache test", "user")
        t1 = counter.count_message(msg)
        t2 = counter.count_message(msg)  # 命中缓存
        assert t1 == t2
        assert counter.get_cache_size() >= 1


class TestObservationTruncator:
    def test_no_truncate(self):
        truncator = ObservationTruncator(max_lines=100, max_bytes=10000)
        result = truncator.truncate("tool", "short")
        assert result["truncated"] is False
        assert result["preview"] == "short"

    def test_truncate_head(self):
        truncator = ObservationTruncator(max_lines=2, max_bytes=10000)
        result = truncator.truncate("tool", "a\nb\nc\nd")
        assert result["truncated"] is True
        assert result["preview"] == "a\nb"
        assert result["full_output_path"] is not None


class TestContextBuilder:
    def test_build_basic(self):
        builder = ContextBuilder(config=ContextConfig(max_tokens=2000))
        ctx = builder.build(
            user_query="测试问题",
            conversation_history=[Message("q1", "user")],
            system_instructions="系统指令",
        )
        assert "测试问题" in ctx
        assert "系统指令" in ctx

    def test_knowledge_provider(self):
        def provider(query):
            return [ContextPacket(content="图谱数据", metadata={"type": "knowledge_base"})]

        builder = ContextBuilder(config=ContextConfig(max_tokens=2000),
                                 knowledge_provider=provider)
        ctx = builder.build(user_query="查一下")
        assert "图谱数据" in ctx
