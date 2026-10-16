# Brand and naming boundary — Owner decision 2026-10-16

This is the single reference for the ORQEVIA naming state after the Owner
decision of 16 October 2026: **"no more PRIME, JARVIS, SSOT"** in the ORQEVIA
product. It applies to every channel and every agent.

## The product brand is ORQEVIA (奥启维亚) — only

**Changed and verified 2026-10-16 (command-icon mission):**

- Install identity: new `clients/pwa/icons/orqevia-command-v1-*` family
  (dark master 1024, SVG source, light variant, PWA 192/512, maskable 512,
  apple-touch 180, favicons 16/32/48, `favicon.ico`). The legacy dark "lime J"
  artwork that the re-brand had mistakenly kept in `orqevia-official-v1-*` is
  **deleted**; `tests/test_pwa_branding.py` now fails if those bytes reappear
  under any name.
- In-app brand mark: the real ORQEVIA logo restored to
  `icons/orqevia-official-v1-192.png` (the wrapper previously carried the old
  glyph). Only this one file remains from the `orqevia-official-v1` line.
- Manifest, index head, service worker cache list (`orqevia-shell-v27`),
  recovery flag (`orqeviaReady`) and the PWA README all updated to the new
  identity.
- Response contract: `app/jarvis_response_contract.py` → renamed
  `app/orqevia_response_contract.py`; an answer that omits **ORQEVIA** when
  asked its name is now flagged `product_identity_missing` (previously the
  contract still demanded the old name — the identity split-brain is fixed at
  the source). Candidate verifier renamed
  `scripts/verify_jarvis_candidate.py` → `scripts/verify_orqevia_candidate.py`.

## Deliberately staged (compatibility or signing-closure bound)

Renaming these tonight would break a live wire contract or the protected
signing closure that was just completed. Each has an exact unblock path; the
Owner can order the migration round at any time.

| Identifier | Why it stays (for now) | Root-fix path |
|---|---|---|
| `jarvis.interface.v1` protocol string + `X-Jarvis-PWA`/`X-PRIME-Protocol` headers | Cached clients negotiate on it; renaming breaks old installs | Dual-accept round: server accepts both, client switches, then removal after cache expiry |
| `PRIME_*` environment variables (PRIME_DATA_DIR, PRIME_SPINE_TOKEN, PRIME_INTERFACE_*, …) and `prime-epoch-20260919` project/container names | Live services, backups and runbooks reference them | Env-var aliasing round (read new name, fall back to old), then compose/project rename with fresh rollback receipts |
| `app/agent_dispatch_api.py` (`JARVIS_IDENTITY_CONTRACT` alias) and other files in the 47-file verifier closure | These exact bytes anchor the completed fresh29-20261016 signing closure | A new dated closure validation round, then rename with re-pins |
| Golden manifests (`governance/golden-gen1/2`) and their frozen architecture docs (`docs/JARVIS-PRIME-*`) | SHA-256 pinned baselines | Re-issue as a new generation with updated verifier pins |
| Dated historical evidence (`docs/evidence/**`, `governance/observations/**`, receipts like `ABEX_RUNTIME_RECEIPT_17FAD78`) | They record what was true on their date | Never rewritten; history keeps its names by definition |

Until those rounds run, PRIME/JARVIS in the categories above are compatibility
or historical identifiers — never the product brand. Nothing user-facing may
present them as the app's name.
