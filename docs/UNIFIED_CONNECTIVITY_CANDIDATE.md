# Canonical PWA ingress — isolated candidate

This branch is not deployed. The accepted Golden Gen2 image and its data remain
unchanged. `PRIME_PWA_ORIGIN` is the browser origin and must not double as the
container health endpoint when a public domain is protected by Cloudflare
Access. `PRIME_INTERFACE_HEALTH_ORIGIN` selects the private, CA-validated HTTPS
listener; it falls back to `PRIME_PWA_ORIGIN` for the existing LAN deployment.

Observed on ABEX, 3 October 2026:

- PRIME, Interface and Ollama containers are healthy; the Interface binds
  `192.168.1.23:8443`, PRIME owner control binds `127.0.0.1:8000`.
- The current Interface certificate covers the LAN IP, not a public domain.
- `prime.lamjarvis.com` is the existing integration route, not a PWA route;
  its Cloudflare tunnel has no connected connector. No Access application for
  the PWA was observed. No public PWA route has been created.
- The ABEX runtime has no configured OpenAI API, DeepSeek API, frontier API or
  provider catalog environment variable. This says nothing about credentials
  held by Codex or another machine. Ollama lists `gemma3:1b`, `gemma3:4b` and
  `embeddinggemma:300m-qat-q4_0`; registry source validates 21 registered
  agents, not 21 simultaneously active executors.

Future rollout must use a distinct, authenticated `jarvis.lamjarvis.com`
ingress, preserve TLS verification between Cloudflare and the Interface with
the existing public CA certificate mounted read-only, and prohibit public
access to PRIME owner control, Ollama, local tools, SMB and RDP. The published
path set must be narrowed to the PWA and its bounded Interface API. Do not
start the connector before the Access policy and path restriction are verified.

The public hostname changes browser origin. Existing LAN cookies cannot be
reused on that hostname. One authorized identity transition is required;
subsequent Wi-Fi/5G changes should retain the same canonical origin. Cloudflare
Access still has a finite session lifetime, so permanent invisible login is not
an honest acceptance claim.

Promotion remains blocked by exact multi-object data rollback, host stability,
the Lexar thermal condition, and real iPhone/cellular/installed-PWA proof. A
branch test or Cloudflare DNS record does not close those gates.
