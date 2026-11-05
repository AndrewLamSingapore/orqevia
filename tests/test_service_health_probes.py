"""Validate shell-less probes without contacting services or reading credentials."""

import json
import pathlib
import socket
import ssl
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from scripts import probe_service_health as probes


START = "2026-11-05T00:00:00Z"


def _event(time, message):
    return f"2026-11-05T{time}Z 2026-11-05T{time}Z INF {message}"


def _registration(index, time="00:00:01"):
    return _event(time, f"Registered tunnel connection connIndex={index} connection=DO_NOT_EXPORT_TOKEN")


def test_tunnel_reconnect_updates_only_the_affected_connection():
    logs = "\n".join(
        [
            _registration(0),
            _registration(1),
            _event("00:00:02", "Retrying connection in up to 1s connIndex=0 error=SECRET"),
            _registration(0, "00:00:03"),
        ]
    )
    result = probes.parse_tunnel_readiness(logs, START)
    assert result["status"] == "PASS"
    assert result["registered_connections_observed"] == 2
    assert result["connections_with_later_interruption"] == 0
    assert "SECRET" not in json.dumps(result)
    assert "DO_NOT_EXPORT_TOKEN" not in json.dumps(result)


def test_later_disconnect_or_retry_cannot_be_reported_as_healthy():
    logs = "\n".join(
        [_registration(0), _registration(1), _event("00:00:02", "Unregistered tunnel connection connIndex=0")]
    )
    result = probes.parse_tunnel_readiness(logs, START)
    assert result["status"] == "UNKNOWN"
    assert result["connections_with_later_interruption"] == 1
    assert result["ingress_end_to_end_verified"] is False


def test_old_or_unsequenced_log_messages_do_not_qualify_current_process():
    assert probes.parse_tunnel_readiness(_registration(0), "2026-11-05T00:00:05Z")["status"] == "UNKNOWN"
    assert probes.parse_tunnel_readiness("Registered tunnel connection connIndex=0", START)["status"] == "UNKNOWN"
    assert probes.parse_tunnel_readiness(_registration(0), None)["status"] == "UNKNOWN"


def test_timestamp_order_restores_separate_docker_log_streams():
    logs = _registration(0, "00:00:04") + "\n" + _event("00:00:02", "Connection terminated connIndex=0")
    assert probes.parse_tunnel_readiness(logs, START)["status"] == "PASS"


def test_metadata_exports_only_allowlisted_fields():
    raw = {
        "Name": "/" + probes.OTEL,
        "Image": "sha256:" + "a" * 64,
        "RestartCount": 0,
        "State": {"Status": "running", "StartedAt": START, "Error": "SECRET"},
        "Config": {"Env": ["PRIVATE_KEY=SECRET"], "Cmd": ["--token", "SECRET"]},
    }
    result = probes._metadata(raw)
    assert result["state"] == "running"
    assert result["image_id"] == "sha256:" + "a" * 64
    assert "SECRET" not in json.dumps(result)
    assert not {"Env", "Cmd", "Config", "Error"} & result.keys()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:4318",
        "https://example.com:4318",
        "https://localhost:8443",
        "https://user:SECRET@localhost:4318",
        "https://localhost:4318/?token=SECRET",
        "https://localhost:4318/v1/traces",
    ],
)
def test_endpoint_does_not_allow_plaintext_credentials_or_unrelated_destinations(endpoint):
    with pytest.raises(ValueError, match="private HTTPS"):
        probes.run_probes(otel_https_endpoint=endpoint)


def test_false_tls_claim_is_downgraded_and_helper_secrets_are_removed():
    raw = {
        "status": "PASS",
        "mode": "LEGACY_PRIVATE_LOOPBACK_TCP_ONLY",
        "socket_accepting": True,
        "certificate_verified": False,
        "empty_payload_accepted": False,
        "response_code": None,
        "reason_code": "LEGACY_LOOPBACK_SOCKET_ONLY_TLS_UNQUALIFIED",
        "SECRET": "DO_NOT_EXPORT",
    }
    result = probes._safe_otlp_result(raw)
    assert result["status"] == "UNKNOWN"
    assert result["certificate_verified"] is False
    assert "SECRET" not in json.dumps(result)
    assert "DO_NOT_EXPORT" not in json.dumps(result)


def _runner(*, tls=False, stopped=False, broken_logs=False):
    calls = []

    def execute(args, *, input=None, timeout=15):
        calls.append((args, input))
        if args[1] == "inspect":
            data = [
                {
                    "Name": "/" + name,
                    "Image": "sha256:" + "f" * 64,
                    "RestartCount": 0,
                    "State": {"Status": "exited" if stopped else "running", "StartedAt": START},
                    "Config": {"Env": ["TOKEN=NEVER_EXPORT"], "Cmd": ["SECRET_COMMAND"]},
                }
                for name in (probes.OTEL, *probes.TUNNELS)
            ]
            return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr="NEVER_EXPORT")
        if args[1] == "logs":
            return SimpleNamespace(
                returncode=1 if broken_logs else 0,
                stdout=_registration(0) + "\n" + _registration(1),
                stderr="NEVER_EXPORT",
            )
        if args[1] == "exec":
            value = {
                "status": "PASS" if tls else "UNKNOWN",
                "mode": "VERIFIED_HTTPS_ATTEMPT" if tls else "LEGACY_PRIVATE_LOOPBACK_TCP_ONLY",
                "certificate_verified": tls,
                "empty_payload_accepted": tls,
                "response_code": 200 if tls else None,
                "socket_accepting": None if tls else True,
                "reason_code": "TLS_OTLP_RECEIVER_ACCEPTED_EMPTY_REQUEST"
                if tls
                else "LEGACY_LOOPBACK_SOCKET_ONLY_TLS_UNQUALIFIED",
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="NEVER_EXPORT")
        raise AssertionError("Unexpected command")

    return execute, calls


def test_legacy_socket_reports_unknown_while_tunnels_have_scoped_evidence():
    runner, calls = _runner()
    result = probes.run_probes(runner=runner)
    assert result["overall"] == "UNKNOWN"
    assert [service["status"] for service in result["services"]] == ["UNKNOWN", "PASS", "PASS"]
    assert result["services"][0]["readiness"]["socket_accepting"] is True
    assert all(service["readiness"]["ingress_end_to_end_verified"] is False for service in result["services"][1:])
    assert len(calls) == 4
    serialized = json.dumps(result)
    assert "NEVER_EXPORT" not in serialized and "SECRET_COMMAND" not in serialized
    assert result["plaintext_http_requests"] == 0


def test_verified_tls_receiver_is_pass_without_claiming_span_export():
    runner, calls = _runner(tls=True)
    result = probes.run_probes(runner=runner)
    assert result["overall"] == "PASS"
    otlp = result["services"][0]["readiness"]
    assert otlp["certificate_verified"] and otlp["empty_payload_accepted"]
    assert "NO_SPAN_PERSISTENCE_OR_EXPORT_PROOF" in otlp["evidence_scope"]
    program = next(program for args, program in calls if args[1] == "exec")
    assert "ssl.create_default_context(cafile=str(ca))" in program
    assert "data=b'{}'" in program
    assert "NoRedirect()" in program
    assert "CERT_NONE" not in program and "check_hostname=False" not in program


def test_stopped_service_fails_without_readiness_requests():
    runner, calls = _runner(stopped=True)
    result = probes.run_probes(runner=runner)
    assert result["overall"] == "FAIL"
    assert len(calls) == 1


def test_unavailable_logs_or_docker_are_unknown_without_error_text():
    runner, _ = _runner(tls=True, broken_logs=True)
    assert probes.run_probes(runner=runner)["overall"] == "UNKNOWN"

    def unavailable(*args, **kwargs):
        raise OSError("SECRET diagnostic")

    result = probes.run_probes(runner=unavailable)
    assert result["overall"] == "UNKNOWN"
    assert "SECRET" not in json.dumps(result)


def test_remote_legacy_probe_only_opens_existing_tcp_socket(monkeypatch, capsys):
    monkeypatch.setenv("ORQEVIA_OTEL_ENDPOINT", "http://127.0.0.1:4318")
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def connect(address, timeout):
        calls.append((address, timeout))
        return Connection()

    def no_http(*args, **kwargs):
        raise AssertionError("Legacy probe attempted HTTP")

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(urllib.request, "build_opener", no_http)
    exec(probes.OTEL_PROBE, {"EXPECTED_ENDPOINT": probes.EXPECTED_HTTPS_ENDPOINT})
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "UNKNOWN"
    assert result["socket_accepting"] is True
    assert calls == [(("127.0.0.1", 4318), 3)]


@pytest.mark.parametrize(
    "body,status,reason",
    [
        (b"{}", "PASS", "TLS_OTLP_RECEIVER_ACCEPTED_EMPTY_REQUEST"),
        (b'{"ok":true}', "FAIL", "OTLP_RESPONSE_INVALID"),
        (b'{"partialSuccess":{"rejectedSpans":"1"}}', "FAIL", "OTLP_PARTIAL_REJECTION"),
    ],
)
def test_remote_tls_probe_sends_only_empty_otlp_and_requires_protocol_response(
    monkeypatch, capsys, body, status, reason
):
    monkeypatch.setenv("ORQEVIA_OTEL_ENDPOINT", probes.EXPECTED_HTTPS_ENDPOINT)
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: str(self).replace("\\", "/") == "/run/orqevia-tls/ca.crt")
    contexts = []

    def verified_context(*, cafile):
        contexts.append(cafile)
        return object()

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            assert limit == 4097
            return body

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == probes.EXPECTED_HTTPS_ENDPOINT + "/v1/traces"
            assert request.data == b"{}" and request.method == "POST" and timeout == 5
            return Response()

    def build_opener(*handlers):
        redirect = next(handler for handler in handlers if isinstance(handler, urllib.request.HTTPRedirectHandler))
        assert redirect.redirect_request(None, None, 302, None, None, "http://plaintext.invalid") is None
        return Opener()

    monkeypatch.setattr(ssl, "create_default_context", verified_context)
    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    exec(probes.OTEL_PROBE, {"EXPECTED_ENDPOINT": probes.EXPECTED_HTTPS_ENDPOINT})
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == status and result["reason_code"] == reason
    assert contexts == [str(pathlib.Path("/run/orqevia-tls/ca.crt"))]


def test_remote_certificate_failure_is_never_plaintext_fallback(monkeypatch, capsys):
    monkeypatch.setenv("ORQEVIA_OTEL_ENDPOINT", probes.EXPECTED_HTTPS_ENDPOINT)
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: True)
    monkeypatch.setattr(ssl, "create_default_context", lambda **kwargs: object())

    class Opener:
        def open(self, request, timeout):
            raise urllib.error.URLError(ssl.SSLCertVerificationError("SECRET certificate diagnostic"))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    exec(probes.OTEL_PROBE, {"EXPECTED_ENDPOINT": probes.EXPECTED_HTTPS_ENDPOINT})
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert result["status"] == "FAIL" and result["reason_code"] == "TLS_VERIFICATION_FAILED"
    assert result["certificate_verified"] is False and "SECRET" not in raw
