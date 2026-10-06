# Independent verifier: protected canary and certification handoff

Source checked: PRIME `main` `a265693034a87961c73e9e47cf7dcaa78e872b09`
(6 October 2026). This records the source boundary; a workflow run and current
repository protection must be checked separately before making a live claim.

The manual caller in `.github/workflows/prime-verifier-oidc.yml` requires a
protected `main` ref and calls the reusable signer from `@main`. The reusable
workflow checks the caller and checked-out SHA, requests its own OIDC token,
and runs two Azure Key Vault ES256 canaries. The versioned public P-256 key is
pinned in `governance/agent-cert-verifier-azure-pins.json`. The OIDC claim and
token exchange checks are in `scripts/azure_verifier_live_canary.py`; the
reviewed A18 observation is a fixed, synthetic, non-certifying fixture in
`scripts/azure_verifier_observation_canary.py`. Neither workflow accepts a
caller-supplied case, artifact, signing digest, or code.

These canaries establish only their stated cryptographic and observation
checks. This revision contains no protected workflow that independently
reviews and signs an official live agent certification case, no signed case
record, and no certification registry projection. A passing canary must not be
counted as an agent's L1-L7 result.

## Handoff for the first official A19 case

1. Run the registered A19 challenge against the exact source revision that
   certification will project. Preserve the full challenge, authenticated
   dispatch identity, queue/job lineage, raw worker result, fixed oracle
   verdict, observation time, and SHA-256 of the execution artifact. An
   observation on a feature revision remains scoped to that revision.
2. In protected code, independently check the exact case and source-bound
   oracle against those bytes. Write a distinct review artifact naming a
   reviewer other than A19 and the executor, with its run ID, source revision,
   case, execution digest, review version, observations, and PASS/FAIL verdict.
   A claimed reviewer name or an agent-supplied digest is insufficient.
3. Only after PASS, verify both artifact digests and the exact record fields,
   then request Key Vault `sign(ES256, SHA-256(record bytes))` with the pinned
   versioned key. Check the returned key ID and ES256 signature against the
   pinned public key. Keep the OIDC bearer and signing operation inside the
   protected job; agents and callers must not gain signer access.
4. Store the signed record and both immutable artifacts under the subject's
   evidence directory. Project them with a public-key verifier and the same
   source revision, then have an independent clean-room auditor reproduce the
   case verdict and tamper rejection. Repeat the required cases and owned
   capabilities before claiming an agent's level.

The `ProtectedAzureES256Signer.sign_reviewed` and
`AzureES256CertificationVerifier` source on the separate L7 candidate branch
defines part of steps 3-4, but neither is on this `main` revision. Its
digest-only `sign` path is for non-certifying canaries. Integrating the reviewed
path still requires a protected case-specific oracle, live receipt, durable
evidence delivery, and public projection. Do not route a live case through the
digest-only path.

Read-only GitHub UI inspection on 4 October 2026 found no classic branch
protection or ruleset at that time. Treat that as historical evidence: check
effective protection, including administrator bypass, at the run being
qualified. The current workflow denies signing when GitHub does not report
the ref as protected. Do not infer protection from the branch name.

References: [GitHub OIDC claims](https://docs.github.com/en/actions/reference/security/oidc),
[OIDC with reusable workflows](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows),
and [branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
