# Acceptance evidence and gate repair

This candidate follows the owner's sections 43–54. This document and the
acceptance inventory are reporting artifacts, not frozen architecture or a
replacement operational source of truth.

Use only PASS, PASS_WITH_NON_BLOCKING_LIMITATION, BLOCKED or NOT_APPLICABLE for
phase status. A passing development fixture is not a phase PASS when real
integration/hardware evidence is required. No phase in the present inventory
has all required acceptance evidence. In particular, production remains HOLD.

Generate current evidence after the full suite, using disposable test data:

    python -m pytest -q --junitxml=work/acceptance-tests.xml
    python scripts/build_acceptance_matrix.py --junit work/acceptance-tests.xml --output work/acceptance-evidence

On Windows, set PRIME_DATA_DIR, PRIME_SPINE_DB and PRIME_COMPUTE_DB to writable
disposable paths before importing the application. The application otherwise
uses its container data paths. Failure to set these is a test-run configuration
defect; it is not grounds to skip fixtures or request access to the drive root.

The builder reports all 31 required acceptance items, all 13 phase gates, exact
JUnit identities, missing/nonpassing fixtures, failure classification, remaining
limitations and whether Lam has an immediate action. It rejects empty,
inconsistent and duplicate JUnit evidence, refuses unresolved phase promotion,
and never treats a skipped fixture as a pass. Its zero exit means reporting
succeeded, not that production or a phase passed. Evidence labels remain
IMPLEMENTED/FIXTURE_TESTED where supported. Existing hosted container evidence
is separately INTEGRATION_TESTED against a synthetic provider, not HARDWARE_TESTED.

Current substantive gaps include positive inference-need evidence beyond the
four exact contracts, full bounded service supervision/rollback, the autonomous
owner interface versus the frozen read-only ceiling, and qualified bootstrap
adapters. These are not hidden behind the unavailable ABEX. The four Companion
specifications and unresolved Web3 tier policy remain external dependencies.
Cloud execution is NOT_APPLICABLE only within the frozen disabled-cloud pilot.
The incomplete full mandate must not be labeled IMPLEMENTATION COMPLETE.

A gate failure is classified before repair. Fix implementation/configuration
within authority, rerun the failed fixture and affected regression tests, and
preserve the authority/security assertions. Never alter an expected security
result merely to obtain green tests. Source/fixture success cannot promote
production or authorize consequential integration.

The status probe was corrected to apply the existing Harness signing-secret
length and pilot-switch parsing rules without constructing a runtime or
exposing secret values. New tests compare the observation with actual Harness
configuration acceptance. A real SQLite queue fixture also verifies that
outage/recovery events persist before safe resume without invoking inference.

No new action is requested from Lam for the already-known unavailable hardware
and artifacts. Independent work remains permitted; dependent gates remain
BLOCKED. The final installed-system guide and real operator simplicity review
remain pending.

