> Portfolio status authority: [STATUS.md](https://github.com/AndrewLamSingapore/orqevia/blob/main/STATUS.md) in the private ORQEVIA repository. This document describes this repository only; it cannot override the canonical architecture or establish live deployment status.

# JARVIS mobile PWA

Canonical mobile/voice client for v1. This is a static, dependency-free browser client of the existing ABEX Interface Node. PRIME orchestration, provider credentials and execution remain on ABEX. Native iOS tooling is not a v1 dependency.

## Hosting contract

Serve this directory at `/pwa/` on the existing LAN-scoped HTTPS Interface Node. Serve `.mjs` as JavaScript, the manifest as `application/manifest+json`, and the icons with their image MIME types. `/pwa/sw.js` controls only `/pwa/`. Static responses must contain no personalized session data.

`PRIME_PWA_ORIGIN` remains the LAN HTTPS origin. To admit the public hostname on the same Interface Node, set `PRIME_PWA_ADDITIONAL_ORIGINS=https://jarvis.lamjarvis.com`. This setting accepts only that exact origin; an invalid value rejects PWA requests on both hosts. The tunnel must connect to the Interface Node over HTTPS and verify its CA using `/run/prime-tls/ca.crt`. The server does not trust forwarded host or scheme headers.

The paired backend supplies:

- `GET /pwa/api/session` → `{authenticated, clientId, expiresAt}`; expiry is Unix seconds.
- `POST /pwa/api/enroll` with `{code}`; a one-time code is issued through the existing local owner interface.
- `POST /pwa/api/logout` revokes the HttpOnly Secure session.
- `POST /pwa/api/owner-authority-check` is a side-effect-free server authorization proof: Owner receives the explicit capability; Member receives HTTP 403.
- `POST /pwa/api/uploads` with raw bytes and URL-encoded `X-Filename`; TXT/Markdown/JSON only, maximum 1 MiB. Returns `{artifactId, sha256, bytes, reference}`.
- Existing `/interface/v1` routes accept the session cookie; the server supplies client identity internally. Every POST carries `X-Jarvis-PWA: 1`; the browser supplies Origin for server validation.
- Objective submissions carry `uploaded_artifact_ids`, at most four. The backend verifies ownership/integrity and appends the UTF-8 text as labelled untrusted evidence within its 80,000-character combined context limit. The UI does not claim arbitrary binary analysis.

No browser bearer-token storage, provider API call, caller-selected authority, or frontend cloud credential exists. HttpOnly session cookies are not read by JavaScript. Enrollment codes are cleared immediately after submission and are not persisted.

## Recovery and integrity

The task view offers **Follow up on this task** for a completed task with a server revision. This explicitly switches the composer from a new objective to a continuation of that same task ID. Typed text and reviewed browser dictation use the same path. **Switch to new objective** returns to the normal composer. Attachments are disabled in continuation mode because this route does not yet ingest uploads.

`POST /interface/v1/tasks/{id}/continue` sends only `objective`, empty optional `context`, `expected_revision` and `idempotency_key`, with the matching idempotency header. The stored retry record includes the target task and frozen expected revision; an uncertain retry never silently adopts a newer revision. Successful acknowledgment must keep the same task ID and advance revision. A 409 requires reconciliation instead of automatic replay or a new task. Results and agent status are filtered to the current server revision before applying display bounds. Older in-memory text is shown only in a separate Previous result region labelled with its revision while a later turn is pending; it is never reused as the latest completed answer or speech output. Latest-result artifacts are highlighted first while all historical file links remain. History keeps a single reference to the shared task.

IndexedDB persists only client-scoped task references, timestamps/state and an objective digest/request key plus attached artifact IDs. An atomic transaction retains the pending request key together with the returned task ID and history. Objective text, result bodies, files and session secrets are not persisted there. To recover an uncertain objective, enter its original text; stored upload IDs and the same request key are reused. A changed objective is blocked while an earlier submission has no acknowledgment.

The task view fetches bounded SSE snapshots, then retrieves owned status/results on changes. It commits its cursor after processing and retrieves artifacts at terminal state. Network retries are bounded; HTTP conflicts, authorization and integrity failures are not blindly replayed. Background/offline transitions stop monitoring and audio. Foreground/reconnection resumes the selected task with a fresh cursor. Recent task references are browser-local; Open task ID supports another owned/explicitly owner-linked task when authorized by the server.

Uploads are independently SHA256-checked against the backend receipt. Downloads are released only after Web Crypto verifies byte count, metadata digest and digest response header. Interrupted or corrupted downloads never become a saved file. Responses are size-bounded and require the Interface Node protocol header/media type.

The service worker caches only an exact allowlist of public shell files. API responses, sessions, uploads, results, query variants and non-GET requests bypass its cache. Offline mode is a shell/recovery state, not offline execution.

## Voice and installation

Dictation begins only after a visible consent dialog explains that the browser may send audio to its own speech provider. Unsupported/denied speech access has typed-input fallback. Dictation stops after 60 seconds, on Stop audio, backgrounding or going offline. Transcribed text is reviewed before the ordinary objective submit button is pressed. Returned results are spoken only after Read aloud; no additional orchestration layer exists.

On iPhone, open the trusted LAN HTTPS URL in Safari, enter the device enrollment code, then Share → Add to Home Screen. Launch it, send an objective, verify/save its file and disconnect/reconnect to retrieve the same task. Browser speech/installation behavior depends on device support; the physical phone acceptance step remains separate evidence. No Mac, Apple developer membership or native signing is required.

## Executed portable validation

```sh
node clients/pwa/tests.mjs
```

11 tests cover retry identity, result selection, bounded SSE, retry bounds, cookie/CSRF request shape, artifact corruption, task/protocol mismatch, safe error presentation, offline-cache scope, atomic-storage source and explicit voice consent. All 11 passed on the available Windows runtime. Browser and physical-phone acceptance are performed separately against the integrated backend; these Node tests do not claim microphone/device qualification.

Focused candidate continuation tests: `node clients/pwa/followup-tests.mjs` — 6 passing tests for terminal/revision preconditions, exact request schema, task/revision-bound retry identity, wrong acknowledgment rejection, non-retried conflicts and explicit composer/voice integration. These are not a deployed or physical-device acceptance claim. The shell cache version is incremented for the updated composer/core assets.

`make-icons.mjs` reproduces the included geometric PNG icons without external assets or dependencies. It is not required at runtime.

