# ABEX Windows startup package

Install `Start-ABEX-Survival.ps1` and `docker-engine-probe.ps1` from the same
qualified source revision as sibling files in the stable ABEX `operations`
directory. Preserve the previous installed files and compare SHA-256 after
copying. The existing Windows Startup entry invokes the guard in that directory.

The guard resolves its bounded engine probe using `$PSScriptRoot`; it must not
depend on the legacy production checkout, a temporary worktree, or its current
working directory. An incomplete installation fails closed before any recovery
action. A healthy Docker Engine produces a no-op receipt and is not restarted.

The recovered 2026-09-27 failure was a missing installed probe dependency. The
old guard pointed into a checkout without the module and therefore never reached
its existing recovery path. The separate Windows AF_UNIX stale-endpoint failure
remains an upstream condition, not proven disk corruption. Recovery preserves
the exact ephemeral directory as a dated sibling before requesting one start;
it never resets Docker or deletes images, containers, volumes, or evidence.

Validation of this packaging repair uses PowerShell parsing, an isolated
installation with a healthy probe fixture, an incomplete-package negative test,
and the installed healthy no-op path. These checks do not prove a future
post-reboot recovery and do not require restarting Windows or production.
