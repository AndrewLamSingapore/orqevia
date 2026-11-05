# Local source qualification before release

This document records source validation, not deployment or live qualification.
The original logs and receipts are preserved on ABEX under
`operations/reboot-sweep-20261105/`.

## Python regressions

The full Windows run recorded 7,132 passes, 21 skips, 3 deselections and eight
failures. Those eight were outdated assertions about deliberately replaced
branding, routes, source-only contracts and the removed dispatch enablement
flag; their expectations were updated and checked with focused regressions.
Authorization checks were retained. Separately discovered implementation issues
in service-worker asset caching and modern-cookie logout were corrected and
tested, including cross-device and conflicting-cookie rejection.

The independent full Linux run recorded **7,137 passes, 11 failures, 19 skips,
3 deselections and 102 passing subtests**. It ran offline in an isolated retained
image with 2 CPUs, 2 GiB RAM and no production mounts, models or credentials.
The 11 failures were diagnosed individually:

- Two Dell packaging cases and one independent verifier lacked Node.
- Five dependency-closure cases needed test packages in actual site-packages;
  a parent-only PYTHONPATH did not reproduce a normal Python installation.
- The multiprocessing case needed a standard module entrypoint rather than an
  stdin-based pytest launcher.
- The historical dry run needed its exact preserved, non-branch-reachable
  source commit. Its original closure and oracle checks were not changed.
- The frozen SVG needed Git attributes preserving its original hash bytes
  across Windows/Linux checkouts. The logo and expected hash were unchanged.

After installing the verified official Node archive, completing the isolated
Python test installation, using `python -m pytest`, restoring the exact Git
objects and fixing the SVG attribute, **all 11 previously failing cases passed**
in one focused rerun (52.73 seconds). The source revision for that rerun was
`120e7e40b3dc2125d4618bfb8fbacca1d5a480b8`.

This is a full run plus a focused repair rerun, not a claim that another full
7,148-case run was performed. No failing test was disabled to obtain this result.
Skipped tests and unavailable external/live environments remain explicit limits.

## Interface

The frontend unit suite passed 114 cases. The main 34-case browser suite passed
on Chromium, Firefox and WebKit (102 cases). Focused Projects/error-recovery and
metric-clipping regressions also passed on all three engines. Thirty desktop
and mobile source-preview images cover the major surfaces. There were no body
overflows or JavaScript errors in the final captures. The absent user-selected
reference screenshot prevents an exact visual comparison claim.

Actual production screenshots and authenticated live workflows require a later
deployment receipt. Source-preview images are labeled accordingly.

## Security, integrity and scope

Focused tests cover OWNER-only discovery/experiment access, strict empty-body
experiments, owned-task Evidence Lens access, same-origin/CSRF checks, credential
isolation, modern session/device revocation, atomic finite qualification leases,
TLS collector identity and shell-less service probes. Existing financial ceilings
remain. Registry bytes and historical signatures were preserved.

The source-integrity scan checked 1,770 tracked files and found no configured
secret-pattern matches. This is a scoped scan, not proof that every dependency
or historical artifact is vulnerability-free. Ruff baseline and changed-file
gates passed; final CI must verify the consolidated committed tree.

The bounded scheduling experiment uses separate development and held-out cases
and a frozen independent oracle. Eight of eight held-out semantic checks passed
for both the existing exact solver and independent heap, versus two for FIFO.
This does not establish improved live throughput or general intelligence.

The read-only financial audit did not create a wallet, move funds, sign anything,
change financial controls, or activate a provider. Source and runtime findings
are separated in its detailed report.
