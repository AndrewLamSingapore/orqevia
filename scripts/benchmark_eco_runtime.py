"""Sequential Owner-authorized synthetic tests; production pause stays intact.

Uses the existing compute database, model server and per-request options.
Never restarts services, installs models, resumes producers or calls a cloud.
Results qualify a candidate; they do not deploy an ECO production profile.
"""

from __future__ import annotations
import argparse
import ctypes
import datetime as dt
import json
from pathlib import Path
import statistics
import subprocess
import time

from scripts.observe_ollama_load import CGROUP_PATHS, OLLAMA, command, parse_cgroup


WORKER = r"""
import asyncio,dataclasses,datetime,inspect,json,math,sqlite3,sys,time,types,urllib.request
from app.compute_queue_api import queue,providers
from app.settings import SETTINGS
from app.compute_profile import require_compute_capacity
spec=SPEC
for name,source in SOURCES.items():
 module=types.ModuleType(name);module.__package__='app';sys.modules[name]=module
 exec(compile(source,name,'exec'),module.__dict__)
def paused(db):
 row=db.execute('SELECT paused FROM compute_background_admission WHERE id=1').fetchone()
 return row is not None and row[0]==1
with queue.connect() as db:
 if not paused(db):raise RuntimeError('OWNER_BACKGROUND_PAUSE_NOT_ACTIVE')
 if db.execute("SELECT 1 FROM compute_jobs WHERE status='running' OR cloud_inflight=1 LIMIT 1").fetchone():raise RuntimeError('EXISTING_WORK_ACTIVE')
job=queue.submit(agent='a19',prompt=spec['prompt'],priority='background',model=spec['model'],
 model_role=spec['role'],preferred_provider='ollama-'+spec['role'],task_class='classification' if spec['role']=='fast' else 'complex_reasoning',
 max_retries=0,timeout_seconds=180,max_cost_usd=0,allow_cloud=False,
 response_format='text' if spec['role']=='embedding' else 'strict_json',
 response_schema=spec.get('response_schema'))
claimed=None;began=time.monotonic();stages=[]
try:
 # The initial background submission cannot be stolen by the live reaper:
 # the Owner pause trigger holds it. Reserve only this explicit test as held
 # before admitting it at interactive priority. No global pause is released.
 with queue.connect() as db:
  db.execute('BEGIN IMMEDIATE')
  if not paused(db) or db.execute("SELECT 1 FROM compute_jobs WHERE status='running' OR cloud_inflight=1 LIMIT 1").fetchone():raise RuntimeError('EXISTING_WORK_ACTIVE')
  db.execute("UPDATE compute_jobs SET status='held',priority=50,lease_until=? WHERE id=? AND status='queued'",(time.time()+240,job['id']))
  queue._event(db,job['id'],'owner_qualification_reserved',{'purpose':'explicit-isolated-eco-test','threads':spec['threads'],'model':spec['model']})
 available=providers()
 claimed=queue.claim('owner-eco-qualification',available,held_job_id=job['id'])
 if not claimed:raise RuntimeError('OWNER_TEST_ADMISSION_UNAVAILABLE')
 provider=next(p for p in available if p.name==claimed['provider'])
 settings=dataclasses.replace(SETTINGS,context_tokens=spec['context'],max_output_tokens=128,keep_alive='2m')
 options={'num_thread':spec['threads'],'temperature':0,'seed':11}
 if spec['role']=='embedding':
  payload={'model':provider.model,'input':spec['inputs'],'keep_alive':'2m','options':options}
  req=urllib.request.Request(SETTINGS.ollama_base_url+'/api/embed',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=180) as response:raw=json.load(response)
  vectors=raw.get('embeddings',[])
  valid=len(vectors)==3 and len(vectors[0])>0 and all(len(v)==len(vectors[0]) and all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) for v in vectors)
  def cos(a,b):return sum(x*y for x,y in zip(a,b))/math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
  similarity=cos(vectors[0],vectors[1]) if valid else None
  quality=bool(valid and similarity>.999)
  result={'result':json.dumps({'vectors':len(vectors),'dimensions':len(vectors[0]) if vectors else 0,'identical_input_similarity':similarity}),
   'input_tokens':int(raw.get('prompt_eval_count',0)),'output_tokens':0,'actual_cost_usd':0}
  metrics={k:raw.get(k) for k in ('total_duration','load_duration','prompt_eval_count')}
 else:
  claimed['lifecycle_state']='ADMITTED'
  result=asyncio.run(sys.modules['app.eco_trial_stream'].infer(claimed,provider,settings=settings,
   capacity=require_compute_capacity,options=lambda:options,
   cancelled=lambda:queue.get(job['id'])['status']=='cancelled',
   stage=lambda phase:stages.append({'phase':phase,'elapsed_seconds':time.monotonic()-began})))
  metrics=result.get('timing_metrics',{})
  try:
   observed=json.loads(result['result']);expected=spec['expected']
   quality=not result.get('error') and type(observed) is dict and observed.keys()==expected.keys() and all(type(observed[k]) is type(v) and observed[k]==v for k,v in expected.items())
  except ValueError:quality=False
 allowed=set(inspect.signature(queue.finish).parameters)
 finished=queue.finish(job['id'],**{k:v for k,v in result.items() if k in allowed})
 with queue.connect() as db:
  if not paused(db):raise RuntimeError('OWNER_PAUSE_DRIFT_DETECTED')
 print(json.dumps({'job_id':job['id'],'job_status':finished['status'],'model':provider.model,
  'quality_pass':quality,'answer':result['result'],'input_tokens':result.get('input_tokens'),
  'output_tokens':result.get('output_tokens'),'timing':metrics,'stage_events':stages,
  'test_elapsed_seconds':time.monotonic()-began,'requested_threads':spec['threads'],
  'context_tokens':spec['context'],'keep_alive':'2m','production_background_pause_preserved':True}),flush=True)
except Exception:
 if claimed is None:queue.cancel(job['id'])
 else:
  try:queue.finish(job['id'],error='OWNER_QUALIFICATION_FAILED',retryable=False)
  except ValueError:pass
 raise
"""


def trial_spec(model, threads, role):
    if role == "fast":
        prompt = (
            "Owner-authorized synthetic model qualification. Classify the message as BUG, FEATURE, or QUESTION. "
            "Message: The export button crashes and no file is produced. Return only JSON with key category."
        )
        expected = {"category": "BUG"}
    else:
        prompt = (
            "Owner-authorized synthetic scheduling reasoning qualification. One nonpreemptive inference slot starts "
            "background B1 at time0 for40seconds. Interactive I1 arrives at time5 and needs10seconds. "
            "Background B2 arrives at time8 and needs20seconds. Interactive work has priority when the slot becomes free. "
            "Waiting does not consume an active execution budget. Return only JSON with integer keys "
            "i1_start, i1_finish, i1_wait, b2_start, b2_finish, b2_wait and boolean waiting_consumes_execution_budget."
        )
        expected = {
            "i1_start": 40,
            "i1_finish": 50,
            "i1_wait": 35,
            "b2_start": 50,
            "b2_finish": 70,
            "b2_wait": 42,
            "waiting_consumes_execution_budget": False,
        }
    result = {"model": model, "threads": threads, "role": role, "prompt": prompt, "expected": expected, "context": 8192}
    if role != "embedding":
        result["response_schema"] = {
            "type": "object",
            "properties": {
                key: (
                    {"type": "boolean"}
                    if type(value) is bool
                    else {"type": "integer"}
                    if type(value) is int
                    else {"type": "string"}
                )
                for key, value in expected.items()
            },
            "required": list(expected),
            "additionalProperties": False,
        }
    if role == "embedding":
        result.update(
            prompt="Owner-authorized synthetic embedding qualification",
            inputs=[
                "A cat rests beside the window.",
                "A cat rests beside the window.",
                "Industrial bolts and steel bearings.",
            ],
        )
    return result


def metrics():
    paths = " ".join(CGROUP_PATHS)
    shell = (
        "for p in "
        + paths
        + '; do printf "%s=" "$p"; if test -r "/sys/fs/cgroup/$p"; then tr "\\n" "|" < "/sys/fs/cgroup/$p"; fi; printf "\\n"; done'
    )
    value = parse_cgroup(command(["docker", "exec", OLLAMA, "sh", "-c", shell]))
    return {
        "monotonic": time.monotonic(),
        "cpu_usec": value["cpu.stat"]["usage_usec"],
        "memory_current": value["memory.current"],
        "swap_current": value["memory.swap.current"],
    }


def shell_responsiveness():
    """Noninteractive WM_NULL round trip, an Explorer proxy, not a GUI benchmark."""
    if not hasattr(ctypes, "windll"):
        return None
    from ctypes import wintypes

    api = ctypes.windll.user32
    api.GetShellWindow.restype = wintypes.HWND
    hwnd = api.GetShellWindow()
    if not hwnd:
        return None
    api.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    api.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    output = ctypes.c_size_t()
    began = time.monotonic()
    ok = api.SendMessageTimeoutW(hwnd, 0, 0, 0, 3, 200, ctypes.byref(output))
    return {"responsive": bool(ok), "milliseconds": (time.monotonic() - began) * 1000}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["fast", "deep", "embedding"], required=True)
    parser.add_argument("--threads", nargs="+", type=int, default=[8, 4, 6])
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 3 or any(t not in (4, 6, 8) for t in args.threads):
        parser.error("Use bounded measured candidates4/6/8 and1..3 repetitions")
    root = Path(__file__).resolve().parents[1]
    sources = {
        name: (root / path).read_text(encoding="utf-8")
        for name, path in [("app.home_eco", "app/home_eco.py"), ("app.eco_trial_stream", "app/direct_stream.py")]
    }
    model = {"fast": "gemma3:1b", "deep": "gemma3:12b", "embedding": "embeddinggemma:300m-qat-q4_0"}[args.role]
    trials = []
    candidates = [args.threads[0]] if args.role == "embedding" else args.threads
    for rep in range(args.repetitions):
        for threads in candidates:
            spec = trial_spec(model, threads, args.role)
            program = "SPEC=" + repr(spec) + "\nSOURCES=" + repr(sources) + "\n" + WORKER
            observations = [{**metrics(), "explorer": shell_responsiveness()}]
            began = time.monotonic()
            process = subprocess.Popen(
                ["docker", "exec", "-i", "orqevia-epoch-20261016-backend-1", "python", "-B", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            process.stdin.write(program)
            process.stdin.close()
            process.stdin = None
            while process.poll() is None:
                time.sleep(1)
                observations.append({**metrics(), "explorer": shell_responsiveness()})
            stdout, stderr = process.communicate()
            if process.returncode:
                args.output.write_text(
                    json.dumps(
                        {
                            "trials": trials,
                            "failed_trial": spec,
                            "error_class": "OWNER_TEST_EXECUTOR_FAILURE",
                            "diagnostic": stderr[-3000:],
                        },
                        indent=2,
                    )
                    + "\n"
                )
                raise SystemExit("Bounded test failed; production pause remains in place. See local artifact.")
            result = json.loads(stdout)
            intervals = []
            for a, b in zip(observations, observations[1:]):
                seconds = b["monotonic"] - a["monotonic"]
                cpu = (b["cpu_usec"] - a["cpu_usec"]) / 1e6
                intervals.append(100 * cpu / seconds)
            elapsed = observations[-1]["monotonic"] - observations[0]["monotonic"]
            cpu_seconds = (observations[-1]["cpu_usec"] - observations[0]["cpu_usec"]) / 1e6
            probes = [s["explorer"] for s in observations if s.get("explorer")]
            result.update(
                repetition=rep + 1,
                wall_seconds=time.monotonic() - began,
                cpu_seconds=cpu_seconds,
                mean_cpu_percent=100 * cpu_seconds / elapsed,
                peak_sample_cpu_percent=max(intervals, default=None),
                peak_cgroup_memory_bytes=max(s["memory_current"] for s in observations),
                explorer_message_p50_ms=statistics.median(p["milliseconds"] for p in probes) if probes else None,
                explorer_unresponsive_samples=sum(not p["responsive"] for p in probes),
                observations=observations,
            )
            trials.append(result)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    {
                        "schema": "orqevia.eco-qualification.v1",
                        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "profile_status": "ISOLATED_CANDIDATE_NOT_PRODUCTION_DEPLOYMENT",
                        "production_background_resumed": False,
                        "thread_count_enforcement": "REQUEST_OPTIONS_PLUS_MEASURED_OCCUPANCY_NOT_A_RUNNER_THREAD_COUNT_ATTESTATION",
                        "responsiveness_scope": "EXPLORER_WM_NULL_PROXY_NOT_ALL_WINDOWS_APPS",
                        "trials": trials,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "job_id",
                            "model",
                            "quality_pass",
                            "requested_threads",
                            "test_elapsed_seconds",
                            "cpu_seconds",
                            "mean_cpu_percent",
                            "peak_sample_cpu_percent",
                            "explorer_message_p50_ms",
                        )
                    }
                ),
                flush=True,
            )
            if not result["quality_pass"]:
                raise SystemExit("Quality gate failed; do not enable this routing candidate")


if __name__ == "__main__":
    main()
