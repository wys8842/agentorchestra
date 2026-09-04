"""OTLPHttpJsonExporter 载荷测试（mock transport，不真发）。"""

from agentorchestra.core.tracing import Span
from agentorchestra.observability.otel_exporter import OTLPHttpJsonExporter


def _make_span() -> Span:
    s = Span(name="llm.invoke", trace_id="abc", span_id="123",
             attributes={"model": "gpt", "tx_id": "tx-1", "obj_id": "o1",
                         "action_id": "a1", "flag": True, "n": 5})
    s.end()
    return s


def test_disabled_by_default():
    ex = OTLPHttpJsonExporter()
    assert ex.enabled is False
    ex.export(_make_span())  # 不发
    assert ex.sent == 0


def test_build_payload_structure():
    ex = OTLPHttpJsonExporter(service_name="svc-test")
    span = _make_span()
    payload = ex._build_payload(span)
    rs = payload["resourceSpans"][0]
    assert rs["resource"]["attributes"][0]["value"]["stringValue"] == "svc-test"
    otel_span = rs["scopeSpans"][0]["spans"][0]
    assert otel_span["name"] == "llm.invoke"
    assert otel_span["traceId"] == "abc".zfill(32)
    assert otel_span["spanId"] == "123".zfill(16)
    assert otel_span["status"]["code"] == 1  # OK
    attrs = {a["key"]: a["value"] for a in otel_span["attributes"]}
    assert attrs["tx_id"] == {"stringValue": "tx-1"}
    assert attrs["obj_id"] == {"stringValue": "o1"}
    assert attrs["action_id"] == {"stringValue": "a1"}
    assert attrs["flag"] == {"boolValue": True}
    assert attrs["n"] == {"intValue": "5"}


def test_error_status():
    ex = OTLPHttpJsonExporter()
    span = Span(name="x", trace_id="t", span_id="s")
    span.set_error()
    payload = ex._build_payload(span)
    otel_span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert otel_span["status"]["code"] == 2


def test_export_posts_when_enabled(monkeypatch):
    ex = OTLPHttpJsonExporter().enable()
    posted = {}

    def fake_post(payload):
        posted["payload"] = payload

    monkeypatch.setattr(ex, "_post", fake_post)
    ex.export(_make_span())
    assert ex.sent == 1
    assert posted["payload"]["resourceSpans"]


def test_parent_span_id():
    ex = OTLPHttpJsonExporter()
    span = Span(name="child", trace_id="t", span_id="s2", parent_id="p1")
    payload = ex._build_payload(span)
    otel_span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert otel_span["parentSpanId"] == "p1".zfill(16)
