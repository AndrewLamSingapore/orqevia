"""Privacy-first optional OpenTelemetry instrumentation.

Telemetry is disabled by default. When enabled, collection is restricted to a
loopback OTLP/HTTP endpoint. Request/response bodies, prompts, credentials,
question text and arbitrary headers are never recorded.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import inspect
import math
import os
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlsplit

from opentelemetry import context, metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode


_SAFE_ATTRIBUTES = frozenset(
    {
        "component",
        "operation",
        "status",
        "provider",
        "backend",
        "route_class",
        "http.method",
        "http.response.status_code",
        "job_type",
        "document_count",
        "chunk_count",
        "result_count",
        "error_code",
    }
)
_STATE_LOCK = threading.Lock()
_INSTALLED = False
_TRACER = None
_METER = None
_TRACE_PROVIDER = None
_METER_PROVIDER = None
_COUNTERS: dict[str, Any] = {}
_HISTOGRAMS: dict[str, Any] = {}


@dataclass(frozen=True)
class ObservabilitySettings:
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:4318"
    service_name: str = "orqevia"
    environment: str = "abex-local"
    sample_ratio: float = 0.1
    service_version: str = "UNKNOWN"

    @classmethod
    def from_env(cls) -> "ObservabilitySettings":
        enabled = os.getenv("ORQEVIA_OTEL_ENABLED", "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        endpoint = os.getenv("ORQEVIA_OTEL_ENDPOINT", "http://127.0.0.1:4318").strip().rstrip("/")
        try:
            sample_ratio = float(os.getenv("ORQEVIA_OTEL_SAMPLE_RATIO", "0.1"))
        except ValueError:
            sample_ratio = 0.1
        if not math.isfinite(sample_ratio):
            sample_ratio = 0.1
        return cls(
            enabled=enabled,
            endpoint=endpoint,
            service_name=os.getenv("ORQEVIA_OTEL_SERVICE_NAME", "orqevia").strip() or "orqevia",
            environment=os.getenv("ORQEVIA_OTEL_ENVIRONMENT", "abex-local").strip() or "abex-local",
            sample_ratio=max(0.0, min(1.0, sample_ratio)),
            service_version=os.getenv("PRIME_RUNTIME_REVISION", "UNKNOWN").strip() or "UNKNOWN",
        )

    def validated_endpoint(self) -> str:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OTLP endpoint must be a credential-free loopback URL")
        return self.endpoint


def _safe_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(attributes, Mapping):
        return {}
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        if key not in _SAFE_ATTRIBUTES:
            continue
        if isinstance(value, str):
            clean[key] = value[:200]
        elif isinstance(value, (bool, int)):
            clean[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            clean[key] = value
    return clean


def tracer():
    return _TRACER or trace.get_tracer("orqevia.noop")


def meter():
    return _METER or metrics.get_meter("orqevia.noop")


@contextmanager
def span(name: str, attributes: Mapping[str, Any] | None = None):
    current = tracer()
    with current.start_as_current_span(name[:120], attributes=_safe_attributes(attributes)) as value:
        try:
            yield value
        except Exception as error:
            value.record_exception(error)
            value.set_status(Status(StatusCode.ERROR))
            raise


def traced(name: str, attributes: Mapping[str, Any] | None = None):
    def decorate(function):
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapper(*args, **kwargs):
                with span(name, attributes):
                    return await function(*args, **kwargs)

            return async_wrapper

        @wraps(function)
        def wrapper(*args, **kwargs):
            with span(name, attributes):
                return function(*args, **kwargs)

        return wrapper

    return decorate


def record_counter(name: str, value: int = 1, attributes: Mapping[str, Any] | None = None) -> None:
    if _METER is None or type(value) is not int or value < 0:
        return
    try:
        with _STATE_LOCK:
            instrument = _COUNTERS.get(name)
            if instrument is None:
                instrument = _METER.create_counter(name, unit="1")
                _COUNTERS[name] = instrument
        instrument.add(value, _safe_attributes(attributes))
    except Exception:
        return


def record_duration(
    name: str,
    milliseconds: float,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    if _METER is None or not math.isfinite(milliseconds) or milliseconds < 0:
        return
    try:
        with _STATE_LOCK:
            instrument = _HISTOGRAMS.get(name)
            if instrument is None:
                instrument = _METER.create_histogram(name, unit="ms")
                _HISTOGRAMS[name] = instrument
        instrument.record(milliseconds, _safe_attributes(attributes))
    except Exception:
        return


def trace_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    carrier = dict(headers or {})
    try:
        propagate.inject(carrier)
    except Exception:
        pass
    return carrier


def _route_class(path: str) -> str:
    if path == "/health":
        return "health"
    if path.startswith("/pwa/"):
        return "pwa"
    if path.startswith("/interface/"):
        return "interface"
    if path.startswith("/media/"):
        return "media"
    if path.startswith("/control"):
        return "control"
    if path.startswith("/api/"):
        return "api"
    return "other"


class ObservabilityMiddleware:
    def __init__(self, app, *, tracer_instance=None, meter_instance=None):
        self.app = app
        self.tracer = tracer_instance or tracer()
        self.meter_instance = meter_instance or meter()
        self.requests = self.meter_instance.create_counter("orqevia.http.server.requests", unit="1")
        self.duration = self.meter_instance.create_histogram("orqevia.http.server.duration", unit="ms")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        carrier = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        parent = propagate.extract(carrier)
        path = str(scope.get("path", ""))
        route_class = _route_class(path)
        attributes = {
            "http.method": str(scope.get("method", ""))[:16],
            "route_class": route_class,
        }
        started = time.perf_counter()
        status_code = 500
        failed = False
        token = context.attach(
            trace.set_span_in_context(
                self.tracer.start_span("http.server", context=parent, kind=SpanKind.SERVER, attributes=attributes)
            )
        )
        current = trace.get_current_span()
        try:

            async def observe(message):
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = int(message.get("status", 500))
                await send(message)

            await self.app(scope, receive, observe)
        except Exception as error:
            failed = True
            current.record_exception(error)
            current.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            elapsed = max(0.0, (time.perf_counter() - started) * 1000)
            current.set_attribute("http.response.status_code", status_code)
            current.set_attribute("status", "ERROR" if failed or status_code >= 500 else "OK")
            try:
                self.requests.add(
                    1,
                    {
                        "http.method": attributes["http.method"],
                        "route_class": route_class,
                        "status": "ERROR" if failed or status_code >= 500 else "OK",
                    },
                )
                self.duration.record(
                    elapsed,
                    {
                        "http.method": attributes["http.method"],
                        "route_class": route_class,
                    },
                )
            except Exception:
                pass
            context.detach(token)
            current.end()


def install_observability(app, settings: ObservabilitySettings | None = None) -> dict[str, Any]:
    global _INSTALLED, _TRACER, _METER, _TRACE_PROVIDER, _METER_PROVIDER
    settings = settings or ObservabilitySettings.from_env()
    if not settings.enabled:
        return {"status": "DISABLED", "network_probe_performed": False}
    try:
        endpoint = settings.validated_endpoint()
    except ValueError as error:
        return {"status": "CONFIGURATION_REJECTED", "error": str(error)}
    with _STATE_LOCK:
        if _INSTALLED:
            return {"status": "ALREADY_INSTALLED", "endpoint": endpoint}
        try:
            from opentelemetry.sdk.trace.sampling import (
                ParentBased,
                TraceIdRatioBased,
            )

            resource = Resource.create(
                {
                    "service.name": settings.service_name,
                    "service.version": settings.service_version,
                    "deployment.environment": settings.environment,
                }
            )
            trace_exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=3)
            trace_provider = TracerProvider(
                resource=resource,
                sampler=ParentBased(TraceIdRatioBased(settings.sample_ratio)),
            )
            trace_provider.add_span_processor(
                BatchSpanProcessor(
                    trace_exporter,
                    max_queue_size=512,
                    schedule_delay_millis=5000,
                    max_export_batch_size=64,
                    export_timeout_millis=3000,
                )
            )
            metric_exporter = OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=3)
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[
                    PeriodicExportingMetricReader(
                        metric_exporter,
                        export_interval_millis=15000,
                        export_timeout_millis=3000,
                    )
                ],
            )
            trace.set_tracer_provider(trace_provider)
            metrics.set_meter_provider(meter_provider)
            _TRACE_PROVIDER = trace_provider
            _METER_PROVIDER = meter_provider
            _TRACER = trace_provider.get_tracer("orqevia")
            _METER = meter_provider.get_meter("orqevia")
            app.add_middleware(ObservabilityMiddleware)
            _INSTALLED = True
            return {
                "status": "ENABLED",
                "endpoint": endpoint,
                "sample_ratio": settings.sample_ratio,
                "body_capture": "DISABLED",
                "prompt_capture": "DISABLED",
                "network_probe_performed": False,
            }
        except Exception as error:
            return {
                "status": "UNAVAILABLE",
                "error": type(error).__name__,
                "network_probe_performed": False,
            }


def shutdown_observability(timeout_millis: int = 3000) -> None:
    for provider in (_METER_PROVIDER, _TRACE_PROVIDER):
        if provider is None:
            continue
        try:
            provider.shutdown(timeout_millis=timeout_millis)
        except Exception:
            pass
