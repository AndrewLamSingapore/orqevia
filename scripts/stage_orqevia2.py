"""Create an isolated local stage. Production containers and data are never changed.

Credentials and the stage TLS private key stay in an owner-restricted directory
outside Git. The generated Compose file must not be published or printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess

SOURCE = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ["LOCALAPPDATA"]) / "ORQEVIA/staging/orqevia2-20261023"
PROJECT = "orqevia2-stage-20261023"
BASELINE = "sha256:026ff681d12785aa9afd0b55787103d9b028abffe3e5428a96f57f7f38947481"


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, **kwargs)


def inspect(name):
    return json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]


def prepare():
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    PRIVATE.mkdir(parents=True, exist_ok=True)
    # Native Windows ACLs protect all descendants before any secret is written.
    acl_script = "$ErrorActionPreference='Stop';$p=$env:ORQEVIA_STAGE_PRIVATE;$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;& icacls.exe $p '/grant:r' ('*'+$sid+':(OI)(CI)(F)') '*S-1-5-18:(OI)(CI)(F)' | Out-Null;if($LASTEXITCODE -ne 0){throw 'Stage ACL grant failed'};& icacls.exe $p '/inheritance:r' | Out-Null;if($LASTEXITCODE -ne 0){throw 'Stage ACL inheritance restriction failed'}"
    run(
        "powershell.exe",
        "-NoProfile",
        "-Command",
        acl_script,
        env={**os.environ, "ORQEVIA_STAGE_PRIVATE": str(PRIVATE)},
        capture_output=True,
    )
    destination = PRIVATE / "compose.json"
    if destination.exists():
        raise SystemExit("Prepared stage already exists. Reuse its identity and data.")
    tls_sources = {
        m["Destination"]: m["Source"]
        for m in inspect("orqevia-epoch-20261016-interface-1")["Mounts"]
        if m["Destination"].startswith("/run/orqevia-tls/")
    }
    (PRIVATE / "ca.crt").write_bytes(Path(tls_sources["/run/orqevia-tls/ca.crt"]).read_bytes())
    leaf = x509.load_pem_x509_certificate(Path(tls_sources["/run/orqevia-tls/server.crt"]).read_bytes())
    if ipaddress.ip_address("192.168.1.23") not in leaf.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.IPAddress):
        raise SystemExit("Existing trusted LAN certificate does not cover the verified stage address")
    pin = hashlib.sha256(
        leaf.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    backend = inspect("orqevia-epoch-20261016-backend-1")
    mount = next(m for m in backend["Mounts"] if m["Destination"] == "/app/config/provider-catalog.active.json")
    catalog = json.loads(Path(mount["Source"]).read_text(encoding="utf-8-sig"))
    for model in catalog.get("models", []):
        if model.get("location") == "cloud":
            model["enabled"] = False
    (PRIVATE / "provider-catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    model_dir = Path.home() / "orqevia-ai/models/all-MiniLM-L6-v2-onnx-1110a243"
    if not (model_dir / "model.onnx").is_file():
        raise SystemExit("Existing pinned ONNX embedding model is unavailable; no replacement is downloaded.")
    model_digest = hashlib.sha256((model_dir / "model.onnx").read_bytes()).hexdigest()
    secret = secrets.token_urlsafe(40)
    owner = "orqevia2-isolated-acceptance-owner"
    common = {
        "ORQEVIA_SPINE_TOKEN": secret,
        "ORQEVIA_REGISTRY_V1_ENABLED": "1",
        "PRIME_REGISTRY_V1_ENABLED": "1",
        "ORQEVIA_NODE_ID": "ABEX-OSIP-ISOLATED-STAGE",
        "ORQEVIA_NODE_ROLE": "AUTHORITATIVE",
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": owner,
        "ORQEVIA_OPEN_ACCESS": "0",
        "ORQEVIA_PWA_ACCESS_MODE": "pairing",
        "ORQEVIA_DATA_DIR": "/data",
        "PRIME_DATA_DIR": "/data",
        "ORQEVIA_SPINE_DB": "/data/orqevia-spine.db",
        "ORQEVIA_RUNTIME_REVISION": revision,
        "PRIME_RUNTIME_REVISION": revision,
        "ORQEVIA_OTEL_ENABLED": "0",
        "ORQEVIA_INTERFACE_RUNTIME_REVISION": revision,
        "ORQEVIA_INTERFACE_CANDIDATE_STATUS": "ISOLATED_CANDIDATE",
        "ORQEVIA_FAST_MODEL": "gemma3:1b",
        "ORQEVIA_DEEP_MODEL": "gemma3:12b",
        "ORQEVIA_EVALUATOR_MODEL": "gemma3:12b",
        "ORQEVIA_EMBED_MODEL": "embeddinggemma:300m-qat-q4_0",
        "OLLAMA_BASE_URL": "http://ollama:11434",
    }
    backend_env = {
        **common,
        "ORQEVIA_PROVIDER_CATALOG": "/run/provider-catalog.json",
        "PRIME_PROVIDER_CATALOG": "/run/provider-catalog.json",
        "ORQEVIA_QUEUE_CONCURRENCY": "1",
        "ORQEVIA_AGENT_CONCURRENCY": "1",
        "ORQEVIA_LOCAL_RAM_MB": "8192",
        "ORQEVIA_LOCAL_VRAM_MB": "0",
        "ORQEVIA_CONTEXT_TOKENS": "8192",
        "ORQEVIA_MAX_OUTPUT_TOKENS": "512",
        "ORQEVIA_PWA_ORIGIN": "https://192.168.1.23:9443",
        "ORQEVIA_HARNESS_SIGNING_SECRET": secrets.token_urlsafe(40),
        "ORQEVIA_HARNESS_DB": "/data/action-harness.db",
        "ORQEVIA_MODEL_KEEP_ALIVE": "2m",
        "ORQEVIA_PUBLIC_AGENT_TRACE": "0",
        "ORQEVIA_OBSERVATION_POLLING": "1",
        "ORQEVIA_HIGGSFIELD_ENABLED": "0",
    }
    interface_env = {
        **common,
        "ORQEVIA_PWA_ORIGIN": "https://192.168.1.23:9443",
        "ORQEVIA_PWA_DATA_CLASSIFICATION": "LOCAL_ONLY",
        "ORQEVIA_PWA_MAX_COST_USD": "0",
        "ORQEVIA_BACKEND_BASE_URL": "http://backend:8000",
        "ORQEVIA_INTERFACE_HOST_ID": "ABEX-OSIP-ISOLATED-STAGE",
        "ORQEVIA_INTERFACE_SPKI_SHA256": pin,
        "ORQEVIA_INTERFACE_PUBLIC_KEY": base64.b64encode(
            leaf.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        ).decode(),
        "ORQEVIA_INTERFACE_RUNTIME_VERSION": "2.0-candidate",
    }

    def bind(source, target):
        return {"type": "bind", "source": str(source), "target": target, "read_only": True}

    data = {"type": "volume", "source": "data", "target": "/data"}
    image = "orqevia:osip-candidate-20261023"
    services = {
        "backend": {
            "image": image,
            "command": [
                "python",
                "-m",
                "uvicorn",
                "app.production_entry:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--no-proxy-headers",
            ],
            "environment": backend_env,
            "volumes": [data, bind(PRIVATE / "provider-catalog.json", "/run/provider-catalog.json")],
            "mem_limit": "2g",
            "networks": ["default", "frontend"],
        },
        "interface": {
            "image": image,
            "command": [
                "python",
                "-m",
                "uvicorn",
                "app.interface_server:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8443",
                "--no-proxy-headers",
                "--ssl-keyfile",
                "/tls/server.key",
                "--ssl-certfile",
                "/tls/server.crt",
            ],
            "environment": interface_env,
            "volumes": [
                data,
                bind(Path(tls_sources["/run/orqevia-tls/server.key"]), "/tls/server.key"),
                bind(Path(tls_sources["/run/orqevia-tls/server.crt"]), "/tls/server.crt"),
            ],
            "ports": ["192.168.1.23:9443:8443"],
            "mem_limit": "768m",
            "networks": ["default", "frontend"],
        },
        "ollama": {
            "image": image,
            "command": [
                "python",
                "-B",
                "-m",
                "uvicorn",
                "scripts.staging_model_proxy:app",
                "--host",
                "0.0.0.0",
                "--port",
                "11434",
                "--no-access-log",
                "--no-proxy-headers",
            ],
            "volumes": [bind(SOURCE / "scripts/staging_model_proxy.py", "/app/scripts/staging_model_proxy.py")],
            "mem_limit": "256m",
            "networks": {"default": {}, "shared_inference": {}},
        },
        "intelligence": {
            "image": inspect("orqevia-intelligence-1")["Image"],
            "command": [
                "python",
                "-B",
                "-m",
                "uvicorn",
                "app.orqevia.deployment:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8100",
                "--no-proxy-headers",
            ],
            "environment": {**common, "ORQEVIA_DATA_DIR": "/data/intelligence", "PRIME_SPINE_TOKEN": secret},
            "volumes": [data],
            "mem_limit": "1g",
        },
        "knowledge": {
            "image": "orqevia:osip-stage-knowledge-20261023",
            "environment": {
                "ORQEVIA_SERVICE_TOKEN": secret,
                "ORQEVIA_OWNER_ACCOUNT": owner,
                "ORQEVIA_LOCAL_AI_ROOT": "/data/knowledge",
                "ORQEVIA_LOCAL_RELEASE": revision,
                "ORQEVIA_LOCAL_GENERATION_MODEL": "gemma3:12b",
                "ORQEVIA_LOCAL_GENERATION_URL": "http://ollama:11434",
                "ORQEVIA_MINILM_BACKEND": "onnx",
                "ORQEVIA_MINILM_ONNX_DIR": "/model",
                "ORQEVIA_MINILM_ONNX_SHA256": model_digest,
                "ORQEVIA_MINILM_ONNX_THREADS": "2",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
                "ORQEVIA_OTEL_ENABLED": "0",
            },
            "volumes": [data, bind(model_dir, "/model")],
            "mem_limit": "1g",
            "networks": {"default": {"aliases": ["host.docker.internal"]}},
        },
    }
    for service in services.values():
        service["restart"] = "no"
        service["logging"] = {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}}
    nli = Path.home() / "orqevia-ai/models/nli-deberta-v3-base-standard-6c749ce3"
    if (nli / "model-manifest.json").is_file():
        services["knowledge"]["mem_limit"] = "3g"
        services["knowledge"]["cpus"] = 2
        services["knowledge"]["environment"]["ORQEVIA_NLI_MODEL_DIR"] = "/nli"
        services["knowledge"]["volumes"].append(bind(nli, "/nli"))
    compose = {
        "name": PROJECT,
        "services": services,
        "volumes": {
            "data": {"name": PROJECT + "-data"},
        },
        "networks": {
            "default": {"internal": True},
            "frontend": {},
            "shared_inference": {"external": True, "name": "orqevia-epoch-20261016_default"},
        },
    }
    destination.write_text(json.dumps(compose, indent=2) + "\n", encoding="utf-8")
    (PRIVATE / "stage-identity.json").write_text(
        json.dumps(
            {
                "project": PROJECT,
                "source_revision": revision,
                "origin": "https://192.168.1.23:9443",
                "baseline_image": BASELINE,
                "private_configuration": str(destination),
                "ca_sha256": hashlib.sha256((PRIVATE / "ca.crt").read_bytes()).hexdigest(),
                "onnx_sha256": model_digest,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "prepared": True,
                "project": PROJECT,
                "origin": "https://192.168.1.23:9443",
                "source_revision": revision,
                "production_configuration_changed": False,
                "cloud_providers_enabled": False,
            }
        )
    )


def refresh():
    """Upgrade this stage's wiring while retaining its credentials and database."""
    target = PRIVATE / "compose.json"
    compose = json.loads(target.read_text(encoding="utf-8"))
    if compose.get("name") != PROJECT or set(compose["services"]) != {
        "backend",
        "interface",
        "ollama",
        "knowledge",
        "intelligence",
    }:
        raise SystemExit("Unexpected stage configuration; no changes made")
    for name in compose["services"]:
        if inspect(PROJECT + "-" + name + "-1")["State"]["Running"]:
            raise SystemExit("Stop only this stage before refreshing its configuration")
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    services = compose["services"]
    for service in services.values():
        env = service.get("environment", {})
        for key in (
            "ORQEVIA_RUNTIME_REVISION",
            "PRIME_RUNTIME_REVISION",
            "ORQEVIA_INTERFACE_RUNTIME_REVISION",
            "ORQEVIA_LOCAL_RELEASE",
        ):
            if key in env:
                env[key] = revision
    for name in ("backend", "interface"):
        services[name]["environment"].update(
            {
                "ORQEVIA_REGISTRY_V1_ENABLED": "1",
                "PRIME_REGISTRY_V1_ENABLED": "1",
                "ORQEVIA_NODE_ID": "ABEX-OSIP-ISOLATED-STAGE",
                "ORQEVIA_NODE_ROLE": "AUTHORITATIVE",
            }
        )
    services["interface"]["networks"] = ["default", "frontend"]
    services["interface"]["ports"] = ["192.168.1.23:9443:8443"]
    production_env = dict(
        entry.split("=", 1) for entry in inspect("orqevia-epoch-20261016-interface-1")["Config"]["Env"]
    )
    public_key = production_env.get("ORQEVIA_INTERFACE_PUBLIC_KEY", "")
    if not public_key or "PRIVATE" in public_key:
        raise SystemExit("Verified public host identity is unavailable")
    services["interface"]["environment"]["ORQEVIA_INTERFACE_PUBLIC_KEY"] = public_key
    services["ollama"] = {
        "image": "orqevia:osip-candidate-20261023",
        "command": [
            "python",
            "-B",
            "-m",
            "uvicorn",
            "scripts.staging_model_proxy:app",
            "--host",
            "0.0.0.0",
            "--port",
            "11434",
            "--no-access-log",
            "--no-proxy-headers",
        ],
        "volumes": [
            {
                "type": "bind",
                "source": str(SOURCE / "scripts/staging_model_proxy.py"),
                "target": "/app/scripts/staging_model_proxy.py",
                "read_only": True,
            }
        ],
        "mem_limit": "256m",
        "restart": "no",
        "networks": {"default": {}, "shared_inference": {}},
        "logging": {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}},
    }
    services["knowledge"]["environment"]["ORQEVIA_LOCAL_GENERATION_MODEL"] = "gemma3:12b"
    services["knowledge"].pop("network_mode", None)
    services["knowledge"]["networks"] = {"default": {"aliases": ["host.docker.internal"]}}
    services["knowledge"]["environment"]["ORQEVIA_LOCAL_GENERATION_URL"] = "http://ollama:11434"
    services["backend"]["networks"] = ["default", "frontend"]
    services["backend"]["environment"]["ORQEVIA_OBSERVATION_POLLING"] = "1"
    nli = Path.home() / "orqevia-ai/models/nli-deberta-v3-base-standard-6c749ce3"
    if (nli / "model-manifest.json").is_file():
        services["knowledge"]["mem_limit"] = "3g"
        services["knowledge"]["cpus"] = 2
        services["knowledge"]["environment"]["ORQEVIA_NLI_MODEL_DIR"] = "/nli"
        services["knowledge"]["volumes"] = [v for v in services["knowledge"]["volumes"] if v["target"] != "/nli"]
        services["knowledge"]["volumes"].append(
            {"type": "bind", "source": str(nli), "target": "/nli", "read_only": True}
        )
    compose["volumes"].pop("models", None)
    compose["networks"] = {
        "default": {"internal": True},
        "frontend": {},
        "shared_inference": {"external": True, "name": "orqevia-epoch-20261016_default"},
    }
    backup = PRIVATE / ("compose.before-shared-inference-" + revision[:7] + ".json")
    if backup.exists():
        raise SystemExit("Refresh backup exists; inspect it before retrying")
    backup.write_bytes(target.read_bytes())
    target.write_text(json.dumps(compose, indent=2) + "\n", encoding="utf-8")
    identity_path = PRIVATE / "stage-identity.json"
    identity = json.loads(identity_path.read_text())
    identity.update(source_revision=revision, inference="EXISTING_LOCAL_MODEL_RUNTIME", production_data_mounted=False)
    identity_path.write_text(json.dumps(identity, indent=2) + "\n")
    print(
        json.dumps(
            {
                "refreshed": True,
                "project": PROJECT,
                "source_revision": revision,
                "shared_inference": True,
                "production_database_mounted": False,
                "stage_credentials_rotated": False,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "refresh", "build", "up", "stop", "status"])
    args = parser.parse_args()
    if args.action == "prepare":
        return prepare()
    if args.action == "refresh":
        return refresh()
    if args.action == "build":
        run("docker", "tag", BASELINE, "orqevia:baseline-98b2537-20261023")
        revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
        run(
            "docker",
            "build",
            "--pull=false",
            "-f",
            "deploy/Dockerfile.modernization",
            "--build-arg",
            "ORQEVIA_RUNTIME_REVISION=" + revision,
            "-t",
            "orqevia:osip-candidate-20261023",
            str(SOURCE),
            cwd=SOURCE,
        )
        return run(
            "docker",
            "build",
            "--pull=false",
            "-f",
            "deploy/Dockerfile.staging-knowledge",
            "-t",
            "orqevia:osip-stage-knowledge-20261023",
            str(SOURCE),
            cwd=SOURCE,
        )
    command = ["docker", "compose", "-f", str(PRIVATE / "compose.json"), "-p", PROJECT]
    if args.action == "up":
        return run(*command, "up", "-d", "--no-build", "--pull", "never")
    if args.action == "stop":
        return run(*command, "stop")
    return run(*command, "ps")


if __name__ == "__main__":
    main()
