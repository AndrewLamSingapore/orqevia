from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from app import observability
from app.observability import (
    ObservabilityMiddleware,
    ObservabilitySettings,
    span,
    trace_headers,
)


def providers():
    span_exporter = InMemorySpanExporter()
    trace_provider = TracerProvider(resource=Resource.create({"service.name": "fixture"}))
    trace_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    return span_exporter, trace_provider, trace_provider.get_tracer("fixture"), meter_provider, metric_reader


def test_middleware_records_only_bounded_route_metadata_and_metrics():
    exporter, trace_provider, tracer, meter_provider, metric_reader = providers()
    app = FastAPI()
    app.add_middleware(
        ObservabilityMiddleware,
        tracer_instance=tracer,
        meter_instance=meter_provider.get_meter("fixture"),
    )

    @app.post("/api/private-object")
    def private_object():
        return {"ok": True}

    client = TestClient(app)
    response = client.post("/api/private-object?token=must-not-appear", json={"prompt": "private"})
    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attributes = dict(spans[0].attributes)
    assert attributes["route_class"] == "api"
    assert attributes["http.method"] == "POST"
    assert attributes["http.response.status_code"] == 200
    assert attributes["status"] == "OK"
    assert "must-not-appear" not in str(attributes)
    assert "private" not in str(attributes)
    metrics_data = metric_reader.get_metrics_data()
    metric_names = {
        metric.name
        for resource_metric in metrics_data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
    }
    assert "orqevia.http.server.requests" in metric_names
    assert "orqevia.http.server.duration" in metric_names
    trace_provider.shutdown()
    meter_provider.shutdown()


def test_internal_span_attribute_allowlist_and_trace_propagation(monkeypatch):
    exporter, trace_provider, tracer, meter_provider, _ = providers()
    monkeypatch.setattr(observability, "_TRACER", tracer)
    with span("rag.retrieve", {"component": "rag", "operation": "retrieve", "question": "secret question"}):
        headers = trace_headers()
    assert headers["traceparent"].startswith("00-")
    attributes = dict(exporter.get_finished_spans()[0].attributes)
    assert attributes == {"component": "rag", "operation": "retrieve"}
    trace_provider.shutdown()
    meter_provider.shutdown()


def test_loopback_otlp_trace_export():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "length": int(self.headers.get("Content-Length", "0")),
                }
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = TracerProvider(resource=Resource.create({"service.name": "fixture"}))
        exporter = OTLPSpanExporter(
            endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces",
            timeout=3,
        )
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("fixture")
        tracer.start_span("loopback.probe").end()
        assert provider.force_flush(3000)
        assert received and received[0]["path"] == "/v1/traces"
        assert received[0]["length"] > 0
        provider.shutdown()
    finally:
        server.shutdown()
        server.server_close()


def test_endpoint_validation_rejects_remote_collectors():
    for endpoint in (
        "https://collector.example.com",
        "http://192.168.1.50:4318",
        "http://user:pass@127.0.0.1:4318",
    ):
        settings = ObservabilitySettings(enabled=True, endpoint=endpoint)
        try:
            settings.validated_endpoint()
        except ValueError:
            pass
        else:
            raise AssertionError(endpoint)
    assert ObservabilitySettings(endpoint="http://127.0.0.1:4318").validated_endpoint().endswith("4318")


def test_disabled_install_performs_no_network_probe():
    app = FastAPI()
    result = observability.install_observability(app, ObservabilitySettings(enabled=False))
    assert result == {"status": "DISABLED", "network_probe_performed": False}


def test_production_apps_disable_native_fastapi_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ORQEVIA_LOCAL_AI_ROOT", str(tmp_path / "local-ai"))
    from app.interface_server import app as interface_app
    from app.local_knowledge_service import app as knowledge_app
    from app.production_entry import app as production_app

    for app in (production_app, interface_app, knowledge_app):
        assert app._telemetry["tracing"] is False
        assert app._telemetry["metrics"] is False
        assert app._telemetry["logs"] is False
        assert app._telemetry["operation_spans"] is False


def test_missing_opentelemetry_degrades_to_noop(monkeypatch):
    monkeypatch.setattr(observability, "_TRACER", None)
    monkeypatch.setattr(observability, "_OTEL_AVAILABLE", False)
    monkeypatch.setattr(observability, "trace", None)
    monkeypatch.setattr(observability, "propagate", None)
    with span("optional.noop", {"component": "rag"}) as current:
        current.set_attribute("status", "OK")
    assert trace_headers({"content-type": "application/json"}) == {"content-type": "application/json"}
    result = observability.install_observability(
        FastAPI(),
        ObservabilitySettings(enabled=True),
    )
    assert result == {
        "status": "UNAVAILABLE",
        "error": "OPENTELEMETRY_NOT_INSTALLED",
        "network_probe_performed": False,
    }
