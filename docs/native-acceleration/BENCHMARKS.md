# Reproduce the bounded investigation

Use repository Python3.12 with installed existing NumPy/psutil; no download is
required on ABEX. Start from fetched mainf37673b4 and the candidate branch.
Run heavy tests/benchmarks sequentially. No background resume is required.

```powershell
python benchmarks/native_acceleration/baseline.py --output <new-baseline-folder>
python benchmarks/native_acceleration/compare.py --output <new-comparison.json>
python benchmarks/native_acceleration/run_linux.py --output <new-linux-baseline.json>
python benchmarks/native_acceleration/run_linux.py --candidate --output <new-linux-comparison.json>
python -m pytest -q tests/test_pif.py tests/test_pif_acceleration.py tests/test_mel.py tests/test_interface_telemetry.py tests/test_interface_telemetry_counts.py
```

baseline.py uses the current imported source. For the original baseline, run it
at the pinned main revision or use run_linux.py without --candidate, which
packages Git's pinned original core. compare.py always loads that original core
from Git and compares it to the actual working candidate in the same process.
Temporary SQLite stores retain SHADOW, unvalidated fixture/no-authority fields.
The fixture package and database disappear after the run; evidence remains in
the explicitly selected new output JSON. The harness never calls a model.

For live journal profiling, feed journal_readonly.py to a disposable Python child
inside the existing interface; it opens existing databases with mode=ro and
exports counts, metadata-query plan, function SHA and timings only. It never
exports tasks, results, free-text errors, environment or tokens.

Statistics: nearest-rank p95, sample variance, median;21 samples after3warmups.
Startup uses7fresh Python children and includes process wall/import times and
RSS after imports. Process CPU-seconds and 10ms memory sampling are recorded;
short calls can finish between samples. CPU core-equivalents are CPU-seconds /
summed call-wall time, not whole-host CPU utilization. Thermal/GPU readings are
unavailable. No destructive stress tests or uncontrolled parallel workloads.

Raw evidence is in evidence/. These are synthetic domain fixtures, not traffic
frequency or forecast-quality qualification. Public reports contain no private
production row contents. File integrity manifest: evidence/SHA256SUMS.json.
