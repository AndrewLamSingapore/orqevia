# PRIME Cross-Project Contracts

PRIME is the bounded reasoning and verification layer between discovery systems and execution systems.

## Input

PRIME may ingest an `ExperimentCandidate` produced by The Portal. The candidate remains a proposal, not evidence that its hypothesis is true.

## Output

PRIME may produce an `ExperimentSpec` conforming to `experiment-spec.schema.json`.

An experiment specification separates:

- objective and method;
- evidence requirements;
- success criteria;
- safety constraints;
- target execution system;
- verification state; and
- explicit human approval state.

`verified` does not mean `approved`. PRIME's existing consequential-action boundary remains authoritative.

## Evidence return path

Execution systems such as VELYQUA may return observations/results. Those records are evidence inputs; PRIME must apply its existing grounding contract before drawing conclusions from them.

## Architecture boundary

PRIME must not import application internals from The Portal or VELYQUA. Integration occurs through versioned data contracts or APIs/events built around those contracts.

Initial lifecycle:

```text
The Portal ExperimentCandidate
        ↓
PRIME ingest + specialist routing
        ↓
PRIME verification
        ↓
ExperimentSpec (draft/verified)
        ↓
explicit owner approval
        ↓
execution system
        ↓
observations/evidence
        ↓
PRIME evaluation
```
