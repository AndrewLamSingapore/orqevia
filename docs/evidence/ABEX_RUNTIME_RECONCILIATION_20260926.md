# ABEX Runtime Reconciliation — 2026-09-26

Status: **ABEX-OBSERVED / INDEPENDENT DELL ACCEPTANCE PENDING**

This record is non-secret evidence prepared on ABEX. It is not an independent
receipt and must not change `PRIME.RUNTIME ACCEPTANCE` to verified by itself.

## Current production identity

- Windows host name: `DESKTOP-27LKJ2V`; governed PRIME host identity: `ABEX`.
- Production lineage: `feat/supreme-integration-20260925` at remote SHA
  `44b261e241a2e951626e1c5c28c466e8c620d623`.
- Running source revision: `f874eab4f69c43bdfda7eb8a79a604eaf378a054`.
- PRIME and Interface image: `prime:sha-f874eab`.
- Image ID: `sha256:5a961ed5f3f8d06e9145b09ab4c8157fb63719f7c4770fc5f46d67e80999902c`.
- The one production-lineage commit after the image revision is configuration
  correction `44b261e` (PR #120), which passes the canonical Owner account to
  PRIME's loopback-only pairing authority. The correction is active in the
  runtime Compose configuration and does not change executable image content.
- `origin/main` is `687016796b0816f4055c27120357976f803fc765`.
  Production and main intentionally diverge from merge base
  `0d4b8d19a8b7d82ffe1ff231a912ac9652f85a4b`: production has 53 unique commits;
  main has two Offline Survival commits. Main is not the production release.

## Runtime observations

- PRIME: healthy, zero restarts, not OOM-killed.
- Interface: healthy, zero restarts, not OOM-killed.
- Ollama: healthy, zero restarts, pinned digest
  `sha256:da6e0dc5651df159e45686fd663c4dbe1624a52c44d7280eeac1551d8f865532`.
- Models present: `gemma3:1b`, `gemma3:4b`, and
  `embeddinggemma:300m-qat-q4_0`.
- ABEX IPv4 endpoint: `192.168.1.23`.
- Intended listeners: PRIME `127.0.0.1:8000`; HTTPS Interface
  `192.168.1.23:8443`.
- `/pwa/`, `/pwa/index.html`, and `/pwa/recovery.js` returned HTTP 200.
- No public Ollama, database, Docker, or PRIME-internal listener was observed.

## Registry truth

- Schema: `2.0`; registry version: `1.0.0`.
- Logical agents: 21.
- Historical responsibility mappings: 29.
- Runtime registry SHA-256:
  `fec92b1d0e3e858bc5f4fe1b26401d053ee94b9b2358be8da379b97884d916ff`.
- Runtime and source registry hashes are identical.
- `registered_agent_ids()` returns the 21 canonical logical agents plus the
  unnumbered `prime` orchestrator (22 identifiers total). This does not mean 22
  specialist agents.

The earlier Dell observation of image `sha-c449dd1`, schema `1.1`, and 29
logical agents describes an older deployment and is not current ABEX runtime
evidence.

## Data, queue, and identity observations

- All seven production SQLite databases returned `PRAGMA integrity_check = ok`:
  `compute-ledger.db`, `compute-queue.db`, `interface.db`,
  `jarvis-memory.db`, `objectives.db`, `offline-queue.db`, and
  `pwa-sessions.db`.
- Compute queue: 11 completed; no pending, running, failed, or orphan state was
  observed.
- Offline queue: one reconciled record; no unreconciled work observed.
- Owner session: one active canonical-account-bound session.
- Member records: three preserved historical session records, zero active.
  Therefore “no Member identity exists” is not supported by the canonical live
  session store; equally, an active Member client is not currently proven.
- No live unused enrollment credential exists.

## Fresh Owner objective evidence

- Objective UUID: `d249e15a-03ee-466e-a051-d6838747a715`.
- Compute job: `1722b7c3-daaf-49d2-b803-c2bd801c78b8`.
- State: `COMPLETED`; job status: `completed`; text result present.
- Artifact ID: `efadc463f43e4413af22ea124aa55732`.
- Artifact: Markdown, 317 bytes, `STRUCTURE_VALIDATED`, contains the requested
  unique marker `OWNER-LAN-20260926` and Chinese content.
- Server execution and artifact persistence are verified. Physical display and
  retrieval on the Owner iPhone remain Owner-observed evidence, not established
  by this ABEX record alone.

## Host health

- Windows 11 Home build `26200`; no relevant 24-hour disk, NTFS, NVMe, WHEA,
  bugcheck, unexpected-power, or volume-manager critical/error event observed.
- Windows Time running and synchronized to `time.windows.com`.
- Microsoft Defender and Windows Firewall services running.
- Docker Engine `29.8.0`; WSL default version 2.

## Rollback

- Immediate prior image: `prime:sha-a1ea9ad`, image ID
  `sha256:076c6c4cdf21066e6b1029850bef186697f2aedcde6fc0a493c65d68b293b144`.
- Earlier baseline: `prime:sha-0ecb580`, image ID
  `sha256:e59c43c885dd07bd2b037e8c7281b999749c3f54cba76a9bff95ce1de7e13d6c`.
- Private checkpoints retained under
  `recovery-records/pwa-navigation-repair-20260926-100808` and
  `recovery-records/production-promotion-20260926-090630`.
- Their existence does not authorize or constitute a rollback.

## Acceptance boundary

Authority Engine revision
`a4134f155f7b7f0e560e692a947234b3f9610828` intentionally reports
`independent_runtime_receipt_required`. No code path currently validates and
consumes an independent Dell runtime receipt. Consequently:

`PRIME.RUNTIME ACCEPTANCE = UNVERIFIED`

until Dell independently verifies current runtime evidence and a governed,
non-forgeable receipt-validation path is implemented and exercised. Do not
manually flip `prime.state`.

