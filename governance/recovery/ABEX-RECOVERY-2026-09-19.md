# ABEX Recovery and Reconstruction Record — 2026-09-19

This is a non-secret, off-machine recovery record. It does not override `governance/operational-manifest.json`, which remains the sole operational SSOT and remains `STALE` until runtime evidence is independently accepted.

## Proven facts

- The original Kingsand SSD is permanently unavailable.
- The replacement device is `Lexar SSD NM610 PRO 1TB`; Windows reported `Healthy / OK` during recovery checks.
- No matching Disk, NTFS, NVMe/controller, volume-manager, WHEA or BugCheck warning/error was found in the examined post-repair window.
- Three Kernel-Power 41 events exist on September 17–19. The September 19 event corresponds to a human forced power cycle; event 41 alone does not establish root cause.
- A later apparent HDMI loss was Windows Modern Standby: entry reason `Idle Timeout`, exit reason `Input Keyboard`; ABEX remained responsive and did not reboot.
- PRIME was not activated during source recovery. Docker, original `.env`, original databases/volumes, original credentials, enrollment state and trust state were absent.

## Recovery semantics

The original PRIME trust epoch is **UNRECOVERABLE** unless equivalent authoritative external evidence is independently found. The lost objects must never be silently recreated and described as recovered.

Any commissioned replacement must be labelled **NEW PRIME TRUST EPOCH** and must distinguish:

- recovered source;
- reconstructed non-secret configuration;
- new reconstructed runtime database;
- new credentials;
- new Owner and Member sessions;
- new device enrollments;
- new trust relationships.

No plaintext secret belongs in Git, runtime receipts, or this record.

## Canonical source and safety baseline

- PRIME safety merge: `7cf75b0395e772c19463cfa00217cce2759edcdb`.
- Safety feature commit: `a11a24dd9d9284d8b968f465aab4dfd1d5952c1c`.
- Windows portability commit: `3ea8e46896778b72c36fe4c99491622d94d220b9`.
- Portal 6.5.0 documentation merge: `8af57e4c35e4b53bd3307005ddc9dabfc6dc453f`.
- Canonical active registry: 21 agents. The 29-agent fixture is preserved historical migration evidence.
- W3-01 recovered design exists remotely at authority-engine commit `4681521e74b9a1d45161889a49fa57eb612c6d45` and remains `PARKED / DO NOT EXECUTE / ZERO REAL FUNDS`.
- VELYQUA source and public health aligned at `4ecf65eec8dca0926fe01c3e9c34488e80764470`, version `0.4.0`, during recovery observation. Physical sensors remain untested; simulation is not real telemetry.

## Permanent host boundary

PRIME application authority does not include destructive host authority. Disk initialization/formatting, partition/GPT/MBR changes, EFI/BCD changes, destructive filesystem repair, firmware/BIOS/CMOS/TPM/Secure Boot mutation, Windows reset/reinstall, destructive credential operations and destructive Git history rewriting require exact owner authorization and cannot be self-authorized by an agent.

`app/host_guard.py` classifies execution effects immediately before the executor. Unknown privileged effects fail closed. Exact approval is bound to action/executable/arguments/target; risk cannot be lowered by the caller.

## Test evidence

- Focused host-guard/harness/connector/recovery contracts: 30 passed.
- Canonical isolated CI runner: 239 passed, 0 failed, one dependency deprecation warning.
- Portal `npm run verify`: passed.
- Broad all-files pytest composition after installing pinned Wasmtime: 465 passed / 95 failed. These failures remain visible and are dominated by legacy/current entrypoint suite contamination; they are not represented as green.

## Reconstruction dependencies

- Node.js: `22.23.2` was used during recovery validation; project engine requirement is Node 22.x where declared.
- Python: 3.12 with `requirements.txt`.
- Wasmtime: `48.0.0` from `requirements-sandbox.txt`.
- Docker/Compose: required by current runtime topology but version/image selection must be recorded before activation.
- Critical images must use reviewed immutable tags or digests. `latest` is prohibited by the recovered Compose contract.
- PRIME must initially bind only to `127.0.0.1:8000`; tunnel services remain opt-in.

Required image variables before Compose validation:

- `OLLAMA_IMAGE`
- `CADDY_IMAGE`
- `CLOUDFLARED_IMAGE`
- optionally commit-addressed `PRIME_IMAGE`, or a recorded local build from the selected commit

## Database and trust commissioning

If the original database remains unavailable, create a separately named volume/database labelled `NEW RECONSTRUCTED RUNTIME DATABASE`. Apply authoritative migrations only. Do not insert fabricated history.

Generate credentials with a cryptographically secure generator into an owner-controlled local secret mechanism. Record variable names, epoch ID and recovery procedure, never values. Establish Owner first, then a separately authorized Member invitation/device. `OWNER != MEMBER` is a permanent acceptance rule.

## Incremental activation order

1. Host stability and pre-reboot checkpoint.
2. Pinned infrastructure dependencies.
3. Reconstructed configuration and database schema.
4. PRIME loopback health and real bounded task evidence.
5. 21-agent registry and tool containment.
6. New Owner identity/session.
7. New Member invitation/session.
8. Observer.
9. Reconciler.
10. Physical clients with human interaction.
11. Autonomous repair last, with harmless controlled trials and independent retest.

At each stage: start, observe, test, record, then continue. A listening port alone is not operational proof.

## Always-on host behavior

The Windows plan retained display-off behavior while sleep/hibernate were disabled. Because this S0 platform entered Modern Standby when the screen timed out, recovery added a per-user startup keeper using `ES_SYSTEM_REQUIRED` only. It intentionally does not request `ES_DISPLAY_REQUIRED`, away mode, firmware changes, or disabled thermal safeguards.

## Disaster recovery target

ABEX hardware, SSD and Windows must be replaceable. Source, safety architecture, schemas, topology, non-secret reconstruction instructions, VELYQUA and W3-01 evidence must remain remotely durable. After catastrophic host loss, secrets and trust are newly commissioned into a new explicit epoch rather than inferred from an old machine.
