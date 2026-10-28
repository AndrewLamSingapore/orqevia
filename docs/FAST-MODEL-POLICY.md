# ORQEVIA fast-model policy

## Superseded - 28 October 2026

The current [model-selection policy](MODEL-SELECTION-POLICY.md) supersedes the
exclusive defaults and model-name exclusions below. These dated instructions
describe prior operation and are retained as history. No model or provider is
mandatory for every ORQEVIA task; select a qualified capability for the task.

## Standing default

- Use the fastest complete path that preserves the required evidence and
  authorization checks.
- Fast work uses `gemma3:1b`.
- Higher-capability local work uses `gemma3:4b`.
- `model_reasoning_effort = "max"` remains the default for Codex sessions.
- Do not select or install multi-gigabyte slow models such as
  `qwen2.5:14b-instruct-q4_K_M` or `qwen2.5:7b-instruct`.
- The 4.7 GB and 9 GB Qwen models were removed from the active Ollama runtime on
  20 October 2026.

## Change control

A new model may replace these defaults only after a focused comparison shows
that it is faster or materially more capable at an acceptable latency, followed
by an isolated acceptance run. Do not change models midway through a workflow,
because mixed-model output would invalidate the run's consistency and cost
evidence.

## Provider rules

Codex uses the authenticated ChatGPT provider with maximum reasoning. Direct
DeepSeek configuration is rejected because Codex requires a
Responses-compatible gateway; ORQEVIA's separate DeepSeek adapter uses the
provider-specific `/chat/completions` endpoint.

## Recovery

Runtime model selection is persisted in the release environment file and in
container environment. The user startup task restores a safe ChatGPT
configuration if the Codex configuration regresses. Model-registry history is
retained, but no slow model remains active or installed.
