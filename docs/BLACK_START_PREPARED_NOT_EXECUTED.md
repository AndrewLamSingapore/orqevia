# Sovereign Black Start — PREPARED / NOT EXECUTED

This procedure is intentionally not executed during the Windows stability observation. It does not claim physical evidence.

## Preconditions

1. Windows observation is complete or the Owner explicitly accepts resetting that evidence window.
2. A durable checkpoint records host health, source SHA, immutable image digests, volume names and encrypted-secret requirements.
3. No database migration, backup, model download or other write-heavy operation is active.
4. Docker Desktop, WSL, local images, PRIME data volume, Ollama data volume and TLS material are already present locally.
5. Required secrets are referenced by variable name only; no plaintext secret appears in this procedure or its receipts.

## Isolation condition

Disconnect normal Internet access without changing BIOS, firmware, disks, partitions, EFI/BCD, TPM or Secure Boot. OpenAI, ChatGPT, Codex and GitHub must be unreachable. Local LAN access remains available for JARVIS acceptance.

## Recovery order

1. **ABEX host:** boot normally; record boot time and relevant BugCheck, WHEA, NTFS and storage events.
2. **Local prerequisites:** verify WSL and Docker Engine metadata without factory reset or data deletion.
3. **PRIME:** use the reviewed compose file and explicitly supplied immutable image identities. Never use `latest`.
4. **Identity/authority:** verify the existing trust epoch and Owner/Member separation from the authoritative local database. Do not bootstrap replacements.
5. **Memory:** open the existing governed database; verify integrity, scope and provenance before retrieval.
6. **Registry:** prove 21 registered agents and the separately documented responsibility coverage.
7. **Local model:** verify locally cached model identities; do not pull from the network.
8. **Orchestration:** submit a harmless local-only objective and preserve trace/request IDs.
9. **Queues:** prove cloud work becomes `DEFERRED_OFFLINE`; do not replay it.
10. **Local JARVIS:** verify HTTPS LAN workspace, authoritative session truth, JARVIS identity and Chinese response without cloud access.

## Acceptance checks

- PRIME, interface and Ollama are healthy with zero restart loops.
- Identity and authority are unchanged; Member cannot acquire Owner authority.
- Memory and registry integrity checks pass.
- Local inference and orchestration return a real result.
- Cloud/GitHub objectives remain durable and deferred.
- No external listener, tunnel or privacy-violating fallback appears.

## Failure capture and recovery

Preserve Docker/WSL/service logs, Windows events, container inspection, queue state and correlation IDs in a dated evidence directory. Stop after one bounded startup attempt if a persistent failure appears. Restore normal connectivity only after capturing the offline state, then revalidate authority, relevance, expiry and remote idempotency before reconciling eligible queue items.

Physical status remains **PREPARED / NOT EXECUTED**.
