# Brand and naming boundary

This is the single reference for what is renamed versus what intentionally still
says SSOT, JARVIS or PRIME. It applies to every channel (ChatGPT, Codex, Sol,
Astra, ABEX, Dell) and every agent.

## Already renamed or retired

- Product brand: ORQEVIA (奥启维亚).
- Repository: AndrewLamSingapore/orqevia (renamed from prime).
- PWA user-facing brand and install assets: ORQEVIA (`orqevia-official-v1-*`).
- SSOT.json: retired and absent; `scripts/check_status_authority.py` rejects its
  reappearance.

## What must NOT be blanket-renamed or removed

The remaining SSOT/JARVIS/PRIME text falls into five deliberately preserved
categories. Treat each as frozen until an explicit Owner decision re-pins it.

1. Frozen golden manifests
   - governance/golden-gen1-manifest.json
   - governance/golden-gen2-manifest.json
   These freeze the internal baseline identity (`jarvis-prime-golden-*`),
   `production_authority: ABEX`, and the internal "ABEX PRIME" identity. Their
   hashes are verified by `scripts/verify_golden_gen1.py` and
   `scripts/verify_golden_gen2.py`.

2. Byte-pinned operational manifest
   - governance/operational-manifest.json
   Contains `JARVIS_PRIME_CURRENT_SSOT.md` (human resume mirror title),
   `truth_reconciliation`, `repository_registry`, and superseded-SSOT references.
   `tests/test_portfolio_reconciliation.py` byte-pins its authority prose and
   evidence hashes; editing requires a matching, recorded test update.

3. Internal runtime identifiers (functional, not brand)
   - Environment names such as PRIME_DATA_DIR, PRIME_COMPUTE_QUEUE_DB,
     PRIME_SPINE_TOKEN, PRIME_LOCAL_ADMISSION_MODE, PRIME_QUEUE_CONCURRENCY,
     PRIME_INTERFACE_*, and OLLAMA_*.
   - Modules and contracts such as app/jarvis_response_contract.py,
     app/prime_evidence_adapter.py, contracts/prime-execution-record-v1.schema.json,
     and portfolio-contracts.
   - Docker images/tags (`prime:sha-*`) and workflow identity files
     (`orqevia-verifier-oidc.yml`, `orqevia-verifier-signer.yml`; OIDC identity-bound).
   Renaming these breaks runtime configuration, signing identity, or deployments.

4. Historical evidence
   - docs/evidence/**, governance/observations/**,
     governance/reconciliations/**, docs/deployments/**,
     governance/agent-cert-case-evidence/**.
   These are dated records; the old names inside them are preserved history.

5. Frozen architecture documents
   - docs/JARVIS-PRIME-GOLDEN-BASELINE-ARCHITECTURE.md
   - docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md
   Referenced by the golden manifests with SHA-256 pins.

## Legacy SSOT-era tooling (retired and removed)

The Dell truth-reconciler and node-sync tools were retired and removed from
source on 16 October 2026. They remain recoverable from Git history as
historical evidence:

- tools/dell_truth_reconciler/**
- tools/dell_node_sync/**
- config/dell-truth-reconciler.example.json
- config/dell-node-sync.example.json
- scripts/install_dell_truth_reconciler.ps1
- scripts/install_dell_node_sync.ps1
- scripts/run_dell_truth_reconciler.ps1
- scripts/run_dell_node_sync.ps1
- docs/DELL_TRUTH_RECONCILER.md
- docs/DELL_NODE_SYNCHRONIZATION.md
- tests/test_truth_reconciler.py
- tests/test_dell_node_sync.py

Note: contracts/truth-reconciliation-v1.schema.json stays because the
operational manifest still references it as `truth_reconciliation.result_contract`.

## Rule for everyone

SSOT/JARVIS/PRIME in the five preserved categories are compatibility or
historical identifiers, not the product brand. Do not rename, delete, or
"clean up" them without an Owner decision and a re-pinned manifest or golden
record. The product brand is ORQEVIA.
