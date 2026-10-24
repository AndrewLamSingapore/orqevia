# HTTPS browser defaults

The Windows operator opens `https://localhost:8443/pwa/` for the `open` action
and after a successful `start` or `update`. The ready message uses that same
workspace URL. `-NoOpen` continues to suppress browser launch. The HTTPS
interface and its trusted local certificate must already be configured; the
operator does not bypass certificate validation or fall back to HTTP.

The operator's private backend health and control checks still use
`http://127.0.0.1:8000`. Docker-private service traffic and the host inference
and knowledge adapters retain their existing transports. Migrating those paths
to TLS requires separate certificate, client-trust and end-to-end verification.
This browser-default change does not establish HTTPS for every internal hop.

Existing certificates, mobile trust profiles, session storage and historical
verification records are preserved. Retiring the legacy HTTP bootstrap listener
on port 8081 is a separate deployment action, with HTTPS profile delivery and an
offline first-trust route retained for new devices. Source changes alone do not
prove that a running listener has been retired.
