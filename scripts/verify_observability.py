"""Verify loopback OTLP export, privacy, and measured request overhead."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import observability
from app.observability import ObservabilitySettings, install_observability


class Receiver(BaseHTTPRequestHandler):
    body = bytearray()
    requests: list[tuple[str, bytes]] = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.requests.append((self.path, raw))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        return


def build_app(instrumented: bool, endpoint: str):
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/control/private")
    def private(payload: dict):
        return {"accepted": bool(payload)}

    state = {"status": "NOT_INSTALLED"}
    if instrumented:
        state = install_observability(
            app,
            ObservabilitySettings(
                enabled=True,
                endpoint=endpoint,
                sample_ratio=1.0,
                service_name="orqevia-verification",
                environment="abex-local",
            ),
        )
    return app, state


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    sentinel = "PRIVATE-PROMPT-MUST-NOT-EXPORT"
    try:
        baseline_app, _ = build_app(False, endpoint)
        baseline = TestClient(baseline_app)
        instrumented_app, state = build_app(True, endpoint)
        instrumented = TestClient(instrumented_app)
        if state.get("status") != "ENABLED":
            raise RuntimeError(f"instrumentation unavailable: {state}")

        def measure(client: TestClient, count: int = 120) -> list[float]:
            values = []
            for _ in range(count):
                started = time.perf_counter_ns()
                response = client.post("/control/private", json={"prompt": sentinel})
                assert response.status_code == 200
                values.append((time.perf_counter_ns() - started) / 1_000_000)
            return values

        baseline_ms = measure(baseline)
        instrumented_ms = measure(instrumented)
        assert observability._TRACE_PROVIDER.force_flush(3000)
        assert observability._METER_PROVIDER.force_flush(3000)

        payloads = dict(Receiver.requests)
        if "/v1/traces" not in payloads:
            raise RuntimeError("no OTLP trace export observed")
        if "/v1/metrics" not in payloads:
            raise RuntimeError("no OTLP metric export observed")
        combined = b"".join(raw for _, raw in Receiver.requests)
        if sentinel.encode() in combined:
            raise RuntimeError("private request body appeared in telemetry")
        result = {
            "status": "PASS",
            "endpoint": endpoint,
            "trace_export_bytes": len(payloads["/v1/traces"]),
            "metric_export_bytes": len(payloads["/v1/metrics"]),
            "body_capture": "ABSENT",
            "prompt_capture": "ABSENT",
            "baseline_median_ms": round(statistics.median(baseline_ms), 4),
            "instrumented_median_ms": round(statistics.median(instrumented_ms), 4),
            "median_overhead_ms": round(statistics.median(instrumented_ms) - statistics.median(baseline_ms), 4),
            "requests_per_measurement": len(baseline_ms),
        }
        print(json.dumps(result, indent=2))
        return 0
    finally:
        observability.shutdown_observability()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
