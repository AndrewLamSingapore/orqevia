"""Bounded, read-only time series. Does not submit, cancel or restart work.

Prompts/results and environment values are never exported. CPU-seconds come
from the Ollama cgroup counter; job status does not prove inference ownership.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import math
from pathlib import Path
import ssl
import statistics
import subprocess
import time
import urllib.request


BACKEND = "orqevia-epoch-20261016-backend-1"
OLLAMA = "orqevia-epoch-20261016-ollama-1"
PROBE = r"""
import collections,datetime,hashlib,json,pathlib,sqlite3,urllib.request
from app.settings import SETTINGS
now=datetime.datetime.now(datetime.timezone.utc)
with sqlite3.connect('file:/data/compute-queue.db?mode=ro',uri=True,timeout=3) as db:
 db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
 cols={r[1] for r in db.execute('PRAGMA table_info(compute_jobs)')}
 active=[]
 for r in db.execute("SELECT * FROM compute_jobs WHERE status IN ('running','queued')"):
  d=dict(r);prompt=d.get('prompt') or ''
  receipt={}
  try:receipt=json.loads(d.get('inference_receipt') or '{}')
  except (ValueError,TypeError):pass
  active.append({**{k:d.get(k) for k in ('id','agent','provider','model','model_role','task_class','priority','status','created_at','started_at','timeout_seconds','attempts','lifecycle_state')},
    'prompt_chars':len(prompt),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
    'purpose_markers':{k:k.lower() in prompt.lower() for k in ('coaching','independent','acceptance','baseline','forecast','architecture','cost','strategy')},
    'receipt_options':receipt.get('effective_options'),
    'receipt_present':bool(receipt)})
 recent=[]
 for r in db.execute("SELECT * FROM compute_jobs WHERE status IN ('completed','failed','cancelled') ORDER BY completed_at DESC LIMIT 30"):
  d=dict(r);started=d.get('started_at');ended=d.get('completed_at')
  duration=(datetime.datetime.fromisoformat(ended)-datetime.datetime.fromisoformat(started)).total_seconds() if started and ended else None
  receipt={}
  try:receipt=json.loads(d.get('inference_receipt') or '{}')
  except (ValueError,TypeError):pass
  recent.append({**{k:d.get(k) for k in ('id','agent','model','status','error','input_tokens','output_tokens','started_at','completed_at','timeout_seconds')},
    'application_elapsed_seconds':duration,'prompt_chars':len(d.get('prompt') or ''),
    'receipt_options':receipt.get('effective_options'),
    'prompt_sha256':hashlib.sha256((d.get('prompt') or '').encode()).hexdigest()})
 result={'active_application_jobs':active,'recent_jobs':recent,
    'shared_slot_columns_present':{'local_inflight','lifecycle_state'}<=cols}
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='compute_background_admission'").fetchone():
  row=db.execute('SELECT * FROM compute_background_admission WHERE id=1').fetchone()
  result['background_admission']=dict(row) if row else {'paused':True,'status':'UNKNOWN_FAIL_CLOSED'}
  result['background_admission_holds']=[dict(r) for r in db.execute('SELECT * FROM compute_background_admission_holds ORDER BY last_held_at DESC LIMIT 64')]
 result['coaching_pause_marker_present']=pathlib.Path('/data/coaching.pause').exists()
mem={}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
 k,_,v=line.partition(':')
 if k in ('MemTotal','MemAvailable','SwapTotal','SwapFree','SwapCached','Cached','AnonPages','Dirty'):mem[k]=int(v.split()[0])*1024
vm={}
for line in pathlib.Path('/proc/vmstat').read_text().splitlines():
 k,v=line.split()
 if k in ('pswpin','pswpout','pgmajfault'):vm[k]=int(v)
result.update(linux_memory_bytes=mem,vm_counters=vm,
 gpu_devices={p:pathlib.Path(p).exists() for p in ('/dev/dxg','/dev/dri','/dev/kfd')},
 actual_request_mission_binding='UNINSTRUMENTED_APPLICATION_CANDIDATES_ONLY',
 settings={k:getattr(SETTINGS,k) for k in ('compute_profile','context_tokens','max_output_tokens','keep_alive','fast_model','deep_model','embedding_model')})
try:
 with urllib.request.urlopen(SETTINGS.ollama_base_url+'/api/ps',timeout=5) as r:
  data=json.load(r)
 result['resident_models']=[{k:m.get(k) for k in ('name','digest','size','size_vram','context_length','expires_at','details')} for m in data.get('models',[])]
except (OSError,ValueError):result['resident_models']=None
print(json.dumps(result))
"""
CGROUP_PATHS = (
    "cpu.stat",
    "cpu.max",
    "memory.current",
    "memory.peak",
    "memory.swap.current",
    "memory.stat",
    "memory.events",
    "memory.pressure",
    "cpu.pressure",
    "io.stat",
)


def command(args, *, stdin=None):
    result = subprocess.run(
        args, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25
    )
    if result.returncode:
        raise RuntimeError("Read-only probe failed: " + args[1])
    return result.stdout


def parse_cgroup(raw):
    result = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key] = value.replace("|", "\n").strip()
    for key in ("cpu.stat", "memory.stat", "memory.events"):
        result[key] = {k: int(v) for k, v in (line.split() for line in result.get(key, "").splitlines())}
    for key in ("memory.current", "memory.peak", "memory.swap.current"):
        result[key] = int(result[key]) if result.get(key, "").isdigit() else None
    return result


def host_memory():
    if not hasattr(ctypes, "windll"):
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "physical_total",
                "physical_available",
                "pagefile_total",
                "pagefile_available",
                "virtual_total",
                "virtual_available",
                "extended_available",
            )
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return {
        "physical_total_bytes": status.physical_total,
        "physical_available_bytes": status.physical_available,
        "load_percent": status.load,
    }


def sample(*, ca_file=None):
    start = time.monotonic()
    journal = json.loads(command(["docker", "exec", "-i", BACKEND, "python", "-B", "-"], stdin=PROBE))
    paths = " ".join(CGROUP_PATHS)
    shell = (
        "for p in "
        + paths
        + '; do printf "%s=" "$p"; if test -r "/sys/fs/cgroup/$p"; then tr "\\n" "|" < "/sys/fs/cgroup/$p"; fi; printf "\\n"; done'
    )
    group = parse_cgroup(command(["docker", "exec", OLLAMA, "sh", "-c", shell]))
    https = None
    if ca_file:
        context = ssl.create_default_context(cafile=str(ca_file))
        began = time.monotonic()
        try:
            with urllib.request.urlopen(
                "https://localhost:8443/interface/v1/health", context=context, timeout=8
            ) as response:
                https = {"status": response.status, "seconds": time.monotonic() - began, "certificate_verified": True}
        except OSError as exc:
            https = {"status": "UNVERIFIED", "error_class": type(exc).__name__}
    return {
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "monotonic_seconds": time.monotonic(),
        "probe_seconds": time.monotonic() - start,
        "ollama_cgroup": group,
        "journal": journal,
        "host_memory": host_memory(),
        "https_health": https,
        "mutations": False,
    }


def summarize(samples):
    cpu = []
    swap = []
    for prior, current in zip(samples, samples[1:]):
        elapsed = current["monotonic_seconds"] - prior["monotonic_seconds"]
        delta = (
            current["ollama_cgroup"]["cpu.stat"]["usage_usec"] - prior["ollama_cgroup"]["cpu.stat"]["usage_usec"]
        ) / 1e6
        cpu.append({"seconds": elapsed, "cpu_seconds": delta, "cpu_percent": 100 * delta / elapsed})
        swap.append(
            {
                k: current["journal"]["vm_counters"][k] - prior["journal"]["vm_counters"][k]
                for k in ("pswpin", "pswpout", "pgmajfault")
            }
        )
    latency = [
        s["https_health"]["seconds"] for s in samples if s.get("https_health") and "seconds" in s["https_health"]
    ]
    jobs = {r["id"]: r for s in samples for r in s["journal"]["recent_jobs"]}

    def pct(values, p):
        return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None

    return {
        "sample_count": len(samples),
        "interval_count": len(cpu),
        "observation_seconds": samples[-1]["monotonic_seconds"] - samples[0]["monotonic_seconds"]
        if len(samples) > 1
        else 0,
        "ollama_cpu_seconds": sum(x["cpu_seconds"] for x in cpu),
        "mean_cpu_percent": 100 * sum(x["cpu_seconds"] for x in cpu) / sum(x["seconds"] for x in cpu) if cpu else None,
        "peak_sample_cpu_percent": max((x["cpu_percent"] for x in cpu), default=None),
        "peak_memory_current_bytes": max(s["ollama_cgroup"]["memory.current"] or 0 for s in samples),
        "peak_ollama_swap_bytes": max(s["ollama_cgroup"]["memory.swap.current"] or 0 for s in samples),
        "minimum_linux_available_bytes": min(s["journal"]["linux_memory_bytes"]["MemAvailable"] for s in samples),
        "linux_swap_in_pages": sum(x["pswpin"] for x in swap),
        "linux_swap_out_pages": sum(x["pswpout"] for x in swap),
        "https_health_p50_seconds": statistics.median(latency) if latency else None,
        "https_health_p95_seconds": pct(latency, 0.95),
        "recent_job_summary": list(jobs.values()),
        "cpu_intervals": cpu,
        "caveat": "PASSIVE_UNCONTROLLED_PRODUCTION_LOAD_NOT_A_THREAD_OR_MODEL_COMPARISON",
        "windows_gui_responsiveness": "NOT_MEASURED",
        "thermal_power_fan": "UNAVAILABLE",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 360 or not 1 <= args.interval <= 60:
        parser.error("Use bounded samples and intervals")
    samples = []
    for index in range(args.samples):
        began = time.monotonic()
        value = sample(ca_file=args.ca_file)
        samples.append(value)
        report = {"schema": "orqevia.ollama-load-observation.v1", "samples": samples, "summary": summarize(samples)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "sample": index + 1,
                    "utc": value["utc"],
                    "available_mib": round(value["journal"]["linux_memory_bytes"]["MemAvailable"] / 1048576, 1),
                    "ollama_cgroup_mib": round(value["ollama_cgroup"]["memory.current"] / 1048576, 1),
                    "active_application_jobs": len(value["journal"]["active_application_jobs"]),
                }
            ),
            flush=True,
        )
        if index + 1 < args.samples:
            time.sleep(max(0, args.interval - (time.monotonic() - began)))
    print(json.dumps({k: v for k, v in report["summary"].items() if k not in ("recent_job_summary", "cpu_intervals")}))


if __name__ == "__main__":
    main()
