# Independent toolkit review

This review ran in the cloud Linux workspace. Its results are **PROVEN_BY_AUTOMATION** for synthetic gate and observer behavior. They do not establish installation or execution on the physical Dell, an authenticated ABEX connection, successful promotion, or physical iPhone audibility.

The review agent did not repair candidate source or ABEX production. The agents owning the local verifier and observer corrected the toolkit defects; the review agent reran unchanged reproductions. Historical failing runs remain alongside successor runs.

## Corrected verifier defects

- A post-promotion deployment drift failure still exposed `PROMOTION_VERIFICATION_PASS` in the current top-level gate. Historical approval is now separately labeled; the current gate fails closed.
- Post-promotion reports omitted additional physical gates, unproven claims and longer-observation gates. These are now retained from approval and deployment contexts.
- Post-promotion findings did not receive the same evidence validation and severity reporting as candidate findings. The shared validation now preserves those checks.

Five independent regression cases pass, including refusal of candidate-supplied JSON as a trusted run, missing finding evidence, and retention of the physical iPhone acceptance gate after software success.

| Run | Result | Code SHA-256 |
| --- | --- | --- |
| `run-642f6764051949a9b092a8be842da13f` | Two failures reproduced | `0a1c64e43aacf1530ae7a1079d69a841e43f159653286b6e8473c560cd66a3e4` |
| `run-8ce6ad6b526b4850b85f267bcff04352` | All five cases passed | `861af6b27089db0b69c40e862996dcafff708c7d1ebe982e6cd5ce0a7d7df014` |

## Corrected observer defects

- Malformed host-binding JSON could raise an uncontrolled attribute error. The observer now rejects it through a controlled blocked result.
- A blocked observation lacked the `status` field used by successful status documents. Blocked attempts now have consistent status, durable fresh evidence and the last successful observation timestamp.
- Static review identified a source-copy integrity gap in the Windows installer; installed bytes are now compared with the selected release digest before execution.
- Static review identified output limits applied only after unbounded subprocess capture. Stdout is now streamed under a bounded budget and stderr is discarded.

Two independent failure regressions pass after correction. Windows scheduling, credential behavior and native host probes remain untested here.

| Run | Result | Code SHA-256 |
| --- | --- | --- |
| `observer-run-333ead2c43c14d68850e11cd7f2341fe` | Two failures reproduced | `f278747fa5903ed3edb8d95deddf13ab6d0b1674f17fb7f461623a80ec4332b3` |
| `observer-run-7d2901358fb447ee987010f0f2fa6c42` | Both cases passed | `8b4e51a3c7c8cc1f5de4aca8f21ee2db1c2deefe0379e49dc5d725ecb97b75fc` |

Each run directory preserves the tested source, test source, stdout, stderr and a digest receipt. These are integrity records, not signed attestations or WORM storage.

## Operational boundaries

- The offline gate CLI cannot issue an independent Dell PASS from untrusted manifests or imported success-shaped JSON. Its typed API is a documented trust boundary for a future trusted runner, not authentication of such a runner.
- The current evidence-store backend requires POSIX descriptor-relative no-follow I/O. Native Windows evidence storage requires a separately reviewed implementation or a supported isolated POSIX environment.
- The passive observer watches remote refs; it does not qualify a candidate or create promotion authority.
- A read-only shell sandbox does not constrain every remote MCP connector. The initial native Codex launcher inherited existing configuration. The final launcher now blocks before starting Codex or decrypting a credential, with no bypass flag. Actual Dell effective configuration and isolation still require local verification. `Start-DeepSeekPacketReview.ps1` supplies a separate exact-file advisory route through isolated Python invocation: dry run does not decrypt credentials, and the explicit send path restores the prior API-key environment. This helper has no model tools and does not inherit Codex connectors. The Windows wrapper received static review only.
- Software speech API callbacks cannot close physical iPhone audibility. Owner observation remains required for that physical gate.

Run independent regressions from the package root with `python -m unittest discover -s review -v`.
