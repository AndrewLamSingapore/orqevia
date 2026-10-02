"""Bounded local-only Ollama parallelism probe; never changes server settings."""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import re
import time
import urllib.request


def request(base_url: str, model: str, start_at: float, timeout: int, context: int = 8192,
            sequence_max: int = 20) -> dict:
    if sequence_max not in (20, 50):
        raise ValueError("unsupported deterministic sequence length")
    prompt = f"Write only the integers 1 through {sequence_max} in order, separated by spaces. No prose."
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": True, "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": (64 if sequence_max == 20 else 160), "num_ctx": context},
    }).encode()
    queued = time.perf_counter()
    delay = start_at - queued
    if delay > 0:
        time.sleep(delay)
    started = time.perf_counter()
    first = None
    final = None
    chunks = []
    try:
        req = urllib.request.Request(base_url + "/api/generate", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for line in response:
                if not line.strip():
                    continue
                frame = json.loads(line)
                if frame.get("response"):
                    if first is None:
                        first = time.perf_counter()
                    chunks.append(frame["response"])
                if frame.get("done"):
                    final = frame
                    break
        ended = time.perf_counter()
        answer = "".join(chunks)
        return {
            "ok": final is not None and re.findall(r"\d+", answer) == [str(i) for i in range(1, sequence_max + 1)],
            "start_s": started, "first_token_s": first, "end_s": ended,
            "ttft_s": None if first is None else first - started,
            "wall_s": ended - started,
            "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
            "eval_count": None if final is None else final.get("eval_count"),
            "eval_duration_ns": None if final is None else final.get("eval_duration"),
            "generation_tokens_per_s": (final.get("eval_count", 0) / (final.get("eval_duration", 0) / 1e9)
                                        if final and final.get("eval_duration") else None),
            "load_duration_ns": None if final is None else final.get("load_duration"),
            "prompt_eval_duration_ns": None if final is None else final.get("prompt_eval_duration"),
        }
    except Exception as exc:
        return {"ok": False, "start_s": started, "end_s": time.perf_counter(),
                "error_type": type(exc).__name__}


def run(base_url: str, model: str, width: int, timeout: int, count: int = 5,
        context: int = 8192) -> dict:
    if width not in (1, 2, 3, 4, 6, 8):
        raise ValueError("unsupported width")
    if count not in (5, 8):
        raise ValueError("unsupported request count")
    if context not in (1024, 8192):
        raise ValueError("unsupported context")
    # Keep request count fixed across configurations being compared.
    begin = time.perf_counter()
    launch = begin + 0.1
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(request, base_url, model, launch, timeout, context) for _ in range(count)]
        rows = [future.result() for future in futures]
    end = time.perf_counter()
    good = [row for row in rows if row["ok"]]
    tokens = sum(row.get("eval_count") or 0 for row in good)
    individual_rates = [row["generation_tokens_per_s"] for row in good
                        if row.get("generation_tokens_per_s") is not None]
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "configured_parallel": width,
        "parallel_label_only": True,
        "backend_parallel_verified_by_harness": False,
        "fixed_request_count": count,
        "model": model,
        "context_tokens": context,
        "all_correct": len(good) == count,
        "failures": count - len(good),
        "workload_wall_s": end - begin,
        "aggregate_output_tokens_per_wall_s": tokens / (end - begin),
        "mean_individual_generation_tokens_per_s": (sum(individual_rates) / len(individual_rates)
                                                    if individual_rates else None),
        "requests": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:11435")
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--requests", type=int, choices=(5, 8), default=5)
    parser.add_argument("--context", type=int, choices=(1024, 8192), default=8192)
    args = parser.parse_args()
    if args.url != "http://127.0.0.1:11435":
        parser.error("only the isolated loopback endpoint is accepted")
    print(json.dumps(run(args.url, args.model, args.width, args.timeout, args.requests,
                         args.context), indent=2))
