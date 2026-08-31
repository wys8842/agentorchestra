"""core/metrics 指标测试"""

from agentorchestra.core.metrics import MetricsCollector


class TestMetricsCollector:
    def test_disabled(self):
        metrics = MetricsCollector(enabled=False)
        # 禁用时 no-op，不报错
        metrics.record_llm_call("gpt-4", "openai", 100, 50)
        metrics.record_tool_call("Read")
        metrics.record_action_execution("create_order")
        metrics.request_start()
        metrics.request_end()

    def test_prometheus_available_or_graceful(self):
        metrics = MetricsCollector(enabled=True)
        # 无论是否装了 prometheus_client 都不应抛错
        metrics.record_llm_call("gpt-4", "openai", 100, 50)
        metrics.record_tool_call("Read", error=True)
        metrics.record_action_execution("create_order")
        metrics.request_start()
        metrics.request_end()

    def test_generate_latest(self):
        metrics = MetricsCollector(enabled=True)
        output = metrics.generate_latest()
        # 返回字符串（可能是真实 metrics 或降级提示）
        assert isinstance(output, str)
