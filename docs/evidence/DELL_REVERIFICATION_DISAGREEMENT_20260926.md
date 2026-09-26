# Dell Re-verification Disagreement — 2026-09-26

Status: **INDEPENDENT FAIL PRESERVED / WRONG-ENDPOINT RECHECK REQUIRED**

Dell returned a read-only `BLOCKED — CRITICAL DEPENDENCY` result and confirmed
that it did not modify ABEX. The result is preserved rather than overwritten or
relabelled PASS.

## Dell observations

- Authority Engine still reported `prime.state = unverified`.
- Dell repeated a runtime observation of `sha-c449dd1`, schema 1.1 and 29 agents.
- Dell tested TCP ports 22, 8000, 8765 and 11434; those ports were closed from
  Dell.
- Dell did not report a test of the canonical HTTPS Interface port 8443.
- Dell assigned one P1 to unresolved runtime acceptance/deployment drift.

## ABEX primary evidence after receipt of Dell result

- PRIME and Interface are both healthy on `prime:sha-f874eab`, image ID
  `sha256:5a961ed5f3f8d06e9145b09ab4c8157fb63719f7c4770fc5f46d67e80999902c`,
  OCI revision `f874eab4f69c43bdfda7eb8a79a604eaf378a054`, zero restarts.
- The live registry is schema 2.0 with 21 logical agents and 29 historical
  responsibility mappings; runtime and source registry SHA-256 are identical.
- The intended Dell/iPhone application endpoint is
  `https://192.168.1.23:8443/pwa/`.
- Windows is listening on `192.168.1.23:8443`; a current ABEX request returned
  HTTP 200 with the PWA shell.
- PRIME internal port 8000 is intentionally loopback-only. Ollama 11434 is not
  exposed. Closed Dell access to those ports is a security property, not a
  production failure.
- Current production-lineage remote SHA is
  `2ecae11afa5d254772d90dfd9b2237a673225eab`; `origin/main` is a divergent
  development lineage, not the qualified production release.

## Resolution status

Dell's `prime.state = unverified` result is correct: no independent current
runtime receipt has yet been accepted. Dell's image/registry/drift conclusion
does not describe the current ABEX runtime and remains unresolved until Dell
tests the canonical 8443 endpoint and independently observes the current
generation.

No ABEX mutation or deployment is justified by this disagreement. One fresh
Dell recheck is required, beginning with physical reachability of the canonical
HTTPS endpoint. Dell remains free to fail that check.
