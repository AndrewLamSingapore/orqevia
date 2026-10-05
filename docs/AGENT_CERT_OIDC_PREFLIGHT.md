# Independent verifier OIDC preflight (candidate)

The two workflow files are deliberately **not** a certification signer yet.
The manual caller runs only on canonical `main`, requires GitHub to report the
ref as protected, and calls the reusable signer from `@refs/heads/main`. The
reusable signer accepts no caller-supplied code or inputs, checks the caller
again, and checks out no repository files. Only the signer jobs may request an
OIDC token. No Azure identity, federation, Key Vault permission, or signing
operation is introduced by this change.

After merge, run the caller once on `main` only after verifying branch
protection (including whether administrators can bypass). Its log prints only
selected claims, not the token. Capture the actual `sub`, repository and owner
IDs, `workflow_ref`, and `job_workflow_ref`. Do **not** infer the subject from
the repository name: GitHub can use an immutable ID-based subject. Only then
create a separate Azure federated credential matching those observed claims
and the main-pinned reusable signer. The future signer must independently
decide each case before it is allowed to ask Key Vault to sign the exact digest;
an OIDC login by itself cannot certify an agent.

Read-only GitHub UI inspection on 4 October 2026 found no classic branch
protection and no ruleset for this private repository. The Owner's billing
page showed GitHub Pro at $0/month, so private branch protection is available
on the current plan, but it is not currently configured. This workflow must
fail closed until an effective `main` protection rule is separately installed
and verified, including its administrator-bypass behavior. Azure signing
access must not be granted on the strength of a main-branch name alone.

References: [GitHub OIDC claims](https://docs.github.com/en/actions/reference/security/oidc),
[OIDC with reusable workflows](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows),
and [branch-protection availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
