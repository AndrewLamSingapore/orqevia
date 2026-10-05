# A20 Hugging Face candidate canary — 5 October 2026

Scope: one isolated, synthetic A20 agent-mediated cloud request against
`feat/backend-admission-20261005@515260b54da7cf59d172aac737bfee070fda9a6f`.
This is **not** a Golden deployment, 21-agent inference proof, or L7 certification.

- Source worktree clean before and after. Canary script:
  `ABEX/recovery-records/master-closure-20261004/hf_a20_current_canary.py`,
  SHA-256 `9bb9967524d58bedf16d19c96b7b8d8d255aeac38c1f45902e20a26d5f027b83`.
- One-shot container used the accepted Golden image ID
  `sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5`
  as a Python base, with candidate source and the protected token file mounted
  read-only. Root filesystem read-only; isolated `/tmp`; 512 MiB, one CPU,
  64-PID limit; no published port, dropped capabilities and no-new-privileges.
  It exited 0 and `--rm` removed it. The token, prompt and response were not
  printed; only redacted result metadata was returned.
- Synthetic route: registered `a20` / `responsibility.a20` → authenticated
  dispatcher → governed queue → explicit cloud provider →
  `google/gemma-3-4b-it:deepinfra`. Classification was `CLOUD_PERMITTED` and
  maximum job cost was USD 0.0005. The transient catalog existed only inside
  the one-shot container, not in Golden PRIME.
- Result: dispatch PASS, queue PASS, inference PASS, credential readiness READY,
  exactly one transport request, one correlated successful ledger row,
  completed queue status, zero retries, 177 input tokens, three output tokens,
  751 ms elapsed. Estimated cost USD 0.00000915 from provider-reported usage
  and advertised rates; actual billing was not independently verified.
- Current public Hugging Face model metadata identified DeepInfra as live and
  listed USD 0.05/M input and USD 0.10/M output tokens:
  <https://router.huggingface.co/v1/models/google/gemma-3-4b-it>.
  These prices may change and must be rechecked before production admission.
- Golden PRIME and Interface remained on the accepted image above; Ollama on
  `sha256:da6e0dc5651df159e45686fd663c4dbe1624a52c44d7280eeac1551d8f865532`.
  All three were running/healthy, with zero restarts and OOM kills after the
  canary. Production has no HF catalog or secret mount.

Open gates: production provider qualification/configuration and privacy review,
exact rollback, accepted runtime promotion, Owner-path proof, and independent
per-capability L7 evidence. Do not infer any of those from this canary.
