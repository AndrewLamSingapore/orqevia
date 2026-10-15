# ORQEVIA unified operational architecture

Owner master continuation orders, 15 October 2026. ABEX implements and deploys;
Dell independently reviews only. This extends the permanent interface standard.
Preserve completed work and authoritative domain ownership. No parked cloud
migration, certification or historical registry is a prerequisite for access or RAG.

## One primary interface

The existing encrypted `/pwa/` workspace is the normal operational entrypoint.
Home, Intelligence, God's Eye and owned task/evidence navigation share the
existing trusted-device identity. A public shell grants no private authority.
Private document, model, draft, construction and validation APIs require a
currently authorized OWNER with the exact bound account. Observation read scopes
remain separate from private document scopes. Session renewal, expiry, revocation,
origin checks and audit are preserved.

## Shared services and owned data

| Layer | Existing resource reused | Integration boundary |
| --- | --- | --- |
| Presentation | Existing primary PWA and browser session | Selected additive Interface files; preserved preimage |
| Gateway | Existing TLS Interface | Allowlisted owner-scoped knowledge adapter; no caller URL/tool/command |
| Geospatial | Existing internal intelligence companion and SQLite observations | Public-source retrieval, distance/radius filtering, history, provenance, authorized USGS sync |
| Documents | Existing local AI virtual environment and `documents` directory | PDF/DOCX/TXT/Markdown extraction; bounded short-lived parser worker |
| Embeddings | Existing offline Hugging Face MiniLM cache | Same 384-dimensional normalized embeddings as the preserved V2 index |
| Retrieval | Existing `rag_index_v2` FAISS index and metadata | Version-aware document filtering, exact passage hashes and scores |
| Generation | Existing host Ollama Qwen2.5:7b | Local-only constrained generation with cited untrusted passages; no tool authority |
| Cross-module context | Existing companion observation API | Gateway supplies actual USGS records; clients cannot submit fabricated observation context |
| Ideas | Shared local service metadata area | Atomic persisted owner drafts; explicit handoff to existing owned objectives |
| Construction | Existing `app/scaffolding.py` | Reviewable file candidates; never implicitly executed or deployed |
| Validation | Existing document/index regression tests | Fixed allowlisted suite in a new disposable fixture directory; no arbitrary command |
| Operations | Existing Docker services plus one loopback local-AI adapter | Owner-only health, measured release metadata, existing release workflow, recoverable index generations |

The Windows loopback adapter reuses the installed local AI environment, model
cache and original indexes. It is a shared application service, not another
workspace or an independent vector database. It is reachable from the retained
Interface through Docker Desktop's host gateway; authentication is still required.
Existing legacy-named containers remain compatibility resources. Their names do
not establish product identity, architectural authority or dependency requirements.

## Preservation and persistence

The original prototype scripts, V1/V2 index files and document corpus are copied
and hashed privately before changes. Existing V2 files remain intact. New index
and metadata generations are fully written, reopened and validated, then exposed
by one atomic pointer replacement. The previous pointer and generations provide
rollback. Failed extraction cannot truncate an existing index. Document-byte
deduplication, versioned updates and selected-source retrieval prevent accidental
duplicate ingestion and unrelated-document attribution. Superseded versions stay
preserved and are excluded from current retrieval.

Streamlit and CLI originals are retained. Only after the shared replacement is
verified may their normal paths become diagnostic clients of the shared service.
The Singapore map in the original Streamlit prototype is explicitly a demonstration,
not a live source, and is not imported into the production observation store.

## Trustworthy evidence and limits

Every answer separates retrieved source passages from model-generated
interpretation. Citation identifiers are checked against the actual supplied
passages; this does not independently prove model entailment or domain truth.
The original corpus identifies itself as synthetic PDF/DOCX test content. It can
prove extraction/retrieval mechanics, never production corpus correctness.
Real project documents require their own ingestion and source-grounding evidence.

No OCR is claimed for scanned or encrypted PDFs. Unsupported formats, parser
deadlines, model/index failures, no evidence and invalid citations are explicit.
Agent liveness, missing host collectors and provider-blocked aviation, maritime,
geopolitical or formal semantic integrations remain unavailable where unmeasured.
Source availability and a successful build do not establish runtime readiness.

## Release and final acceptance

Use task branches, current canonical references, secret/diff review, required CI,
authorized merge and the established additive Interface rollout. Preserve existing
backend, storage, tokens, TLS and rollback containers. Promote the local service
from its measured staged release; register hidden per-user startup only for the
accepted release. Keep the private data path and service authority out of frontend
code and command-line arguments.

Retain an execution ledger, item-level reconciliation register and the Owner's
20-test acceptance matrix. Mark each test PASS, FAIL, BLOCKED or NOT APPLICABLE;
never turn NOT APPLICABLE or an unreviewed historical reference into PASS.
Report implemented, tested, integrated, deployed and operationally verified
separately. No unsupported claim of exhaustive semantic recovery or 100% readiness.
