# Golden Gen 2 SSOT reconciliation — 2026-09-27

Golden Gen 2 accepts exact source `b171253566e7c879283d2aacf699ae6c1ec8988e` and immutable image `sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5` for the qualified Phase-2 non-audio scope.

Read Aloud/iOS audio is explicitly **PARKED — PHYSICAL FAIL / NOT ACCEPTED** under the Owner waiver. This exclusion is not a technical PASS and is not counted among unresolved P0/P1/P2 for the accepted scope.

Canonical references:

- `governance/golden-gen2-manifest.json`
- `docs/evidence/PHASE2_RUNTIME_RECEIPT_B171253_20260927.json`
- `docs/evidence/PHASE2_PRIME_RUNTIME_ACCEPTANCE_20260927.json`
- `docs/evidence/IOS_PWA_AUDIO_OUTPUT_NOT_PHYSICALLY_VERIFIED.md`

Golden Gen 1 remains immutable rollback/history. The Phase-2 production database volume, identities, sessions, task history, queues, artifacts and memory were preserved through promotion and bounded service restart.

Dell subsequently returned `PROMOTION_VERIFICATION_PASS` for the accepted non-audio scope using the signed live Docker-derived runtime attestation. It independently matched source, image digest, Golden generation, immutable manifest digest, runtime-receipt digest and live PWA, and reported P0/P1/P2 = 0 within scope. The exact external Dell receipt remains on Dell at `C:/Users/User/Documents/Codex/2026-09-27/y/outputs/DELL-GEN2-POST-PROMOTION-RECEIPT-20260927.md`, 2,445 bytes, SHA-256 `566e5f8d0f55f0af30d02ca2c0672b08fa329809ee26fd3fc19a680165055d71`; ABEX did not recreate it. Reconciliation metadata is preserved in `docs/evidence/DELL_GEN2_POST_PROMOTION_RECONCILIATION_20260927.json`. The frozen Golden manifest remains byte-identical to the version Dell audited; its embedded `PENDING` value is historical pre-audit state rather than a mutable final-status field.

No cognitive-continuity, commercial, VELYQUA physical-telemetry or new feature program is activated by this reconciliation.
