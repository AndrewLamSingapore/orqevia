# Dell Read-Only Runtime Re-verification — Handoff

Dell is requested to independently verify; it is not instructed what result to
return. Dell must not modify ABEX.

## Claimed current identity to challenge

- ABEX address: `192.168.1.23`.
- HTTPS PWA: `https://192.168.1.23:8443/pwa/`.
- Production lineage remote SHA:
  `44b261e241a2e951626e1c5c28c466e8c620d623`.
- Running revision: `f874eab4f69c43bdfda7eb8a79a604eaf378a054`.
- Image: `prime:sha-f874eab`.
- Image ID: `sha256:5a961ed5f3f8d06e9145b09ab4c8157fb63719f7c4770fc5f46d67e80999902c`.
- Registry: schema `2.0`, version `1.0.0`, 21 logical agents, 29 historical
  responsibility mappings, SHA-256
  `fec92b1d0e3e858bc5f4fe1b26401d053ee94b9b2358be8da379b97884d916ff`.
- Interface host identity: `ABEX`; Interface revision `f874eab...`; candidate
  status `PRODUCTION`.
- Authority Engine revision:
  `a4134f155f7b7f0e560e692a947234b3f9610828`.

## Verify independently

1. Confirm the evidence document exists remotely at the production-lineage SHA
   and recompute its Git identity.
2. From Dell, confirm the real TLS endpoint and PWA assets are reachable at the
   stated address; distinguish TLS/reachability from PRIME authentication.
3. Verify the presented certificate/trust path is the adopted ABEX identity.
4. Use Authority Engine `/jarvis` and **Open my JARVIS workspace**; confirm it
   resolves to the stated ABEX PWA, not a cached or alternate endpoint.
5. Confirm no direct public access to PRIME internal API, Ollama, databases,
   Docker, or Windows management.
6. If an existing Owner session is available, confirm authenticated READY state,
   submit one fresh harmless objective, record its fresh UUID, and verify the
   result returns to Dell. Do not create another Owner or re-enroll silently.
7. Compare the observed production image/revision and registry identity with the
   claims above using Dell's independent evidence source. Do not accept ABEX
   self-report alone.
8. Return a signed or otherwise attributable non-secret result containing:
   verifier identity, observed timestamp, observed ABEX endpoint, source SHA,
   image ID, registry hash/schema/count, Interface identity, checks performed,
   PASS/FAIL/PARTIAL per check, evidence references/digests, and discrepancies.

## Rollback identity to verify, not execute

- Immediate prior image: `prime:sha-a1ea9ad` /
  `sha256:076c6c4cdf21066e6b1029850bef186697f2aedcde6fc0a493c65d68b293b144`.
- Earlier image: `prime:sha-0ecb580` /
  `sha256:e59c43c885dd07bd2b037e8c7281b999749c3f54cba76a9bff95ce1de7e13d6c`.

Dell must remain free to disagree. A page load, ARP entry, HTTP 200, source SHA,
or ABEX-generated document alone is not independent runtime acceptance.
