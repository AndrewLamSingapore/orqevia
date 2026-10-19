"""Benchmark local Ollama models without sending prompts off-device."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_TASKS = [
    {"category": "reasoning", "language": "en", "prompt": "A release has 12 checks and one fails. Explain why the release must remain blocked in three concise points.", "must_include": ["blocked"]},
    {"category": "coding", "language": "en", "prompt": "Return only a Python function named clamp that limits x between low and high.", "must_include": ["def clamp"]},
    {"category": "structured_output", "language": "en", "prompt": "Return only JSON with keys decision and reason. decision must be BLOCKED.", "must_be_json": True, "required_json_keys": ["decision", "reason"], "json_equals": {"decision": "BLOCKED"}},
    {"category": "chinese", "language": "zh", "prompt": "请用中文回答：你叫什么名字？你必须把自己称为 JARVIS。", "must_include": ["jarvis"], "must_contain_cjk": True},
    {"category": "english", "language": "en", "prompt": "What is your name? Answer in one English sentence and identify yourself as JARVIS.", "must_include": ["jarvis"]},
    {"category": "tool_selection", "language": "en", "prompt": "Return only the tool name memory.search for retrieving authorized local knowledge.", "must_include": ["memory.search"]},
    {"category": "retrieval", "language": "en", "prompt": "Context: PRIME routes deterministic, local AI, confidence gate, frontier AI. Which stage follows local AI?", "must_include": ["confidence gate"]},
    {"category": "verification", "language": "en", "prompt": "Verify this claim: 17 multiplied by 6 equals 92. State whether it is correct and give the correct product.", "must_include": ["102", "incorrect"]},
]

CJK = re.compile(r"[\u3400-\u9fff]")


def validate_tasks(tasks: object) -> list[dict]:
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("benchmark tasks must be a non-empty JSON array")
    required_categories = {"reasoning", "coding", "structured_output", "chinese", "english", "tool_selection", "retrieval", "verification"}
    categories: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise SystemExit(f"benchmark task {index} must be an object")
        category = task.get("category")
        prompt = task.get("prompt")
        if not isinstance(category, str) or not category.strip() or not isinstance(prompt, str) or not prompt.strip():
            raise SystemExit(f"benchmark task {index} requires non-empty category and prompt strings")
        if not any(task.get(key) for key in ("must_include", "must_exclude", "must_be_json", "must_contain_cjk")):
            raise SystemExit(f"benchmark task {index} requires at least one deterministic scoring assertion")
        categories.add(category)
    if tasks is DEFAULT_TASKS and categories != required_categories:
        raise SystemExit("built-in benchmark coverage is incomplete")
    return tasks


def score_answer(task: dict, answer: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    lowered = answer.lower()
    for value in task.get("must_include", []):
        if str(value).lower() not in lowered:
            failures.append(f"missing:{value}")
    for value in task.get("must_exclude", []):
        if str(value).lower() in lowered:
            failures.append(f"forbidden:{value}")
    if task.get("must_contain_cjk") and not CJK.search(answer):
        failures.append("missing:cjk")
    if task.get("must_be_json"):
        try:
            parsed = json.loads(answer)
        except json.JSONDecodeError:
            failures.append("invalid:json")
        else:
            if not isinstance(parsed, dict):
                failures.append("invalid:json_object")
            else:
                for key in task.get("required_json_keys", []):
                    if key not in parsed:
                        failures.append(f"missing_json_key:{key}")
                for key, expected in task.get("json_equals", {}).items():
                    if parsed.get(key) != expected:
                        failures.append(f"json_mismatch:{key}")
    return not failures, failures


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
    tasks = validate_tasks(json.loads(args.tasks.read_text(encoding="utf-8")) if args.tasks else DEFAULT_TASKS)
    available = [item["name"] for item in request_json(args.base_url.rstrip("/") + "/api/tags").get("models", [])]
    configured = []
    for key in ("ORQEVIA_FAST_MODEL", "ORQEVIA_DEEP_MODEL"):
        model = os.environ.get(key, "").strip()
        if model and model in available and model not in configured:
            configured.append(model)
    generation_models = [model for model in available if "embed" not in model.lower()]
    models = args.models or configured or generation_models
    if not models:
        raise SystemExit("no local models are available")
    privacy = "docker-internal-only" if docker_internal else "loopback-only"
    report = {
        "schema_version": "2.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoint": args.base_url,
        "privacy": privacy,
        "offline_resilience": "network-independent endpoint",
        "measurement_scope": {
            "response_content_persisted": False,
            "ollama_api_timing": True,
            "host_cpu": "not measured by this container-local harness",
            "host_ram": "not measured by this container-local harness",
        },
        "models": [],
    }
    for model in models:
        if model not in available:
            raise SystemExit(f"model is not installed locally: {model}")
        results = []
        for task in tasks:
            started = time.perf_counter()
            try:
                body = request_json(args.base_url.rstrip("/") + "/api/generate", {"model": model, "prompt": task["prompt"], "stream": False})
                answer = str(body.get("response", ""))
                passed, failures = score_answer(task, answer)
                eval_count = int(body.get("eval_count") or 0)
                eval_duration = int(body.get("eval_duration") or 0)
                result = {
                    "category": task["category"],
                    "language": task.get("language", "unspecified"),
                    "passed": passed,
                    "checks_failed": failures,
                    "response_chars": len(answer),
                    "prompt_tokens": int(body.get("prompt_eval_count") or 0),
                    "generated_tokens": eval_count,
                    "tokens_per_second": round(eval_count / (eval_duration / 1_000_000_000), 3) if eval_count and eval_duration else None,
                }
            except (urllib.error.URLError, TimeoutError) as error:
                result = {"category": task["category"], "language": task.get("language", "unspecified"), "passed": False, "response_chars": 0, "error_type": type(error).__name__}
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
