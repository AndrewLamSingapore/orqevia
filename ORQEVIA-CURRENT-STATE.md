# ORQEVIA source state - 6 November 2026

The current source uses direct capability handoffs, one logical ORQEVIA
coordinator and the existing service roles. The capability inventory preserves
the 21 existing identities and all 29 owned responsibilities without a lead or
reporting hierarchy. Tool selection grants no new execution or financial rights.

The supported application entrypoints are `app.production_entry:app` and
`app.interface_server:app`. Desktop and mobile share the verified HTTPS origin
at `/pwa/`. The former standalone server and extra desktop/Pocket renderers are
retired. Their original bytes remain in `docs/history/` and Git history.

Read [the consolidated sweep](docs/ESTATE-SWEEP-20261106.md),
`system.manifest.json` and `deploy/product-runtime-v1.json` for current source
contracts. Source validation checks hashes, identity and ownership. It does not
certify agent competence, runtime health, hardware or an external deployment.

The ABEX host's actual state and private operational receipts live outside this
repository at `C:/Users/Admin/Documents/ABEX/ORQEVIA-CURRENT-STATE.md` and
`operations/resume-priority-20261106/`. Use its latest checkpoint, not dated
shutdown instructions. Current runtime revisions must be observed at the host.

Preserve user data, models, secrets, HTTPS, trusted sessions and rollback
evidence. Wallet investigation remains read-only. REA and MiroFish remain
excluded. Use one consolidated branch/PR and one verified cutover per batch.
