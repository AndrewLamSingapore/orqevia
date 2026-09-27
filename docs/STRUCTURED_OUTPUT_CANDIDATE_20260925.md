# Strict structured output candidate — executed evidence

Classification: **CANDIDATE — NOT DEPLOYED**

Base: router candidate `e423ebad60aa2124287edeb23c813678cc784de2`

## Raw model truth

Unconstrained benchmark truth remains unchanged:

- `gemma3:1b`: strict JSON failed.
- `gemma3:4b`: strict JSON failed.
- Raw model structured output remains **DEGRADED**.

With native Ollama schema constraints and temperature zero, both models returned parseable, schema-shaped JSON in 3/3 attempts. The results were not equivalent:

- 1B: parse 3/3, schema 3/3, semantic evidence 3/3.
- 4B: parse 3/3, schema 3/3, semantic evidence 0/3 because it invented a specific dependency-X security vulnerability absent from the prompt.

Schema compliance is therefore necessary but insufficient.

## Governed control layer

The candidate accepts data only after:

1. bounded size check;
2. strict JSON parse with duplicate-key and NaN/Infinity rejection;
3. explicit supported-schema validation;
4. required/type/enum/range/nested/additional-field validation;
5. caller-supplied independent semantic verification;
6. at most one bounded repair followed by complete revalidation.

Only a standalone Markdown JSON fence may be normalized automatically. Prose surrounding JSON is ambiguous and rejected. Unsupported schema keywords are rejected rather than ignored. Invalid output returns `VERIFY_REQUIRED`, contains no trusted value, and grants no tool authority.

## Adversarial coverage

Valid and Chinese JSON, malformed/truncated input, fences, prose, wrong types, missing fields, extra fields, invalid enums, duplicate keys, non-standard constants, nested violations, prohibited null, oversized content, prompt-injected tool fields, semantic range violations, fabricated causes, broken semantic verifier, one successful repair and one failed repair.

Independent verifier: `scripts/verify_structured_output.py`.

Machine-readable live evidence: `docs/evidence/structured-output-constrained-20260925.json`.

Production data, models, routing, tools and authority were not changed.
