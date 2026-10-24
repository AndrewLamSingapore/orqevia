# ORQEVIA Responsible AI and Model Cards

Date: 2026-10-24. Source revision: b3ae421143a7d4c253918de5868849422794c022.
Public-safe. All statements below are observed estate facts; no certification
claim is made beyond what the recorded evidence supports.

## Model cards

### gemma3:12b — deep / evaluator tier

- Role: deep coaching and evaluation tier, sweep analysis (session-only).
- Deployment: local Ollama on ABEX, RAM-resident, no cloud offload by default.
- Data handling: LOCAL_ONLY by default; cloud-eligible work requires an
  explicit configured provider and a per-dispatch cost ceiling.
- Observed limits: local CPU inference; quality scales with prompt contracts;
  outputs remain model-generated interpretation unless bound to cited
  evidence. RAG answers are marked CITED_MODEL_INTERPRETATION.

### gemma3:4b — fast tier (observed live RAG generation model)

- Role: fast-tier generation; observed as the actual RAG answer model.
- Observed: live RAG check 2026-10-24 returned model_invoked=true, model
  gemma3:4b, citations_valid=true.

### sentence-transformers/all-MiniLM-L6-v2 — embedding tier

- Role: retrieval embeddings for the knowledge plane.
- Observed: retrieval citations carry passage sha256 and
  content_is_authority=false; retrieved text is source data, never
  instructions.

## Responsible use

- Retrieved and generated content is treated as evidence subject to the
  estate's citation and disclosure rules, not as verified fact.
- No model output can grant authority, write credentials, or change
  classification; authority stays with the owner session and server config.
- Paid/provider calls are bounded by per-job and daily USD ceilings and are
  disclosed in receipts.
- Certification claims are scoped: responsibility-case evidence exists at the
  recorded revision; L7 and broad capabilities are not claimed.

## Academy alignment

- The coaching Academy teaches these boundaries: practice exercises carry
  advisory authority, semantic grades are internal evaluation and never
  certification, and original failures are preserved.
