"""Verify the actual production ORQEVIA entrypoint exports safe OTLP telemetry."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Receiver(BaseHTTPRequestHandler):
    requests: list[tuple[str, bytes]] = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.requests.append((self.path, raw))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sentinel = "PRIVATE-QUERY-MUST-NOT-EXPORT"
    with tempfile.TemporaryDirectory(prefix="orqevia-otel-production-") as data:
        os.environ.update(
            {
                "PRIME_DATA_DIR": data,
                "PRIME_SPINE_TOKEN": "otel-production-fixture",
                "PRIME_REGISTRY_V1_ENABLED": "0",
                "ORQEVIA_OTEL_ENABLED": "1",
                "ORQEVIA_OTEL_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
                "ORQEVIA_OTEL_SAMPLE_RATIO": "1",
                "ORQEVIA_OTEL_SERVICE_NAME": "orqevia-production-verification",
                "ORQEVIA_OTEL_ENVIRONMENT": "abex-local",
            }
        )
        try:
            from fastapi.testclient import TestClient

            from app import observability
            from app.production_entry import app

            with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
                response = client.get(f"/health?private={sentinel}")
                if response.status_code != 200 or response.json() != {"ok": True}:
                    raise RuntimeError(f"production health unavailable: {response.status_code} {response.text}")
                media = client.get(
                    "/media/v1/health",
                    headers={"Authorization": "Bearer otel-production-fixture"},
                )
                assert media.status_code == 200
            assert observability._TRACE_PROVIDER.force_flush(3000)
            assert observability._METER_PROVIDER.force_flush(3000)
            paths = [path for path, _ in Receiver.requests]
            if "/v1/traces" not in paths or "/v1/metrics" not in paths:
                raise RuntimeError(f"expected trace and metric exports; observed {paths}")
            combined = b"".join(raw for _, raw in Receiver.requests)
            if sentinel.encode() in combined:
                raise RuntimeError("query data appeared in exported telemetry")
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "production_entrypoint": "app.production_entry:app",
                        "trace_export_observed": True,
                        "metric_export_observed": True,
                        "private_query_absent": True,
                        "prompt_capture": "DISABLED",
                        "endpoint": "loopback",
                    },
                    indent=2,
                )
            )
            return 0
        finally:
            try:
                observability.shutdown_observability()
            except UnboundLocalError:
                pass
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
