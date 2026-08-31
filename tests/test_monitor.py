"""core/health + monitor 测试"""
import json
import urllib.request

from symphony.core.health import HealthCheck
from symphony.core.monitor import MonitorServer
from symphony.core.tracing import MemoryExporter, Tracer


class TestHealthCheck:
    def test_basic_check(self):
        hc = HealthCheck("test")
        hc.register_basic()
        result = hc.check()
        assert result["status"] == "ok"
        assert len(result["checks"]) == 1
        assert result["checks"][0]["name"] == "runtime"

    def test_degraded(self):
        hc = HealthCheck("test")
        hc.register(lambda: {"name": "db", "status": "error", "detail": "down"})
        result = hc.check()
        assert result["status"] == "degraded"

    def test_check_exception(self):
        hc = HealthCheck("test")

        def bad():
            raise RuntimeError("boom")

        hc.register(bad)
        result = hc.check()
        assert result["status"] == "degraded"
        assert result["checks"][0]["status"] == "error"


class TestMonitorServer:
    def _start_server(self):
        tracer = Tracer(MemoryExporter())
        hc = HealthCheck("symphony")
        hc.register_basic()
        with tracer.span("test_op"):
            pass

        server = MonitorServer(
            host="127.0.0.1",
            port=0,  # 自动分配端口
            health_check=hc,
            metrics_provider=lambda: "# test metric 1",
            traces_provider=tracer.export_all,
        )
        server.start()
        return server, tracer

    def test_health_endpoint(self):
        server, _ = self._start_server()
        try:
            port = server._server.server_address[1]
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health") as resp:
                data = json.loads(resp.read())
            assert data["status"] == "ok"
            assert data["checks"][0]["name"] == "runtime"
        finally:
            server.stop()

    def test_metrics_endpoint(self):
        server, _ = self._start_server()
        try:
            port = server._server.server_address[1]
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/metrics") as resp:
                text = resp.read().decode()
            assert "# test metric" in text
        finally:
            server.stop()

    def test_traces_endpoint(self):
        server, tracer = self._start_server()
        try:
            port = server._server.server_address[1]
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/traces") as resp:
                data = json.loads(resp.read())
            assert data["count"] == 1
            assert data["spans"][0]["name"] == "test_op"
        finally:
            server.stop()

    def test_root_endpoint(self):
        server, _ = self._start_server()
        try:
            port = server._server.server_address[1]
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/") as resp:
                data = json.loads(resp.read())
            assert "endpoints" in data
        finally:
            server.stop()
