# Independent review — AI Scaffolding Engine (`app/scaffolding.py`) — 16 October 2026

Reviewer: Codex (Dell, `DESKTOP-IPV4PH9`). Reviewed at `main`
`9f2e9cac7d1b6b945cb7d7d3d288176a7ed81322`.

## Scope and method

Read `app/scaffolding.py` v1.0.0 and `tests/test_scaffolding.py` end to end,
then exercised every factory through a new end-to-end acceptance test that
materializes a project, agent and skill and runs each generated application's
own test suite.

## Findings

The engine is correctly a generator and validator only. It has no network,
subprocess, deployment or execution code paths; generated agents and skills are
`advisory_only` with no tool grants and `human_approval: required_for_execution`;
`materialize` refuses overwrite and path traversal; and generated files are
secret-scanned before they are returned.

Three defects were found and fixed:

1. `ScaffoldResult.generated_at` was a plain dataclass default evaluated once at
   class-definition time, so every result shared the import-time timestamp.
   Fixed with `field(default_factory=_utcnow_iso)`.
2. The generated project test referenced `Handler` without importing it, so a
   scaffolded project's own test would fail with a `NameError`. Fixed to import
   `PORT, Handler` and to be path self-contained.
3. The generated agent and skill tests opened their JSON using a current-working-
   directory-relative path. Fixed to resolve against `Path(__file__)`.

## Acceptance

Added `test_scaffolded_acceptance_application_end_to_end`, which materializes a
project, agent and skill and runs each one's generated pytest suite, then
asserts the fail-closed properties and that no generated file embeds
credential-like content.

Result: `tests/test_scaffolding.py` + `tests/test_fast_acceptance.py` = 18 passed.

## Verdict

The engine is fit for use as a reviewable scaffolding subsystem. It remains not
deployed and not runtime-activated; activation is a separate authority decision
and is not claimed here.
