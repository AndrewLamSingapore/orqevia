"""Benchmark local Ollama models without sending prompts off-device."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_TASKS = [
    {"category": "reasoning", "prompt": "A release has 12 checks and one fails. Explain why the release must remain blocked in three concise points.", "must_include": ["blocked"]},
    {"category": "coding", "prompt": "Return only a Python function named clamp that limits x between low and high.", "must_include": ["def clamp"]},
    {"category": "retrieval", "prompt": "Context: PRIME routes deterministic, local AI, confidence gate, frontier AI. Which stage follows local AI?", "must_include": ["confidence gate"]},
]


def request_json(url: str, payload: dict | None = None, timeout: int = 180) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--tasks", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-docker-internal", action="store_true")
    args = parser.parse_args()
    host = urllib.parse.urlsplit(args.base_url).hostname
    docker_internal = args.allow_docker_internal and host == "ollama" and Path("/.dockerenv").exists()
    if host not in {"127.0.0.1", "localhost", "::1"} and not docker_internal:
        raise SystemExit("benchmark endpoint must be loopback or the internal Ollama service from inside Docker")
    tasks = json.loads(args.tasks.read_text(encoding="utf-8")) if args.tasks else DEFAULT_TASKS
    available = [item["name"] for item in request_json(args.base_url.rstrip("/") + "/api/tags").get("models", [])]
    configured = []
    for key in ("PRIME_FAST_MODEL", "PRIME_DEEP_MODEL"):
        model = os.environ.get(key, "").strip()
        if model and model in available and model not in configured:
            configured.append(model)
    generation_models = [model for model in available if "embed" not in model.lower()]
    models = args.models or configured or generation_models
    if not models:
        raise SystemExit("no local models are available")
    privacy = "docker-internal-only" if docker_internal else "loopback-only"
    report = {"endpoint": args.base_url, "privacy": privacy, "offline_resilience": "network-independent endpoint", "models": []}
    for model in models:
        if model not in available:
            raise SystemExit(f"model is not installed locally: {model}")
        results = []
        for task in tasks:
            started = time.perf_counter()
            try:
                body = request_json(args.base_url.rstrip("/") + "/api/generate", {"model": model, "prompt": task["prompt"], "stream": False})
                answer = str(body.get("response", ""))
                required = [str(value).lower() for value in task.get("must_include", [])]
                result = {"category": task["category"], "passed": all(value in answer.lower() for value in required), "response_chars": len(answer)}
            except (urllib.error.URLError, TimeoutError) as error:
                result = {"category": task["category"], "passed": False, "response_chars": 0, "error": str(error)}
            result["latency_seconds"] = round(time.perf_counter() - started, 3)
            results.append(result)
        report["models"].append({"model": model, "pass_rate": sum(x["passed"] for x in results) / len(results), "median_latency_seconds": round(statistics.median(x["latency_seconds"] for x in results), 3), "tasks": results})
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
