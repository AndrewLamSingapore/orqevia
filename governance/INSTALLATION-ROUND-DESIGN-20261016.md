# Installation round — design record (16 October 2026)

Owner directive: proceed with the Installation-Closure Round — bind the signed
fresh 20261016 cases into each agent's owned domains, and ride the
signing-closure-pinned registry changes (per-agent model bindings and the
"born in Singapore, 2026" origin field) in the same round.

## Mechanism (as built tonight, candidate tier)

1. Input: the protected signed artifact of run `38871679860`
   (`state=SIGNED_CASE_EVIDENCE`, 29/29, `l7_awarded=false`) — local copy at
   `operations/fresh29-20261016/signed-cases/`.
2. For each signed case, the unchanged initialization module resolves the
   agent-owned domain: `agent_cert_initialization._owned_domains(registry_sha,
   agent, capability)` against the current registry bytes.
3. Output: `governance/agent-cert-installation-20261016.json` — 29 installation
   records (agent, capability, dimension, test case, owned domain, signature
   provenance pointer, timestamps), explicitly marked
   `CANDIDATE_INSTALLATION — CLAIMED, NOT PROTECTED-EXECUTED`.

## Registry changes (model bindings + origin) — STAGED by a hard lock

Attempted and reverted tonight with evidence: the initialization module
strictly validates the registry bytes (`_owned_domains` raises
`INITIALIZATION_OWNED_DOMAINS_UNAVAILABLE` on ANY byte change — extra keys,
collapsed model values, or reformatting), by design. The registry therefore
cannot receive `origin`/`model` bindings ad hoc; they ride the next sanctioned
closure re-issue with explicit re-pins. Until then the origin is carried by
`governance/ORQEVIA-ORIGIN.md`, the product surfaces, and the readiness
artifact; the effective model binding (tier router → local `gemma3:1b/4b`) is
documented in this record.

## Guardrails held

- No runtime activation, no backend flags, no deployment change, no L7.
- The candidate is evidence-binding only; acceptance requires a protected
  installation round with its own one-shot workflow and receipts — the exact
  follow-on step, mirroring how validation → signing was executed.

## Status

- Candidate runner: `scripts/install_initialization_20261016.py`
- Candidate evidence: `governance/agent-cert-installation-20261016.json`
- Protected installation execution: NEXT (design fixed here; workflow to be
  minted as the round's one-shot, consuming the signed artifact and verifying
  this candidate's bindings byte-for-byte).
