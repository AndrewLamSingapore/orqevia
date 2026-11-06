# ORQEVIA acceleration decision - 29 October 2026

Mission ORQEVIA-CPP-ACCELERATION-20261028. Candidate only. Production unchanged.

## 1. Executive verdict

Retain the Python control plane. No custom C++ module is justified by the measured
fixtures. The already installed NumPy backend removes the large matrix bottleneck
with less build and maintenance cost. Two exact Python algorithm improvements
also pass the provisional 20% affected-workload threshold. These are source
candidates for controlled release consideration, not production acceptance.

Main was fetched and pinned at f37673b4ce618cc7cd672c987594f849d9985f02.
Read README, STATUS, AGENTS, CHANNEL_CONTRACT, operational manifest and the dated
27 October handover. Current ABEX doctrine overrides dated always-largest and
background-resume statements. Existing worktrees, services, records and pause stay.

## 2. Top five measured opportunities

| Rank | Workload / actual source | Finding | Decision |
|---|---|---|---|
| 1 | Wider PIF forecasts, app/pif/core.py and service.py | 24/48-state persisted fixture service improves on Windows and Linux using existing NumPy | ACCEPT candidate; flag off pending release |
| 2 | Stationary analysis, core.py | Redundant reachability passes after all states are reached; exact early termination | ACCEPT Python candidate |
| 3 | Seeded Monte Carlo, core.py | Repeated identical cumulative-weight preparation; cache visited transition rows | ACCEPT Python candidate |
| 4 | Historical journal, interface_telemetry.agent_activity | Current live SQL already bounds Python decoding; 6,965 rows, all 21 roles returned | Retain current implementation; monitor history growth |
| 5 | Serialization/integrity and MEL wrappers | JSON/SHA use existing native libraries; ONNX/tokenizers/NumPy already implement the numerical kernels | REJECT speculative custom replacements |

Ranks 1-3 have before/after measurements below. Rank 4 has a live read-only timing,
not a new speedup claim. Rank 5 has component microbenchmarks/source findings,
not evidence of an important production hotspot. Task-frequency telemetry and
whole HTTP/API mission speedup remain unverified.

## 3. Bottlenecks and root causes

Wide pure-Python matrix squaring is CPU-bound. The existing implementation already
uses exponentiation by squaring, so comparison uses that optimized algorithm,
not a deliberately slow horizon loop. Eight-state operational models spend most
service latency in registry serialization, loading and SQLite prediction receipts.
No eight-state acceleration claim is supported. Storage/persistence remains in
both service variants and every forecast retains SHADOW/no-authority semantics.

Stationary reachability performed size passes even after full reachability.
Simulation reconstructed the same CDF for every transition. Early exit and lazy
CDF reuse remove this repeated work without changing solvers or RNG calls.

The October 27 journal warning is dated evidence. Current read-only inspection
found the SQL CTE fix loaded in the interface. Its plan still scans metadata and
uses temporary group/ranking indexes; Python decodes bounded candidates, not all
historical tasks. It is algorithm/query work, not a demonstrated C++ opportunity.
No history was removed and no index or live database was changed.

## 4. Modules implemented

No C++20/CMake/pybind11 module, compiler installation, new model kernel, scheduler,
worker service, container or GPU dependency was added. app/pif/numpy_backend.py
is a small optional Python adapter to existing native NumPy operations. It is
entered only with ORQEVIA_PIF_NUMPY_ENABLED=1, at least 24 states and horizon>=2.
Missing NumPy or a numerical validation error falls back to the original Python
forecast. Default is off; the actual eight-state queue model always stays Python.
PIF and MEL retain their independent controls. Source also adds exact Python
reachability early exits and CDF caching. No other interface or model policy changes.

## 5. Baseline versus optimized measurements

Times below are medians in milliseconds, Python 3.12.15, same ABEX hardware,
3 warmups +21 samples per variant. Forecast figures include the actual PIFService
registry/load/forecast/prediction-persistence path in temporary SQLite; HTTP,
TLS and authentication are outside the measured boundary. Synthetic dense
fixtures at 8/24/48 states use horizons16/64/256 respectively.

| Case | Windows baseline ms | Windows candidate ms | Reduction | Linux baseline ms | Linux candidate ms | Reduction |
|---|---:|---:|---:|---:|---:|---:|
| forecast_service_8 | 10.166 | 10.893 | -7.2% | 15.104 | 15.061 | 0.3% |
| forecast_service_24 | 19.239 | 11.870 | 38.3% | 24.663 | 18.942 | 23.2% |
| forecast_service_48 | 77.884 | 17.659 | 77.3% | 82.923 | 25.350 | 69.4% |
| stationary_16 | 3.669 | 0.468 | 87.2% | 3.455 | 0.500 | 85.5% |
| simulation_8x32x100 | 2.798 | 1.951 | 30.3% | 3.211 | 2.242 | 30.2% |

Raw sample times, p95, variance, operations/s, process CPU-seconds, CPU core
equivalents and sampled RSS/headroom are in the evidence JSON. Earlier repeated
runs are preserved privately in ABEX reports; all repeated run-level 24/48-state service median
comparisons exceeded20% reduction, while the eight-state result varied around zero.
Do not promote submillisecond kernel ratios into whole-product throughput.

The pinned Linux baseline's NumPy forecast method is under1% of its persisted
service median. An ideal zero-time custom math kernel could therefore save
under1% versus that existing-library path (Amdahl upper-bound inference, not a
measured C++ result). Custom C++ latency, pybind overhead and native deployment
cost are NOT MEASURED. No C++ benchmark or speedup is fabricated.

## 6. Correctness and regression results

129 focused tests plus two additional numerical edge tests passed on Windows Python3.12.15: PIF, acceleration boundaries,
MEL and interface telemetry/counts. The earlier Python3.13 PIF/MEL run passed105;
Python3.13 is supplementary evidence outside the declared repository range.
New checks preserve exact seeded trajectories and Wilson intervals; independent
forecast comparisons require absolute/relative tolerance1e-12 (stricter than the
existing distribution contract1e-10). Existing singular/reducible/absorbing,
unsupported evidence, tenant isolation and disabled-layer tests remain intact.
Linux fixture comparisons also assert exact simulation/stationary results and
forecast deviations<1e-12. No production quality or 21-role competence claim.

## 7. Hardware and memory implications

ABEX Ryzen7 PRO8840HS,8physical/16logical,32GiB installed RAM. Docker VM15.29GiB.
Radeon780M is present, but no /dev/dxg in the current inference container; no GPU
speedup is assumed. Host and container toolchain probes found no supported C++
compiler/CMake/Ninja in PATH; no extra toolchain was installed for a rejected
custom-native candidate. Windows Python3.12.15 and LinuxPython3.12.15 were tested.

All benchmarks scope BLAS/OMP/MKL to1thread and affinity to2logical CPUs where
supported, then exit. They never alter system power modes, thermal limits or
production process affinity. JSON records sampled process RSS peaks (10ms
sampling; not an allocator/high-water proof) and available memory. Linux process
RSS stayed below44MiB in the final comparisons. Thermal/VRAM telemetry is
unavailable; no temperature, energy or GPU performance benefit is claimed.
Fresh-process import measurements (n7 per backend) explicitly expose NumPy's
startup and RSS cost; warmed service gains do not remove that cost. Optional
acceleration is suitable for repeated wide calculations, not every small call.

## 8. Security and operational risk

No credentials, model weights, model/provider policies, evidence classifications,
HTTP interfaces or durable production records changed. Existing 21 identities
and one coordinator are preserved. Numerical order differs under NumPy; validate
new domains and very large/ill-conditioned models separately. BLAS thread counts
must be qualified for the deployment, not copied from a benchmark assumption.
No independent authorization or orchestration authority is introduced.

The Linux harness extracts only this pinned fixture package into its own new
/tmp directory, runs a short child process in the existing backend and cleans
only that temporary directory. It never mounts/writes a production DB or image.
No new service, container, queue or excluded project is activated.

## 9. Deployment readiness

ACCEPT: exact Python CDF/reachability source candidates, and optional NumPy adapter
for these repeated wide fixture service workloads. This means suitable for
controlled release consideration only. HOLD: production feature activation,
whole HTTP end-to-end benefit, other model sizes/domains, larger matrices and
production quality/frequency evidence. REJECT: bespoke C++ forecast replacement
at this time, replacing ONNX/native inference kernels, or a second orchestrator.
The established Owner pause remains generation0; no release/merge/deploy occurred.

## 10. Next action, rollback and evidence classification

Review the candidate branch codex/cpp-acceleration-20261029 and normal repository CI.
Before release, qualify realistic wide-model usage and first-request overhead;
leave the flag off when the domain uses only eight states. Deployment needs its
existing release authorization. Set ORQEVIA_PIF_NUMPY_ENABLED=0 or remove it to
restore the existing forecast path; the prior source/image remains the rollback
for the exact Python changes. Never replace live containers to run this report.

Measured: fixture latencies/correctness, Python3.12 cross-platform results and
live journal metadata timings. Source findings: service architecture, model
policies, existing native libraries and mature inference paths. Hypothesis:
wide-model production demand could benefit; not yet traffic-profiled. Inference:
Amdahl bound against existing NumPy. Unverified: production gain, thermal/GPU
benefit, C++ comparisons, production acceptance and deployment qualification.

See BENCHMARKS.md and RECONNAISSANCE.md. Exact post-commit SHA, PR and command
receipts are retained in ABEX reports/cpp-acceleration-20261029/CUSTODY.json.
