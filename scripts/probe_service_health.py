"""On-demand shell-less service probes, with sanitized evidence and HTTPS only.

No environment values, commands, credentials or raw logs are exported. Existing
legacy OTLP loopback transport receives only a TCP-connect check, never an HTTP
request. The opt-in configured private TLS endpoint can receive one empty OTLP
request; acceptance proves the receiver, not span persistence or export.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


BACKEND = "orqevia-epoch-20261016-backend-1"
OTEL = "orqevia-epoch-20261016-otel-collector-1"
TUNNELS = ("orqevia-epoch-20261016-cloudflared-1", "orqevia-epoch-20261016-cloudflared-dual-1")
EXPECTED_HTTPS_ENDPOINT = "https://desktop-27lkj2v.local:4318"
_STATUSES = {"PASS", "FAIL", "UNKNOWN"}
_REASONS = {
    "TLS_OTLP_RECEIVER_ACCEPTED_EMPTY_REQUEST",
    "TLS_VERIFICATION_FAILED",
    "OTLP_HTTP_REJECTED",
    "OTLP_CONNECTION_FAILED",
    "OTLP_RESPONSE_INVALID",
    "OTLP_PARTIAL_REJECTION",
    "PUBLIC_CA_UNAVAILABLE",
    "LEGACY_LOOPBACK_SOCKET_ONLY_TLS_UNQUALIFIED",
    "LEGACY_LOOPBACK_SOCKET_UNAVAILABLE",
    "OTLP_ENDPOINT_CONFIGURATION_MISMATCH",
    "BACKEND_PROBE_UNAVAILABLE",
    "BACKEND_PROBE_INVALID",
}


OTEL_PROBE = r"""
import json,os,pathlib,socket,ssl,urllib.error,urllib.parse,urllib.request
out={'status':'UNKNOWN','mode':'UNVERIFIED','certificate_verified':False,
     'empty_payload_accepted':False,'socket_accepting':None,'response_code':None}
configured=os.environ.get('ORQEVIA_OTEL_ENDPOINT','http://127.0.0.1:4318').strip().rstrip('/')
parts=urllib.parse.urlsplit(configured)
safe=not (parts.username or parts.password or parts.query or parts.fragment) and parts.path in ('','/')
try:port=parts.port
except ValueError:port=None
if safe and configured==EXPECTED_ENDPOINT:
 out['mode']='VERIFIED_HTTPS_ATTEMPT'
 ca=pathlib.Path('/run/orqevia-tls/ca.crt')
 if not ca.is_file():out['reason_code']='PUBLIC_CA_UNAVAILABLE'
 else:
  try:
   context=ssl.create_default_context(cafile=str(ca))
   class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=context))
   request=urllib.request.Request(configured+'/v1/traces',data=b'{}',headers={'Content-Type':'application/json'},method='POST')
   with opener.open(request,timeout=5) as response:
    out['response_code']=response.status;out['certificate_verified']=True
    body=response.read(4097)
   if len(body)>4096:raise ValueError()
   payload=json.loads(body) if body else {}
   if type(payload) is not dict or set(payload)-{'partialSuccess'}:raise ValueError()
   partial=payload.get('partialSuccess',{})
   if type(partial) is not dict:raise ValueError()
   rejected=partial.get('rejectedSpans',0)
   if rejected not in (0,'0',None):
    out.update(status='FAIL',reason_code='OTLP_PARTIAL_REJECTION')
   elif out['response_code']==200:
    out.update(status='PASS',empty_payload_accepted=True,reason_code='TLS_OTLP_RECEIVER_ACCEPTED_EMPTY_REQUEST')
   else:out.update(status='FAIL',reason_code='OTLP_HTTP_REJECTED')
  except urllib.error.HTTPError as error:
   out.update(status='FAIL',certificate_verified=True,response_code=error.code,reason_code='OTLP_HTTP_REJECTED')
  except (ssl.SSLError,ssl.CertificateError):out.update(status='FAIL',reason_code='TLS_VERIFICATION_FAILED')
  except urllib.error.URLError as error:
   out.update(status='FAIL',reason_code='TLS_VERIFICATION_FAILED' if isinstance(error.reason,ssl.SSLError) else 'OTLP_CONNECTION_FAILED')
  except (OSError,TimeoutError):out.update(status='FAIL',reason_code='OTLP_CONNECTION_FAILED')
  except (ValueError,TypeError):out.update(status='FAIL',reason_code='OTLP_RESPONSE_INVALID')
elif safe and parts.scheme=='http' and parts.hostname in ('127.0.0.1','localhost','::1') and port==4318:
 out['mode']='LEGACY_PRIVATE_LOOPBACK_TCP_ONLY'
 try:
  with socket.create_connection((parts.hostname,4318),timeout=3):pass
  out.update(socket_accepting=True,reason_code='LEGACY_LOOPBACK_SOCKET_ONLY_TLS_UNQUALIFIED')
 except (OSError,TimeoutError):
  out.update(status='FAIL',socket_accepting=False,reason_code='LEGACY_LOOPBACK_SOCKET_UNAVAILABLE')
else:out['reason_code']='OTLP_ENDPOINT_CONFIGURATION_MISMATCH'
print(json.dumps(out))
"""


def _run(args, *, input=None, timeout=15):
    return subprocess.run(
        args, input=input, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _metadata(item):
    item = item if isinstance(item, dict) else {}
    state = item.get("State", {})
    state = state if isinstance(state, dict) else {}
    status = state.get("Status")
    health = state.get("Health", {})
    health = health.get("Status") if isinstance(health, dict) else None
    started = _time(state.get("StartedAt"))
    image = item.get("Image")
    restarts = item.get("RestartCount")
    return {
        "state": status
        if status in {"running", "created", "restarting", "exited", "dead", "paused", "removing"}
        else "UNKNOWN",
        "docker_health": health if health in {"healthy", "unhealthy", "starting"} else "NOT_DECLARED",
        "started_at_utc": started.isoformat() if started else None,
        "restart_count": restarts if type(restarts) is int and restarts >= 0 else None,
        "image_id": image if isinstance(image, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image) else None,
    }


def parse_tunnel_readiness(logs, started_at):
    """Interpret timestamped current-process connection events; never return logs."""
    started = _time(started_at)
    events, unsequenced = [], 0
    for line in logs.splitlines():
        registration = bool(re.search(r"\bRegistered tunnel connection\b", line, re.I))
        disconnected = bool(
            re.search(
                r"\b(?:Unregistered tunnel connection|Retrying connection|Connection terminated|failed to serve tunnel connection)\b",
                line,
                re.I,
            )
        )
        if not registration and not disconnected:
            continue
        stamp = _time(line.split(" ", 1)[0])
        if stamp is None:
            unsequenced += 1
            continue
        if started is None or stamp < started:
            continue
        index_match = re.search(r"\bconnIndex=(\d{1,3})\b", line)
        index = int(index_match.group(1)) if index_match else None
        events.append((stamp, index, registration and not disconnected))
    # Docker stdout/stderr may arrive as separate buffers. Restore timestamp order.
    events.sort(key=lambda event: event[0])
    connections, global_disconnect = {}, False
    for _, index, registered in events:
        if index is None:
            if not registered:
                connections.clear()
                global_disconnect = True
            continue
        connections[index] = registered
        if registered:
            global_disconnect = False
    registered = sum(value is True for value in connections.values())
    interrupted = sum(value is False for value in connections.values())
    passed = started is not None and registered > 0 and interrupted == 0 and not global_disconnect and unsequenced == 0
    return {
        "status": "PASS" if passed else "UNKNOWN",
        "reason_code": "REGISTERED_CURRENT_PROCESS_NO_LATER_INTERRUPTION" if passed else "TUNNEL_READINESS_NOT_PROVEN",
        "registered_connections_observed": registered,
        "connections_with_later_interruption": interrupted,
        "recognized_events": len(events),
        "unsequenced_events": unsequenced,
        "last_connection_event_utc": events[-1][0].isoformat() if events else None,
        "evidence_scope": "CURRENT_PROCESS_TUNNEL_CONNECTION_LOGS_ONLY",
        "ingress_end_to_end_verified": False,
    }


def _validate_https_endpoint(value):
    try:
        parts = urlsplit(value)
        private_host = parts.hostname in {"localhost", "::1"} or bool(
            parts.hostname and parts.hostname.endswith(".local")
        )
        if not private_host:
            try:
                private_host = ipaddress.ip_address(parts.hostname or "").is_private
            except ValueError:
                private_host = False
        if (
            parts.scheme != "https"
            or not private_host
            or parts.port != 4318
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError()
        return value.rstrip("/")
    except (ValueError, TypeError):
        raise ValueError("Expected a credential-free private HTTPS OTLP origin on port 4318") from None


def _safe_otlp_result(raw):
    if not isinstance(raw, dict):
        raw = {}
    mode = raw.get("mode")
    code = raw.get("response_code")
    reason = raw.get("reason_code")
    status = raw.get("status")
    certificate_verified = raw.get("certificate_verified") is True
    accepted = raw.get("empty_payload_accepted") is True
    # Even malformed helper output cannot claim TLS success without all witnesses.
    if status == "PASS" and not (
        certificate_verified and accepted and code == 200 and mode == "VERIFIED_HTTPS_ATTEMPT"
    ):
        status, reason = "UNKNOWN", "BACKEND_PROBE_INVALID"
    return {
        "status": status if status in _STATUSES else "UNKNOWN",
        "mode": mode
        if mode in {"UNVERIFIED", "VERIFIED_HTTPS_ATTEMPT", "LEGACY_PRIVATE_LOOPBACK_TCP_ONLY"}
        else "UNVERIFIED",
        "reason_code": reason if reason in _REASONS else "BACKEND_PROBE_INVALID",
        "certificate_verified": certificate_verified,
        "empty_payload_accepted": accepted,
        "socket_accepting": raw.get("socket_accepting") if type(raw.get("socket_accepting")) is bool else None,
        "response_code": code if type(code) is int and 100 <= code <= 599 else None,
        "evidence_scope": "OTLP_RECEIVER_ACCEPTANCE_ONLY_NO_SPAN_PERSISTENCE_OR_EXPORT_PROOF",
        "plaintext_http_requests": 0,
    }


def run_probes(*, runner=_run, otel_https_endpoint=EXPECTED_HTTPS_ENDPOINT):
    endpoint = _validate_https_endpoint(otel_https_endpoint)
    names = (OTEL, *TUNNELS)
    found = {}
    try:
        inspection = runner(["docker", "inspect", *names], timeout=15)
        if inspection.returncode == 0:
            for item in json.loads(inspection.stdout):
                if isinstance(item, dict) and isinstance(item.get("Name"), str) and item["Name"].lstrip("/") in names:
                    found[item["Name"].lstrip("/")] = _metadata(item)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        pass
    services = []
    for name in names:
        metadata = found.get(name)
        service = {
            "name": name,
            "status": "UNKNOWN",
            "reason_code": "DOCKER_METADATA_UNAVAILABLE",
            "metadata": metadata,
        }
        if metadata is None:
            services.append(service)
            continue
        if metadata["state"] != "running":
            service.update(status="FAIL", reason_code="CONTAINER_NOT_RUNNING")
            services.append(service)
            continue
        if name in TUNNELS:
            try:
                logs = runner(
                    [
                        "docker",
                        "logs",
                        "--timestamps",
                        "--since",
                        metadata["started_at_utc"] or "0s",
                        "--tail",
                        "300",
                        name,
                    ],
                    timeout=15,
                )
                if logs.returncode != 0:
                    raise ValueError()
                readiness = parse_tunnel_readiness(logs.stdout + "\n" + logs.stderr, metadata["started_at_utc"])
                service.update(status=readiness["status"], reason_code=readiness["reason_code"], readiness=readiness)
            except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                service.update(reason_code="TUNNEL_LOGS_UNAVAILABLE")
        else:
            try:
                probe = runner(
                    ["docker", "exec", "-i", BACKEND, "python", "-B", "-"],
                    input="EXPECTED_ENDPOINT=" + repr(endpoint) + "\n" + OTEL_PROBE,
                    timeout=15,
                )
                if probe.returncode != 0:
                    raise ValueError()
                readiness = _safe_otlp_result(json.loads(probe.stdout))
                service.update(status=readiness["status"], reason_code=readiness["reason_code"], readiness=readiness)
            except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                service.update(reason_code="BACKEND_PROBE_UNAVAILABLE")
        services.append(service)
    statuses = {service["status"] for service in services}
    overall = "FAIL" if "FAIL" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "PASS"
    return {
        "schema": "orqevia.shell-less-service-probes.v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "services": services,
        "scope": "ON_DEMAND_PROCESS_AND_BOUNDED_READINESS_EVIDENCE_NOT_FULL_ESTATE_ACCEPTANCE",
        "raw_logs_exported": False,
        "environment_values_exported": False,
        "plaintext_http_requests": 0,
        "service_restarts": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New receipt file; an existing file is never overwritten.")
    parser.add_argument("--otel-https-endpoint", default=EXPECTED_HTTPS_ENDPOINT)
    args = parser.parse_args()
    try:
        result = run_probes(otel_https_endpoint=args.otel_https_endpoint)
    except ValueError:
        parser.error("Expected a credential-free private HTTPS OTLP origin on port 4318")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(json.dumps(result))
    return 1 if result["overall"] == "FAIL" else 2 if result["overall"] == "UNKNOWN" else 0


if __name__ == "__main__":
    raise SystemExit(main())
