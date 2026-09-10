# Reliability and independent evidence work — discovered state

Owner decision, 10 September 2026. Reporting and implementation scope only;
this does not replace a frozen specification or confer execution authority.

## Current evidence

- Development checkout: clean codex/prime-mandate-20260910 at local 4e0654f,
  source tree b1d262ff79f790aba89b950f236e300594940a7f (PR60 remote 8b4a6bd).
- Existing Dell checkout: OneDrive/Documents/prime, main, clean; unchanged.
- One PDP/PEP path: app/spine, app/action_harness.py, app/harness_execution.py.
  Shared SQLite queue: app/job_queue.py; pilot remains a14/a16/a21, one slot,
  local only. Registry capacity is not permission. Frozen PR59 remains unchanged.
- Claim already skips resource-ineligible queued work and approval-waiting work.
  An unordered LIMIT 1000 before priority sorting can exclude eligible work or
  the true highest-priority work. This is a concrete scheduling defect.
- Compose's optional cloudflared service has restart and bounded log retention;
  it is distinct from the discovered Windows OpenAI tunnel-client 0.0.14,
  build 0f870e50a973fa820d4c409000059e181e8d242b. The latter exposes run,
  health --require-control-plane-poll, profile-file, PID and health URL options.
  No tunnel-client/cloudflared process was observed via Get-Process.
  Process command-line inventory was denied by Windows; this is incomplete
  visibility, not proof that no other-account/service tunnel exists.
- Existing profile folder AppData/Roaming/tunnel-client and runtime inventory
  AppData/Local/JARVIS remain Windows-access-denied even after scoped read
  permission was granted. No profile, credential, alias or authority is recreated.
- No superseding frozen benchmark protocol/addendum/corpus materialized in the
  inspected PRIME checkout. Existing endpoint fixtures are not ABEX measurements.
- VELYQUA main tree 23eb80bc3fd280e4209c9f9eb3bcd764045d0cc3 was inspected
  read-only through GitHub. prototype/firmware/README.md permits serial/USB bench
  logging without cloud infrastructure. src/observations/acquisition.ts and
  docs/observation-implementation-status.md establish CRC/hash/length groundwork,
  not completed Gate 1/2/3. Controlled quality flags and five indeterminate reason
  codes remain missing. Precedence is invalid > unknown > degraded > valid.
  No firmware implementation or replacement trust enums are fabricated.

## Dependency classification

| Workstream | ABEX | Other genuine prerequisites | Independent progress |
| --- | --- | --- | --- |
| Harness source/fixtures | NO DEPENDENCY | Existing signed pilot contracts | Continue on Dell/CI; benchmarking does not authorize execution |
| ABEX Harness integration | HARD DEPENDENCY | Stable OS/storage/network, node identity, approved secrets, isolated runtime, health | Run alongside capacity work after actual minimum baseline; production gate remains separate |
| Frozen Compute Profile authoring/runner | NO DEPENDENCY for source | HARD: exact versioned protocol/addendum/corpus manifest rules | Do not invent frozen artifacts; existing unrelated benchmark fixtures remain usable |
| ABEX capacity measurements | HARD DEPENDENCY | Same minimum runtime baseline plus canonical corpus | Parallel to Harness; measured ceilings constrain resources only |
| Tunnel source/fixtures | NO DEPENDENCY | Verified client command interface | Test transport-only supervision independently |
| Existing Dell tunnel installation | NO DEPENDENCY | HARD: readable approved profile and owner-context process visibility | Installation held by Windows access; no second connection created |
| VELYQUA bench acquisition | NO DEPENDENCY found | HARD: actual probe/interface/board and electrical settings | Serial/USB is sufficient; hardware is owner-PARKED |
| VELYQUA full Gate 3 acceptance | NO DEPENDENCY found | HARD: canonical Gate 1/2 definitions, persisted Observation flow, CRC-valid real frames | Specification gap distinct from hardware park; no synthetic PASS |
| W3-01 | NO DEPENDENCY for specification/test source | HARD: actual workload specification, tier/risk policy, approved testnet credentials for execution | Zero real funds; do not infer authorization from spare capacity |

Tunnel is a HARD dependency only for work that actually needs remote transport;
local/serial evidence work does not wait for it. Convenience of remote access is
otherwise a SOFT dependency. Work > Web3 > VELYQUA governs contention within
eligible work, not an ecosystem-wide serial dependency. The existing signed
priority field and starvation protections remain canonical; no new scheduler,
state vocabulary, speculative domain classifier or authority engine is added.

ABEX/qualification and probe-dependent physical acceptance remain PARKED until
arrival. Offline Companion external artifact gates remain unchanged.
