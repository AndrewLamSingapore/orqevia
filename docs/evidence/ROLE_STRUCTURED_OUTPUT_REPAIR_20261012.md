# Isolated normal-role output-contract repair — 12 October 2026

The prior candidate `bb99929c9e3fddd6d88a97662297dac94546978a` executed all 21
registered roles through the local model and passed three unchanged semantic
oracles. Eighteen failed. Those original tasks, outputs and receipts remain in
`outputs/role-repair-candidate` in the ABEX verification workspace.

This continuation preserves the registry, role ownership, input facts, numeric
oracles and semantic review functions. It adds explicit answer-free output
types and clarifies ambiguous task definitions: a01 selection maximizes total
value separately from efficiency; a14 duplicate indices identify repeated
occurrences after the first. This is a new task-contract revision, not a
retroactive PASS for the original prompts. Contracts contain no expected
values, examples, constants or generated answers.

The generic authenticated request accepts a bounded optional `response_schema`.
Local jobs store the canonical schema, pass it to Ollama's documented `format`
field, and check the returned object. Rejected output and actual usage are
preserved without automatic repair or replay. Unsupported schema requests to
cloud routes fail rather than silently dropping the contract. Requests without
a schema retain legacy canonical serialization and idempotency.

Strict-JSON inference supplies explicit temperature/seed defaults while
retaining configured profile values and token limits. It keeps generic
instruction safeguards separate from the user request, and records the actual
outbound payload/options/schema hashes. These hashes are execution metadata,
not signatures, authority or a guarantee of deterministic sampling. Public
receipts omit arbitrary string-bearing profile options. Owned peer review joins
the canonical schema, format, model, prompt and actual request metadata before
accepting an output for semantic review.

Source regression logs are saved under `outputs/role-competence`, including
initial failures and clean reruns. Mock transports and fixture checks are not
role competence evidence. The next actual 21-role cohort must use one clean,
pinned source revision, an isolated data domain, existing LOCAL_ONLY/$0
policy, and separate role-specific acceptance receipts.

Golden, the prior candidate source/data, existing enrollments and parked
environments are preserved. No model installation, paid inference, production
promotion, branding rollout or cloud migration is included. Rollback is stopping
only the continuation container and retaining the previous candidate/image.

The provider format follows the official [Ollama structured-output contract](https://docs.ollama.com/capabilities/structured-outputs).
