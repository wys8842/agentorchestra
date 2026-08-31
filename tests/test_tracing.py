"""core/tracing 追踪测试"""
import json

import pytest

from symphony.core.tracing import (
    JsonlExporter,
    MemoryExporter,
    Tracer,
    get_tracer,
)


class TestTracer:
    def test_span_basic(self):
        tracer = Tracer(MemoryExporter())
        with tracer.span("op1") as span:
            span.set_attribute("key", "value")
        assert span.duration_ms >= 0
        assert span.status == "OK"

    def test_nested_spans(self):
        tracer = Tracer(MemoryExporter())
        with tracer.span("parent"):
            with tracer.span("child"):
                pass
        # 子 span 的 parent 是父 span
        exported = tracer.export_all()
        child_span = next(s for s in exported if s["name"] == "child")
        parent_span = next(s for s in exported if s["name"] == "parent")
        assert child_span["parent_id"] == parent_span["span_id"]
        # 同一 trace
        assert child_span["trace_id"] == parent_span["trace_id"]

    def test_trace_id_propagation(self):
        tracer = Tracer(MemoryExporter())
        assert tracer.current_trace_id() is None
        with tracer.span("op"):
            trace_id = tracer.current_trace_id()
            assert trace_id is not None
            assert len(trace_id) == 16

    def test_error_span(self):
        tracer = Tracer(MemoryExporter())
        with pytest.raises(ValueError):
            with tracer.span("failing"):
                raise ValueError("boom")
        exported = tracer.export_all()
        assert exported[0]["status"] == "ERROR"

    def test_add_event(self):
        tracer = Tracer(MemoryExporter())
        with tracer.span("op") as span:
            span.add_event("step", {"n": 1})
        exported = tracer.export_all()
        assert len(exported[0]["events"]) == 1
        assert exported[0]["events"][0]["name"] == "step"


class TestExporters:
    def test_memory_exporter(self):
        exporter = MemoryExporter()
        tracer = Tracer(exporter)
        with tracer.span("op"):
            pass
        assert len(exporter.spans) == 1
        assert exporter.spans[0]["name"] == "op"

    def test_jsonl_exporter(self, tmp_path):
        filepath = str(tmp_path / "spans.jsonl")
        tracer = Tracer(JsonlExporter(filepath))
        with tracer.span("op"):
            pass
        with open(filepath, encoding="utf-8") as f:
            line = f.readline().strip()
        data = json.loads(line)
        assert data["name"] == "op"


class TestGlobalTracer:
    def test_singleton(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2
