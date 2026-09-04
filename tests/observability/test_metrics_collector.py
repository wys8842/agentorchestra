"""M5 observability 测试。"""

import pytest

from agentorchestra.observability.metrics import (
    NoOpCollector,
    PrometheusTextCollector,
    enable_prometheus_collector,
    get_default_collector,
    reset_default_collector,
)


@pytest.fixture(autouse=True)
def _reset_collector():
    reset_default_collector()
    yield
    reset_default_collector()


def test_counter_render():
    c = PrometheusTextCollector()
    c.increment("tx_rollback_total", 1, {"reason": "abort"})
    c.increment("tx_rollback_total", 1, {"reason": "abort"})
    text = c.render()
    assert "# TYPE tx_rollback_total counter" in text
    assert 'tx_rollback_total{reason="abort"} 2' in text


def test_histogram_render():
    c = PrometheusTextCollector()
    c.observe("tx_duration_seconds", 0.5, {"result": "committed"})
    text = c.render()
    assert "# TYPE tx_duration_seconds histogram" in text
    assert "tx_duration_seconds_count{result=\"committed\"} 1" in text
    assert "tx_duration_seconds_sum{result=\"committed\"}" in text


def test_gauge_render():
    c = PrometheusTextCollector()
    c.gauge("active_txs", 3)
    text = c.render()
    assert "# TYPE active_txs gauge" in text
    assert "active_txs 3" in text


def test_noop_zero_impact():
    """NoOp 默认：调用无副作用，render 空。"""
    col = get_default_collector()
    assert isinstance(col, NoOpCollector)
    col.increment("x", 1, {"a": "b"})
    col.observe("y", 1.0)
    col.gauge("z", 1.0)
    assert col.render() == ""


def test_enable_prometheus_collector():
    pc = enable_prometheus_collector()
    assert isinstance(get_default_collector(), PrometheusTextCollector)
    assert enable_prometheus_collector() is pc  # 幂等


def test_label_escaping():
    c = PrometheusTextCollector()
    c.increment("x", 1, {"tenant": 'a"b'})
    text = c.render()
    assert 'x{tenant="a\\"b"} 1' in text
