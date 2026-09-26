# JARVIS PRIME accelerated production-promotion closure — 2026-09-26

Verdict: **ACCEPT — production promoted and independently verified.** This is a Codex-observed claim and has not been moved into Lam's personally verified section of `STATUS.md`.

## Owner decision and observation truth

- Owner accelerated promotion: **YES**.
- Original target: `2026-10-02T07:19:19+08:00`, subject to powered-off intervals.
- Clean pre-promotion observation achieved: approximately `25:51:29`.
- Uncompleted duration: approximately `5 days 22:08:31`, **OWNER-WAIVED FOR THIS PROMOTION**.
- The original soak is not recorded as passed. Its ledger remains historical evidence.
- GOLDEN remains `GOLDEN_PENDING` under the historical semantics.

## Provenance and rollback

`0ecb5803470bef2a941da31332d87702268648d6` / `prime:sha-0ecb580` / `sha256:e59c43c…`
→ qualified source `a1ea9ad0a253c40de70194ebf38b7a58c925e5b2`
→ evidence `6a82ecba2b3e58f2b8ffe62582350ee211c6a0f8`
→ deployment `2026-09-26T09:10:48.8425829+08:00`
→ runtime `prime:sha-a1ea9ad` / `sha256:076c6c4cdf21066e6b1029850bef186697f2aedcde6fc0a493c65d68b293b144`.

The previous image, private configuration copy, Compose file, and consistent data snapshot are retained under `recovery-records/production-promotion-20260926-090630/rollback-baseline`. The snapshot contains 34 files; all seven SQLite databases passed `quick_check`; manifest SHA-256 is `4c9ab968760f77b8a98d9409e260bf25ad5ca269dc3c403b2f587a6fc6c8a2c0`.

## Deployment and runtime acceptance

- PRIME and Interface alone were recreated through Compose; Ollama and Windows were not restarted.
- PRIME, Interface, and Ollama are healthy, with zero restarts and no OOM state.
- Both rebuilt containers independently report the exact source revision and image ID above.
- New production objective `e0309e61-3b93-4f00-8013-22ecef14411e` completed through the normal Owner control path.
- Artifact `2b87ac30061649fbb24aabd396928bdf` was created and retrieved: 1,222 bytes, SHA-256 `f72c6609232491a544994ed08272ee4046833b136fa7340f5c65da6fc8aa8a2b`.
- Invalid input returned HTTP 422; no false-success path was observed.
- Deployed deterministic checks passed for contextual freshness, deduction/fallacy rejection, induction uncertainty, UNKNOWN competence, bounded acquisition, safe Pareto selection, anti-Goodhart rejection, and prohibition on model-created authority.
- All seven production databases remain `quick_check=ok`; queue pressure is zero. Identity, pairing, and admission table hashes exactly match the pre-promotion snapshot.
- Six stored identities/sessions remain (three Owner, three Member), but all sessions are expired. Physical Owner/Member acceptance is therefore **NOT TESTED THIS PROMOTION**; no identity was deleted, duplicated, or re-enrolled.
- PWA and manifest return HTTPS 200. API remains loopback-only at `127.0.0.1:8000`; Interface remains private-LAN-only at `192.168.1.23:8443`.
- Defender real-time protection and all firewall profiles are enabled. No relevant post-deployment Windows/storage/WHEA/bugcheck event or container error log line appeared.
- Three resource samples were stable: PRIME stayed below 0.6% CPU and approximately 47 MiB RAM, Interface approximately 41 MiB, free disk 844.14 GiB.

## Defects

- `PROMO-20260926-01` (P2): persisted `.env` identified an older image/revision than the running pre-promotion containers, risking regression on a future Compose recreation. Repaired before cutover by pinning the promoted image and SHA.
- `PROMO-20260926-02` (P5): a generic read-only helper could not make a consistent live backup of the WAL-backed compute queue. Repaired operationally by using SQLite online backup from the owning PRIME container; all exports verified.

No newly introduced unresolved P0/P1 defect was identified. No rollback was performed. The new observation epoch is `prime-a1ea9ad-20260926T091048+0800`; normal quiet production monitoring follows the enhanced immediate checks.

Machine-readable receipt: `docs/evidence/PRODUCTION_PROMOTION_RECEIPT_20260926.json`.
