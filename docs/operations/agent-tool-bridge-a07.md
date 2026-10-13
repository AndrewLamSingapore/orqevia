# First a07 public-source specimen

This is one bounded model-to-tool-to-result specimen for the registered Evidence
Agent. It does not cover all a07 responsibilities, full 21-agent acceptance or
independent Azure L7. The driver supplies a request shape and authorized source
URL, without source contents or task answers. The actual model must generate its
own request; a malformed or out-of-scope output is retained and rejected.

The source is the official public `https://docs.python.org/robots.txt`. Retrieval
uses the existing authenticated owner bridge and guarded public HTTPS reader.
The initial inference stays local, with `allow_cloud=false`, cost ceiling zero,
no retries, and `CLOUD_PERMITTED` classification for the explicitly approved
public egress. Local execution and disclosure classification are separate.
The one feedback job uses the bridge's fixed existing local provider and
`LOCAL_ONLY` classification. There is no automatic repeat or new provider.

Before submission, root must confirm the installed source, Docker container and
immutable image identity from actual deployment receipts. Keep those receipts
outside this driver's self-report. `--deployment-confirmed` reflects that
already-required root decision; it is not a fabricated runtime receipt. The
source argument must match the installed environment. A missing image
environment pin remains an explicit external Docker correspondence dependency.

The prepared script can be staged in the confirmed owner container at
`/tmp/agent_tool_bridge_specimen.py`; scripts are not included automatically by
the current Dockerfile. Keep the original file SHA-256 and deployment receipt.
Use a dedicated directory, for example `/data/e2e-a07-bridge-20261013`.

Run these finite stages with `python -B /tmp/agent_tool_bridge_specimen.py`:

1. `--stage prepare --output-dir /data/e2e-a07-bridge-20261013` creates the
   answer-free scenario and durable state without model/tool submission.
2. After root confirms deployment, add `--deployment-confirmed`,
   `--expected-source <exact40hex>` and `--expected-image sha256:<exact64hex>`
   to `--stage submit` with the same output directory. It submits at most one
   actual local model request using a fixed idempotency key.
3. `--stage collect` with those same pins reads the original job. If it is still
   pending, poll later; no model retry occurs. A successful correctly bound
   original request can create the owner-scoped one-step bridge session and
   execute its actual public read. Original output, source bytes, source hash,
   byte count, public URL, TLS/DNS/credential boundaries and action IDs remain
   inspectable. A rejected request is never replaced with a manufactured one.
4. `--stage feedback` submits at most one result-bound local continuation after
   actual source-byte provenance checks. `--stage finish` later retains its
   original input/output, actual provider/model/attempt/cost and action readback.
   Pending, failed, unknown and partial records remain distinct.
5. Copy the complete specimen directory and independent Docker receipts to the
   retained host evidence directory. An independent reviewer then reads the
   scenario, original request/output, raw public bytes, full tool/action receipts
   and the actual synthesis. Keep the review in `independent-review.json`, with
   reviewer identity, source hashes, observed checks, failures, scope and limits.
6. Run `--stage packet` against that retained directory to create the hashed
   Azure assessment evidence manifest. It explicitly lists missing files and
   issues no signatures, credentials, Azure results or acceptance decision.

Independent review must check that the actual synthesis uses supported source
facts, preserves the retrieved URL/hash/bytes and observation time, separates
interpretation from source evidence, and treats absent publication dates,
corroboration and statistical denominators as missing. Do not substitute the
preflight browser observation for the actual agent's retrieved bytes. A completed
model response alone does not establish semantic consumption or correctness.

The finite initial chain is two inference jobs at most. Same-failure loops must
stop after three unsuccessful attempts; this driver runs no retry loop and does
not authorize another attempt. Preserve a failure first, diagnose it using its
original evidence, and require materially new evidence before any separately
authorized repeat. Interrupted bridge effects remain reconciliation work.
