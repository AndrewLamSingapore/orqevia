"""Benchmark local Ollama models without sending prompts off-device."""
from __future__ import annotations

import argparse
import json
import statistics
import time
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
    args = parser.parse_args()
    host = urllib.parse.urlsplit(args.base_url).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("benchmark endpoint must be loopback; prompts must remain private")
    tasks = json.loads(args.tasks.read_text(encoding="utf-8")) if args.tasks else DEFAULT_TASKS
    available = [item["name"] for item in request_json(args.base_url.rstrip("/") + "/api/tags").get("models", [])]
    models = args.models or available
    if not models:
        raise SystemExit("no local models are available")
    report = {"endpoint": args.base_url, "privacy": "loopback-only", "offline_resilience": "network-independent endpoint", "models": []}
    for model in models:
        if model not in available:
            raise SystemExit(f"model is not installed locally: {model}")
        results = []
        for task in tasks:
            started = time.perf_counter()
            body = request_json(args.base_url.rstrip("/") + "/api/generate", {"model": model, "prompt": task["prompt"], "stream": False})
            latency = time.perf_counter() - started
            answer = str(body.get("response", ""))
            required = [str(value).lower() for value in task.get("must_include", [])]
            results.append({"category": task["category"], "latency_seconds": round(latency, 3), "passed": all(value in answer.lower() for value in required), "response_chars": len(answer)})
        report["models"].append({"model": model, "pass_rate": sum(x["passed"] for x in results) / len(results), "median_latency_seconds": round(statistics.median(x["latency_seconds"] for x in results), 3), "tasks": results})
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
