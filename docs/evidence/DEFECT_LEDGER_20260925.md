# Defect ledger — preserved closure record

| Defect | Discovery / impact | Root cause and repair | Repair SHA | Executed retest | Current status |
|---|---|---|---|---|---|
| governed-memory SQL insert mismatch | focused durability test failed; writes unusable | SQL/value contract corrected and integrity coverage added | `8b7dbe997c85bb21135d536b585867283c661ceb` | memory focused + verifier + canonical/full | REPAIRED-CANDIDATE |
| verifier import/entrypoint defect | verifier could not execute independently | repository-root bootstrap/entrypoint repaired | `8474bf217f8542611c1c6efee2a0629f37e40d45` | independent verifier + canonical/full | REPAIRED-CANDIDATE |
| Windows SQLite handle leakage | Windows cleanup failed and obscured dependency tests | connection lifecycle made explicit | `ffd96b1` historical production-line repair; candidate evidence `020f9754114f8af7facb2961c23bbc44fa68d5c7` | six-scenario verifier + canonical/full | REPAIRED-CANDIDATE |
| schema-valid fabricated model evidence | plausible structures could be mistaken for truth | exact authoritative semantic matching; unsupported claims remain VERIFY_REQUIRED | `8474bf217f8542611c1c6efee2a0629f37e40d45` | adversarial semantic + cross-domain + canonical/full | REPAIRED-CANDIDATE |
| JARVIS explicit-language precedence | explicit user language could be overridden | orchestration precedence and response contract fixed | `566e56a79456febf17111b7ced6cfd55a8dfc07c` | 42 focused; PWA 33/33; verifier 7/7; canonical/full | REPAIRED-CANDIDATE, NOT DEPLOYED |
| stale Connected/session truth | PWA local state could display stale connectivity | authoritative refresh, expiry/version handling and bounded revalidation | `d5123f4` production history; hardened in `566e56a79456febf17111b7ced6cfd55a8dfc07c` | PWA/session focused + verifier + canonical/full | REPAIRED-CANDIDATE |
| missing deterministic PWA startup recovery | stale assets lacked a predictable recovery surface | versioned shell/recovery script/message and cache lifecycle tests | `566e56a79456febf17111b7ced6cfd55a8dfc07c` | PWA 33/33; verifier 7/7; canonical/full | REPAIRED-CANDIDATE, NOT DEPLOYED |

Warnings retained: Starlette `BlockingPortal` and legacy FastAPI `on_event`
deprecations remain non-critical technical debt. They are not justification for
an observation-period production redeploy.
