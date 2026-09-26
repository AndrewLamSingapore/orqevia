# Dell Canonical Endpoint Recheck — 2026-09-26

Status: **NETWORK/PWA PASS; OWNER AUTH AND RUNTIME RECEIPT PENDING**

Dell independently performed a fresh read-only check from host
`DESKTOP-IPV4PH9` at `192.168.1.17`. Dell did not modify ABEX.

## Independently observed by Dell

- Target: ABEX `192.168.1.23`.
- Canonical endpoint: `https://192.168.1.23:8443/pwa/`.
- TCP 8443 reachable.
- TLS 1.3 handshake succeeded.
- Certificate CN `192.168.1.23`, issuer `ABEX PRIME Epoch 20260919 Local CA`,
  valid until 2027-09-19. The CA was not trusted by default on Dell.
- HTTP 200 from Uvicorn with `x-prime-protocol: jarvis.interface.v1`.
- Full JARVIS PRIME Workspace shell rendered.
- PWA identity: `jarvis-shell-v7`; manifest name `JARVIS PRIME`.
- Session truth was `authenticated:false`; PRIME correctly displayed not
  connected and required enrollment.
- Bad enrollment code denied 403; unauthenticated task denied 401; wrong verb
  denied 405; invalid objective denied 422; Owner check denied 403.
- `/docs`, `/openapi.json`, `/health`, `/metrics`, `/.env`, `/debug`, and
  `/admin` returned 404; no secret leakage observed.
- Dell preserved the earlier FAIL and explicitly confirmed that the prior
  ABEX endpoint disagreement is resolved in ABEX's favour.

## Still not established

- Existing Owner authentication in the Dell browser.
- PRIME READY/CONNECTED in the Dell browser.
- Fresh Dell objective UUID, ABEX execution, and result return.
- Independent current image/registry runtime receipt.

Therefore `PRIME.RUNTIME ACCEPTANCE` remains **UNVERIFIED**. Interface/PWA LAN
reachability and security are independently verified; they are not substituted
for runtime acceptance.
