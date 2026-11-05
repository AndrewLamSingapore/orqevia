# ORQEVIA transformation batch - 5 November 2026

This batch replaces the supported interface, removes active legacy execution
dependencies, and adds native discovery and bounded experimentation. It does
not claim that every research ambition in the Owner's four missions is complete.
The complete directives and custody hashes are in
[owner-missions/2026-11-05](owner-missions/2026-11-05/README.md).

## Verified baseline

At boot, nine Docker services recovered. Backend/interface used main 16f1587,
coaching fe4c4e3, and intelligence sgscope-v1; GitHub main was 9439c84. Verified
HTTPS returned 200. Shutdown admission generation 12 was explicitly resumed to
OPEN generation 13, with database snapshots retained. The preserved a02 job
completed with its original identity. No new background admission pause is part
of this release.

The ABEX PC has an eight-core/sixteen-thread Ryzen 7 PRO 8840HS and approximately
32 GiB RAM. The Radeon display adapter is observed; GPU inference, dedicated
VRAM, NPU performance, thermal headroom and SSD throughput are not qualified.
The passive production sample recorded no swap activity and about 6.9 GiB Linux
available memory. This is an uncontrolled production observation, not evidence
that the new software improves throughput.

## Implemented interface and design

`clients/shared/tokens.css` is the sole active token source. The reference is
NOMAD revision 54ee30a44902e5c252b477f8685c26ec3064ab72: background #f7eedc,
panels #424420, headings #2a2a15 and panel text #f6f6f4. Its source uses the
system sans stack, compact bold headings, two-pixel tile borders, four-pixel
corners and a responsive one/two/three-column grid. ORQEVIA uses an original
geometric mark and native outline icons. No NOMAD logo, framework, Docker socket
exposure, authentication bypass or extra vector database is introduced.

The canonical surfaces are Command Center, Intelligence, Agents, Missions,
Knowledge, Workspace, Assets, Wallets, Live Systems, Evolution, Console and
Settings. Projects, cache repair, public pages and the map use the same identity.
Old view queries canonicalize to these surfaces; the old control renderer and
proxied intelligence HTML/scripts/styles are retired. Authenticated APIs and
owned-task Evidence Lens functions remain available through the new Console.
Existing sessions and recovery data remain valid.

No user-selected screenshot was attached to this session. Source fidelity and
desktop/mobile rendering can be verified; exact comparison against that missing
image cannot be claimed. Browser fixtures and live runtime acceptance are
separate evidence categories.

## Runtime simplification and retained protections

The supported direct task path no longer requires PRIME environment aliases, a
global `os.getenv` monkeypatch, an enablement flag for agent dispatch, automatic
copying from historical spine/memory databases, a mandatory manager graph, or
subordinate-product/portfolio status records to pass source integrity checks.
The archived operational manifest, generated JARVIS checkpoint, old signatures
and old source bytes remain dated evidence. Capability identities and artifact
hashes remain checked; source integrity is not a claim of deployed qualification.

The 21 current capabilities remain available on demand. The registry is an
inventory; no permanent six-lead reporting graph is required at startup. Direct
dispatch continues to use existing model routing and measured resource controls.
Authentication, ownership, same-origin checks, external-action authorization,
host-effect boundaries, spending ceilings, idempotency and recovery remain.
There is no replacement council, approval organization, executor or universal
queue. Durable inference scheduling remains necessary for fairness and the
single measured local slot.

## Capability assimilation

- Adapted: NOMAD's compact command dashboard and manifest-driven discovery.
  `config/capability_depot.json` describes existing implementations without
  importing arbitrary code. OWNER-authenticated metadata separates installed
  source from observed runtime health and functional qualification.
- Retained: existing FAISS document retrieval, local Ollama, memory/notebooks,
  PIF, MEL, Academy, resource guardian and offline continuity. Their current
  limitations remain visible.
- Adapted: service/version/rollback clarity through one common Python release
  image, separate service containers, host probes for shell-less services and
  an independently networked, CA-verified TLS telemetry collector.
- Rejected: transplanting AdonisJS/MySQL/Redis/Qdrant solely to match NOMAD;
  unauthenticated LAN administration; browser Docker-socket access; mutable
  automatic installs; duplicate notes or memory stores.
- Investigate only for actual missions: Kiwix/ZIM packs, PMTiles offline regions,
  CyberChef and other utilities. Disk, license, freshness and maintenance costs
  must justify each addition.

The Supply Depot is currently discovery and truthful operational metadata.
Arbitrary web installation/removal and unreviewed third-party package execution
are not implemented. Install/update/rollback retain the existing host release
pathway. This limitation is explicit in the API and interface.

## Wallet reality and costs

No active transaction-capable agent wallet, signer or wallet database was found
on the inspected runtime. Simulated USD-cent wallets exist on a closed,
unmerged candidate, not the deployed system. No funds, balances, signing,
EIP-7702 delegation, funding source or autonomous payment capability is inferred.
External model/media/search API usage can incur charges independently of wallets.
The existing provider budgets are not a demonstrated estate-wide cost ceiling.
The financial audit made no production or financial changes and recommends a
separate technically enforced payment capability only if future needs justify it.

## Evolution experiment and architectural alternatives

The native experiment compares arrival FIFO, an independent priority heap and
the existing exact scheduling tool. Candidates receive inputs only. A pinned
oracle, disjoint development/held-out inputs and predeclared selection rule
prevent changing success criteria through the request. The exact tool and heap
passed eight of eight held-out priority-semantics workloads; FIFO passed two.
This does not mean FIFO failed to physically finish jobs, or prove higher live
throughput, better model cognition, generalization to real missions, or AGI.

The fixed API accepts no caller code, evaluator changes or permission changes.
It records observations, hypotheses, experiments and results as immutable JSON
in the existing data directory. It does not change production routing or spawn
a service. CPU/wall observations accompany the result; coarse clocks and the
small synthetic suite limit performance conclusions. This is a bounded method
comparison prototype, not an untrusted self-modifying agent containment system.

The audited alternatives are: minimal direct tool/model execution; temporary
task-specific parallel teams using the current coordinator; and decentralized
capability workers over existing durable state. The latter two need empirical
benefit before adding communication or state complexity. Current evidence favors
reusing the exact tool for the bounded scheduling problem; it does not establish
one universally best intelligence architecture. The next cycle should evaluate
independently withheld representative missions and compare useful correctness,
latency, CPU/RAM and cost before any new routing promotion.

## Release and recovery

The batch includes the two previously unpublished benchmark fixes, atomic
single-job qualification reservation, and the pypdf 6.21.4 security update.
Qualification holds only its own finite-lease job; production admission is never
paused. Existing private inference/retrieval transports are preserved. The
telemetry network migration updates both endpoints together and verifies TLS;
retired port 8081 stays retired.

`deploy/Dockerfile.unified-runtime` builds one artifact for backend, interface,
coaching and intelligence while retaining service isolation. The prior runtime
image and configuration backups remain rollback assets. The existing intelligence
container is preserved stopped under a dated name; its data volume is reused.
No user data, models, historical signatures or rollback images are deleted.

Validation and final deployment receipts are recorded by the ABEX session under
`operations/reboot-sweep-20261105/` and the canonical workspace handoff. This
source document describes implementation scope; it is not a fabricated CI or
deployment receipt. Reversible rollback restores the dated runtime configuration,
recreates the affected Compose services using their prior images, and restarts
the preserved intelligence container with its original mounts and networks.
Never restore an old database over newer accepted work without reconciliation.

## Remaining work and limits

Independent clean-host/off-device restore acceptance remains unqualified; the
Owner's earlier offline-backup maintenance item is still recorded. The five
historical probability-assessment numeric failures are not repaired by changing
UI, routing metadata or the unchanged grader. No new role certification,
unrestricted financial authority, universal offline service availability,
autonomous arbitrary code evolution or architecture-wide intelligence gain is
claimed. The detailed evidence inventories and selected deferred capabilities
remain part of the mission backlog.

## Attribution

Project NOMAD by Crosstalk Solutions is the source/design reference, inspected
at the pinned revision above under Apache-2.0. The repository declares no custom
font files; ORQEVIA uses system fonts and original brand assets. No NOMAD program
stack or protected brand assets are distributed in this implementation. Existing
third-party dependencies keep their upstream licensing. The reconnaissance
records inspected licenses and limitations; a new full transitive license and
vulnerability certification is not claimed.
