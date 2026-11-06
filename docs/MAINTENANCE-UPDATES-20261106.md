# Dependency maintenance candidate - 6 November 2026

The Owner requested checking, downloading and installing available updates after
the priority repair PR488 had already merged and deployed. This subsequent batch
updates the pinned Python application, optional PostgreSQL adapter, native AI
requirements, browser tooling and same-origin map assets together. It does not
change model weights, financial permissions, authentication, transport policy or
user data. Previous images, native environments and dated receipts are retained.

Core candidates: FastAPI0.162.0, multipart0.0.33, pandas3.1.1, Wasmtime50.0.1,
OpenTelemetry1.45.2, pytest9.2.0, Ruff0.17.4 and pip26.3. Optional PostgreSQL
adapter3.3.8 can be explicitly included in the common runtime image without
selecting PostgreSQL or migrating any database. Native requirements retain the
existing FAISS capability and update Torch2.15.0/sentence-transformers6.2.0.
The already configured optional CPU ONNX runtime updates to1.31.1; model graph
bytes, hashes, thread settings and fallback choice remain explicit and retained.

PWA candidates: MapLibre6.16.0, Playwright1.64.1, pnpm12.18.0 and Node26 CI.
Playwright1.65.0 was downloaded and checked, but its publication is inside the
existing24-hour pnpm release-age floor. Select the newest eligible1.64.1 and
keep the normal frozen-lockfile policy; do not add age exclusions.
The existing closed CSP remains unchanged. Reviewed upstream CSS SHA256 is
`a90798a1953017790e590f7e1bd35ff103a8a4263972cb47290b78adf86f8c20`;
all39 image occurrences become32 unique same-origin SVG files whose decoded
bytes and hashes are checked by the packaging tests. Old6.14 source CSS and
unused icon bytes remain retained. Shell generation47 delivers the coherent
new asset set using the existing safe update protocol.

Qualification and deployment are separate facts. Candidate edits alone do not
establish acceptance. Keep actual targeted/full-suite/Ruff/browser/CI receipts
and per-role deployment versions under the protected host operation directory
`operations/resume-priority-20261106/updates/`. An unresolved Windows elevation
request does not grant an elevated token: machine updates remain staged until
normal OS elevation succeeds.

Primary release information:

- https://fastapi.tiangolo.com/release-notes/
- https://pandas.pydata.org/docs/whatsnew/v3.1.1.html
- https://github.com/bytecodealliance/wasmtime/releases/tag/v50.0.1
- https://playwright.dev/docs/release-notes

The installed CLI updates and the Owner's independent/off-device recovery,
physical phone, public ingress and broad intelligence requirements need their
own current evidence; this source batch cannot certify them.
