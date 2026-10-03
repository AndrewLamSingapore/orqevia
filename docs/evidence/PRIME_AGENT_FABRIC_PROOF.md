# PRIME agent fabric: bounded offline proof

Date: 2026-10-02 (SGT). Scope: isolated `prime-performance-20261002` worktree. This is source and fake-tool evidence, not a production receipt.

## Result

`tests/test_agent_fabric_parallel.py` exercised all 21 canonical registered identities individually. For each identity it checked its immutable ID, registered and unassigned state, declared input and output fields, capability ownership, authority boundary, and legal PRIME-to-lead or lead-to-child path through `AgentAuthorityRuntime` with a temporary SQLite ledger.

The same test module ran deterministic fake tool tasks at logical concurrency widths 2, 4, 8, and 21. A barrier held every task in flight simultaneously; the observed peak equaled the requested width each time. Every task returned a distinct, correctly attributed output shaped to that agent's declared output contract. The tasks made zero model requests and did not contact a service or production database.

At candidate tip `d5a544f` plus this focused test change, the ABEX `test-runs/lens-20260928-venv` Python ran `python -m pytest tests/test_agent_fabric_parallel.py -q`: **50 passed in 5.71s**. The new individual task test gave **21/21** registered identities an authorized handoff, a deterministic local fake execution, an attributed result matching the declared output shape, and started/completed action records tied to the same trace. All ledgers were created under pytest temporary directories. The generic `python` command was unavailable on this host, so this existing test virtual environment supplied pytest.

The [benchmark JSON](PRIME_AGENT_FABRIC_BENCHMARK.json) records monotonic start/end intervals for every fake task. A 50 ms fixed-duration fake I/O job was run serially and through a thread pool at each width:

| Logical tasks | Serial wall ms | Parallel wall ms | Speedup | Maximum interval overlap |
|---:|---:|---:|---:|---:|
| 2 | 101.923 | 52.342 | 1.947x | 2 |
| 4 | 201.620 | 51.483 | 3.916x | 4 |
| 8 | 403.239 | 52.795 | 7.638x | 8 |
| 21 | 1060.069 | 54.875 | 19.318x | 21 |

These are one local sample of sleeping fake jobs, not service throughput or model latency measurements. The test itself asserts timestamp overlap and lower parallel wall time at every width.

## Boundary

This proves registry consistency, legal handoff paths, 21/21 individually attributable local fake send/execute/result cycles, and overlapping independent Python fake tasks in this worktree. It does not establish that 21 model instances, workers, physical slots, queue entries, or agents are available concurrently in the deployed service. Registry records explicitly have `model: unassigned`, and their physical slot claim is `scheduler only`. The input/output contracts are registry declarations; the current dispatcher does not validate a live model answer against every output field. Live operational availability and end-to-end model performance remain unverified by this proof.

No production host or data changes were made.
