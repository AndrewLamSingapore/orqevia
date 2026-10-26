# Controlled verification evidence

`ci-receipt.json` records all nine successful checks for source `7e45a56dd1125bb73168cff238bed7cc0acfd5ec`.
The canonical Linux suite passed 5,909 tests, with one existing skip and 92 passing subtests.

The local verifier passed all 41 Factory tests against that clean source revision.
`controlled-verification.json`, `acceptance.xml` and `source-files.json` bind the
test command, outcomes and exact tested file bytes. `reference-outputs.json` and
`reference-events.json` export actual controlled workflow results and trace events.
No transient test CA private key or production credential is included.

Qualification admission in these Factory fixtures is explicitly synthetic.
These receipts establish controlled component integration, not a07 qualification,
live deployment, physical reboot or production readiness. The separate 65-test
a07 source checkpoint is unintegrated and is documented in the status register.

The subsequent evidence/documentation commit changes no runtime, test, schema,
configuration or skill implementation bytes from the verified source revision.
