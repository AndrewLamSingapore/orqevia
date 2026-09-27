# Dell, Codex and DeepSeek integration

Prepared on 2026-09-27. **Prepared files are not proof of installation on the physical Dell.** This execution environment is a Linux workspace; no physical Dell session, ABEX connection, credential, model call, or Windows runtime test was available here. ABEX remains the only production authority.

## Supported connection

Current OpenAI configuration documentation allows the Responses protocol for custom providers. DeepSeek now documents native Responses support and a Codex connection. This package therefore uses `https://api.deepseek.com`, `wire_api = "responses"`, and `deepseek-flash`; it does not need a Chat Completions translation proxy. The named profile uses current separate profile-file syntax, requiring Codex 0.134.0 or later. An older Dell client must be assessed before use.

The official compatibility guide says DeepSeek treats the `developer` role as `user` and ignores several unsupported parameters and built-in tool types. Its provider model has no right to authorize tools, promotion, evidence qualification, or physical acceptance. Put those boundaries in the verifier and OS permissions. Successful API communication does not establish full Codex tool compatibility or model reliability.

Sources checked on 2026-09-27:

- [OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [OpenAI profiles and advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- [OpenAI CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [DeepSeek Responses compatibility](https://api-docs.deepseek.com/guides/responses_api/)
- [DeepSeek Responses API reference](https://api-docs.deepseek.com/api/create-response/)

## Physical Dell setup

Use a dedicated standard Windows reviewer identity with no production SSH keys, ABEX administrative credentials, deployment tokens, writeable production shares, or inherited production MCP connections. Before launching Codex, inspect that identity's configured MCP servers, hooks and integrations and remove ABEX mutation capability from that identity. This is an operating-system/access-control requirement: a named Codex profile alone cannot enforce it, and a read-only filesystem sandbox does not authorize or constrain every external connector.

Place the package in a Dell-local directory. A local Codex session can perform the remaining setup and check installed versions and sandbox behavior; it must retain any existing configuration and failures. The credential helper prepares the bounded API route. Installing the named native profile is optional preparation and does not enable its launcher:

```powershell
cd C:\JARVIS-DellPeer\integration
.\Set-DeepSeekCredential.ps1
```

The credential helper asks for the key in a hidden local prompt and saves a Windows DPAPI-encrypted credential for that Windows identity and machine. It makes no network request. The exact secret is never placed in the profile or command line. Processes under that same Windows identity can decrypt it; DPAPI is not isolation from malicious same-user processes. Protect the account and keep candidate tests in their separate sandbox without the credential or its directory mounted.

`Install-ReviewProfile.ps1`, if used later, refuses to overwrite an existing named profile. No helper installs software, changes machine execution policy, disables security controls, schedules a background task, opens a listener, changes firewall rules or connects to ABEX.

Prepare a small local review packet containing only material permitted for DeepSeek review. Exclude secrets, session databases, personal conversations and production exports. Keep the packet and output on local disk without symlinks, junctions or mounted production paths. Sending it invokes DeepSeek and may incur API charges.

**Native Codex launch is BLOCKED in code.** `Start-DeepSeekReview.ps1` stops before starting Codex or reading a key. A read-only shell and a named profile can still inherit remote MCP, app, hook, plugin or managed configuration capable of mutating ABEX. This package cannot prove their absence on physical Dell, so it provides no bypass switch or self-attestation marker. A local implementation may replace this blocked launcher only after independently verifying the full effective configuration, disabled mutation paths and Windows sandbox with preserved receipts. Model prompts and caller-provided booleans cannot supply that proof.

The supported prepared route is `Start-DeepSeekPacketReview.ps1`: it calls the bounded Python helper directly, inherits no Codex tools, and executes no model-generated commands. Existing Codex on Dell may invoke this helper as an advisory service. The wrapper keeps the credential in process memory only for the request, restores the prior environment afterwards, and uses Python isolated mode. This leaves the existing Codex defaults and `CODEX_HOME` unchanged.

## Exact-file advisory API helper

`deepseek_review.py` uses Python's standard library. It sends no content until `--send` is present. It reads one bounded UTF-8 file, verifies its supplied SHA-256, and holds those exact bytes in memory before sending. It uses a fixed HTTPS endpoint, rejects redirects, ignores environment proxies, performs no retry, and caps output size and requested tokens. The socket inactivity timeout is 60 seconds; this is not a strict wall-clock job deadline.

Example on Dell with Python installed and a synthetic/non-sensitive packet first:

```powershell
$packetPath = 'C:\JARVIS-DellPeer\review-packets\approved\review.txt'
$packetDigest = (Get-FileHash -LiteralPath $packetPath -Algorithm SHA256).Hash.ToLowerInvariant()
python .\deepseek_review.py --input $packetPath --input-sha256 $packetDigest --candidate-sha FULL_FROZEN_CANDIDATE_SHA
```

That command is a dry run and does not inspect credentials. For convenient use of the locally saved DPAPI credential, replace the candidate placeholder with the actual full frozen SHA and run:

```powershell
.\Start-DeepSeekPacketReview.ps1 -PacketPath $packetPath -InputSHA256 $packetDigest -CandidateSHA FULL_FROZEN_CANDIDATE_SHA
# Add -Send to the same exact command to transmit that packet.
```

The wrapper also defaults to dry-run without reading a key. With `-Send`, it decrypts the locally saved key and passes it to Python in the process environment. Do not put a key in shell history. The candidate SHA is a binding claim in this helper, not independent proof of source integrity; the core Dell verifier must establish that separately.

Every attempted send gets a new local artifact directory with request/input hashes. Completed advice is labeled `UNPROVEN` and `ADVISORY_ONLY`; it cannot award a promotion PASS. Failures produce `REVIEW_UNAVAILABLE`. Model-generated tool calls are never executed. Raw reasoning/provider bodies are not retained; the exact response digest and retained advisory digest are recorded separately. The original submitted packet must be preserved separately in Dell evidence if reproduction requires it. Hashes alone do not authenticate an artifact or make it immutable.

## Convenient ABEX cooperation without shared authority

ABEX publishes frozen source, manifest, image identity and candidate evidence through the approved candidate channel. Dell consumes them with read-only credentials. Dell publishes sanitized verdicts/reproductions through a separate outbox that ABEX can read. Keep Dell's historical evidence, challenge suite, keys and verifier configuration outside ABEX's write access. No network share, webhook or remote-control service is enabled by these helpers.

ABEX may read a Dell FAIL and produce a successor candidate. It cannot update Dell's tests, verdicts or historical artifacts as part of that candidate. DeepSeek findings are hypotheses until Dell reproduces them. Software speech events remain software evidence: Owner physical iPhone observation is required to close audible speech acceptance.

## Validation state

Offline Python boundary tests can run with `python -m unittest discover -s integration -p test_deepseek_review.py` from the package root. They cover accidental transmission, digest changes, redirects, tool output, incomplete/malformed responses and preserving prior artifacts. No live API success is claimed. PowerShell helpers and Codex configuration are prepared and statically reviewed; they have not run on Windows here. Native launch remains BLOCKED, and permanent observation is not activated by this integration package.
