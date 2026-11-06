# Priority resume - 6 November 2026

The Owner explicitly resumed all work in priority order after restarting ABEX.
The existing nine production services and local/LAN HTTPS passed 19 boot checks.
Background admission moved from the observed PAUSED generation14 to OPEN
generation15 through the existing generation-checked CLI. Two accidentally
auto-started historical intelligence rollback containers were stopped and their
restart policies set to `no`; containers, images, volumes and evidence remain.

The first authenticated live acceptance reached 106 checks and failed its full
integrity assertion under resumed writers. This failure is retained. A new
deterministic regression reproduced the same false failure with an independent
SQLite writer. Full verification now starts an explicit read transaction before
structural checks, audit replay and materialized-record comparisons. WAL writers
still commit during replay; a subsequent check detects committed tampering.
Routine dashboard reads remain light and honestly report NOT_CHECKED.

Automatic objective routing now selects one active owned capability from a
reviewable task-term manifest. It no longer imports the old DOMAIN_CHILDREN
authority tree. Direct dispatch records only the actual executing identity;
project assignments use their accepted workflow as origin, without delegated
authority. Assignment persistence is atomic and preserves any pre-existing
partial assignment history. No external-action permission changes follow.

The existing `status-authority` CI job now verifies product source integrity;
canonical release suites no longer require archived portfolio/operational
manifest semantics. Historical validators, tests, documents and records remain
available explicitly. Product integrity, authentication, execution boundaries,
source provenance and security tests remain active.

Recovery tooling now fails on foreign-key violations or expected row-count
mismatches, returns a failing CLI exit status, and refuses to overwrite backups
or retained restore destinations. Reports read one SQLite snapshot. The optional
`restore-test --destination` preserves an independently inspectable restored copy.
Fresh sequential online snapshots of 28 production databases passed quick checks
and copied hashes. They are individually consistent, not an atomic estate backup.

Qualification and deployment are distinct. The candidate has targeted passing
results; full regression, CI, merged-image deployment and final authenticated
and browser acceptance must each have their own receipts under
`operations/resume-priority-20261106/`. Nothing in this document certifies an
undeployed candidate or the completion of the four long-term missions.

Only one physical internal disk and no mapped independent recovery destination
were observed. A same-host isolated restore can qualify data recovery in scope;
it cannot qualify disk-loss recovery, clean-host DPAPI portability, a physical
iPhone or public ingress. Optional old APIs and reporting metadata remain dated
compatibility code. The specialized 21-task project template remains opt-in;
general automatic routing uses one capability. Broad unseen cognitive improvement,
generic depot installation/removal and authoritative provider balances remain
separate evidence requirements. Wallet work remains read-only; REA/MiroFish stay
excluded and port8081 remains retired.
