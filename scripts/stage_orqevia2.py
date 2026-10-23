"""Create an isolated local stage. Production containers and data are never changed.

Credentials and the stage TLS private key stay in an owner-restricted directory
outside Git. The generated Compose file must not be published or printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
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
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    PRIVATE.mkdir(parents=True, exist_ok=True)
    # Native Windows ACLs protect all descendants before any secret is written.
    acl_script = "$p=$env:ORQEVIA_STAGE_PRIVATE;$acl=New-Object Security.AccessControl.DirectorySecurity;$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;$acl.SetOwner($sid);$acl.SetAccessRuleProtection($true,$false);foreach($s in @($sid.Value,'S-1-5-18')){$r=New-Object Security.AccessControl.FileSystemAccessRule($s,'FullControl','ContainerInherit,ObjectInherit','None','Allow');$acl.AddAccessRule($r)};Set-Acl -LiteralPath $p -AclObject $acl"
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
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ORQEVIA isolated staging 20261023")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=14))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (PRIVATE / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (PRIVATE / "server.crt").write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM)
    )
    (PRIVATE / "server.key").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    # The CA signing key is deliberately not persisted; this stage cannot issue more certificates.
    pin = hashlib.sha256(
        key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
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
        "ORQEVIA_PWA_ORIGIN": "https://localhost:9443",
        "ORQEVIA_HARNESS_SIGNING_SECRET": secrets.token_urlsafe(40),
        "ORQEVIA_HARNESS_DB": "/data/action-harness.db",
        "ORQEVIA_MODEL_KEEP_ALIVE": "2m",
        "ORQEVIA_PUBLIC_AGENT_TRACE": "0",
        "ORQEVIA_HIGGSFIELD_ENABLED": "0",
    }
    interface_env = {
        **common,
        "ORQEVIA_PWA_ORIGIN": "https://localhost:9443",
        "ORQEVIA_PWA_DATA_CLASSIFICATION": "LOCAL_ONLY",
        "ORQEVIA_PWA_MAX_COST_USD": "0",
        "ORQEVIA_BACKEND_BASE_URL": "http://backend:8000",
        "ORQEVIA_INTERFACE_HOST_ID": "ABEX-OSIP-ISOLATED-STAGE",
        "ORQEVIA_INTERFACE_SPKI_SHA256": pin,
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
                bind(PRIVATE / "server.key", "/tls/server.key"),
                bind(PRIVATE / "server.crt", "/tls/server.crt"),
            ],
            "ports": ["127.0.0.1:9443:8443"],
            "mem_limit": "768m",
        },
        "ollama": {
            "image": inspect("orqevia-epoch-20261016-ollama-1")["Image"],
            "environment": {
                "OLLAMA_HOST": "0.0.0.0:11434",
                "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "OLLAMA_CONTEXT_LENGTH": "8192",
                "OLLAMA_KEEP_ALIVE": "2m",
            },
            "volumes": [{"type": "volume", "source": "models", "target": "/root/.ollama", "read_only": True}],
            "mem_limit": "8g",
            "networks": {"default": {"aliases": ["host.docker.internal"]}},
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
            "network_mode": "service:ollama",
        },
    }
    for service in services.values():
        service["restart"] = "no"
        service["logging"] = {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}}
    compose = {
        "name": PROJECT,
        "services": services,
        "volumes": {
            "data": {"name": PROJECT + "-data"},
            "models": {"external": True, "name": "orqevia-epoch-20261016-ollama"},
        },
        "networks": {"default": {"internal": True}},
    }
    destination.write_text(json.dumps(compose, indent=2) + "\n", encoding="utf-8")
    (PRIVATE / "stage-identity.json").write_text(
        json.dumps(
            {
                "project": PROJECT,
                "source_revision": revision,
                "origin": "https://localhost:9443",
                "baseline_image": BASELINE,
                "private_configuration": str(destination),
                "ca_sha256": hashlib.sha256((PRIVATE / "ca.crt").read_bytes()).hexdigest(),
                "onnx_sha256": model_digest,
            },
            indent=2,
        )
        + "\n"
    )
    run(
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "Import-Certificate -FilePath $env:ORQEVIA_STAGE_CA -CertStoreLocation Cert:\CurrentUser\Root | Out-Null",
        env={**os.environ, "ORQEVIA_STAGE_CA": str(PRIVATE / "ca.crt")},
        capture_output=True,
    )
    print(
        json.dumps(
            {
                "prepared": True,
                "project": PROJECT,
                "origin": "https://localhost:9443",
                "source_revision": revision,
                "production_configuration_changed": False,
                "cloud_providers_enabled": False,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "build", "up", "stop", "status"])
    args = parser.parse_args()
    if args.action == "prepare":
        return prepare()
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
