# Phase 2 Gap Analysis — 2026-09-26

## Golden capabilities reused

| Capability | Existing implementation | Phase 2 disposition |
|---|---|---|
| Identity and authority | canonical server enforcement | Reuse unchanged |
| Registry | schema 2.0, 21 agents | Reuse; no new agent |
| Memory/RAG | governed knowledge and hybrid memory | Reuse behind scoped context compiler |
| Workflows | workflow engine | Reuse as execution adapter; kernel itself executes no tools |
| Offline continuity | durable offline queue/reconciler | Reuse; effect receipt prevents duplicate consequence |
| Provenance | system/model content separation | Extend to objective and prediction records |
| PWA/client | accepted Golden interface | Unchanged in this candidate increment |

## Genuinely missing primitive

Golden Gen 1 did not contain one durable, integrity-bound state machine connecting the original objective and success criteria to restart-safe checkpoints, scoped context, hypothesis revision, exactly-once effect receipts, qualified learning and immutable shadow predictions. `app/phase2_intelligence.py` supplies that candidate primitive without touching production.

## Defects found during implementation

1. Initial context and lesson writes lacked explicit authority gates.
2. Owner/Member/System context scope ownership was not enforced on ingestion.
3. An operation-ID collision with different effect content could be mistaken for an idempotent duplicate.
4. Completion evidence was validated but not persisted into the terminal checkpoint.
5. Prediction integrity was not rechecked before outcome resolution.

All five were reproduced and repaired before candidate expansion. Regression tests preserve each boundary.

## Remaining boundaries

- Candidate is not integrated with the live workflow adapter or production database.
- Prediction accuracy requires elapsed real horizons; simulation establishes mechanics, not real-world forecasting skill.
- Long-duration Golden stability remains a separate observation gate.
- Physical Wuhan/mainland-China evidence remains pending.
- Production promotion and new runtime acceptance are not implied by candidate tests.
