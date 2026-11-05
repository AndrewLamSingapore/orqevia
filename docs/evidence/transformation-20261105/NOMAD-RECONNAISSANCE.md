# Project NOMAD source reconnaissance — 5 November 2026

Scope: source inspection, not an installed NOMAD service or measured performance comparison.
Pinned upstream revision: [54ee30a44902e5c252b477f8685c26ec3064ab72](https://github.com/Crosstalk-Solutions/project-nomad/tree/54ee30a44902e5c252b477f8685c26ec3064ab72).
The complete tree returned 754 entries without truncation. Selected actual source files are preserved in reference/.
Latest published stable release observed through the upstream GitHub API: v1.35.1, 5 October 2026. main is the source baseline, not an assertion that it equals that release.
Orqevia comparison baseline: origin/main 9439c84; the parent session independently owns live runtime verification.

## Visual system verified from source

- admin/inertia/css/app.css: Tailwind 4 theme; sand background #f7eedc; green panels #424420; darker heading green #2a2a15; white #f6f6f4; related green #353518, #babaaa and #d4d4c8.
- admin/inertia/pages/home.tsx:269: one column, two at sm, three at lg; 16px grid gap/padding. Tiles at lines 287–311 use 192px height, 2px outlines, small rounded corners, 48px icons and bold 24px labels.
- admin/inertia/layouts/AppLayout.tsx: centered 160px logo and bold 48px Command Center heading; compact internal-page option has a 48px logo and 24px heading. Thin green rule separates header and content.
- admin/inertia/app/app.tsx, admin/inertia/css/app.css and admin/tailwind.config.ts declare no custom font family or downloadable fonts. The inspected tree contains no font files. Typography uses Tailwind's system sans default, not a verified proprietary typeface.
- admin/package.json pins @tabler/icons-react 3.36.1. DynamicIcon.tsx resolves that icon package; simple outline geometry is native to the reference.
- Current NOMAD includes optional dark mode and arbitrary link-tile colors. Those conflict with the Owner's requested single ivory/olive identity and are not adoption candidates.
- The user-selected screenshot is absent from this conversation. Source fidelity can be verified; exact screenshot fidelity cannot. Upstream supplies admin/public/docs/dashboard.webp as a useful independent reference, not the Owner-approved image.

## Capability comparison and disposition

| Discovery | What source actually implements / assumptions | Orqevia equivalent and disposition | Dependencies, security, maintenance and measurable value |
|---|---|---|---|
| Command Center | home.tsx, AppLayout.tsx: curated installed-app tiles, visible install/update state, straightforward tools | ADAPT. One native shell and design system; retain existing authenticated handlers | No need to introduce React/Inertia/Adonis. Measure navigation success, mobile overflow and critical workflow completion |
| Supply Depot | supply-depot.tsx, models/service.ts, services/docker_service.ts, database/seeders/service_seeder.ts: curated + custom Docker services, lifecycle/logs/preflight/ports/dependencies | ADAPT. Manifest-driven catalog over existing service and tool inventory; do not grant reasoning unrestricted Docker access | Docker socket confers host-level power. custom_app_guard.ts blocks system/socket mounts and malformed images, warns on moving tags/outside storage. Use scoped host operations, digest pins, rollback and measured resource budgets |
| Reference appliance stack | management_compose.yaml: Node/Adonis/Inertia app, MySQL, Redis/BullMQ, updater, disk collector, optional Dozzle | REJECT direct transplantation. Existing Python services/SQLite/coordinator already work | Adds permanent databases, queues, Linux assumptions, broad socket/mount authority and default HTTP. No demonstrated Orqevia benefit |
| Local Ollama | ollama_service.ts, ollama_compute.ts: local/compatible backend detection, streaming/cancellation, token budgets, model install/removal and GPU discovery | ALREADY PRESENT; ADAPT context budgeting/cancellation diagnostics if benchmarked superior | Orqevia compute_catalog/provider runtime/HOME_ECO already route local/cloud, bound budgets and preserve models. Never copy model-removal defaults into this estate |
| Offline ZIM/Kiwix | kiwix_catalog_service.ts, zim_service.ts, zim_extraction_service.ts, service_seeder.ts: OPDS catalog, archives, local library and ingestion | INVESTIGATE targeted knowledge packs; useful addition where a real offline mission exists | Native libzim/Kiwix service, large disk use, update/license/provenance tracking; do not duplicate documents or download large collections without value |
| Qdrant RAG | rag_service.ts, rag_pipeline_service.ts: per-collection retrieval, provenance, relevance floors/checks, source citations, token-aware context; incremental ingestion state | ALREADY PRESENT conceptually in local_knowledge.py, local_knowledge_service.py, rag_grounding.py; ADAPT tested relevance/freshness patterns; REJECT extra vector service absent measured advantage | Qdrant 1.16 + embedding runtime + content pipeline. Compare held-out answer correctness, source validity, indexing cost, retrieval latency and disk footprint against existing store |
| RAG evaluation | tests/eval/README.md and eval_retrieval_service.ts/eval_generation_service.ts: separate retrieval/generation quality evaluation and corpus | ADOPT pattern; construct independent Orqevia held-out tasks, do not train on evaluation answers | Evaluation fixtures are not production evidence. Preserve independent oracles and baseline resource metrics |
| Hardware/benchmark | system_service.ts, benchmark_service.ts, benchmark_telemetry.ts: CPU/memory/disk/AI channels, model/hardware attribution, v2 raw channels + score | ALREADY PRESENT Resource Guardian/measured profiles/passive observer; ADAPT transparent channel presentation | Linux sysbench helper and selected model downloads inappropriate by default on ABEX. Measure useful jobs per CPU-s, latency, RAM floor and contention; reject arbitrary composite leaderboard as capability evidence |
| Setup wizard | easy-setup/index.tsx, easy_setup_controller.ts, collection_manifest_service.ts: content tiers, storage projection, service prerequisites | ADAPT automatic environment discovery; show only unresolved material choices | Avoid a second setup on an already operational estate; defaults must come from observed hardware and installed capabilities |
| Updates/recovery | auto_update_service.ts, app_auto_update_service.ts, content_auto_update_service.ts, system_update_service.ts: checks/windows, dry-run helpers, sidecar update | ADAPT version/status and recoverable dry-run patterns; retain existing one-batch release | Do not copy unattended mutable latest tags, updater host writes or restart semantics without tested recovery; existing deployment/CI remains simpler |
| Download/content state | download_service.ts, collection_update_service.ts: progress, retry/cancel, resource status and content freshness | ADAPT progress/freshness metadata, resumable bounded downloads | Code contains destructive cancellation cleanup; this estate must preserve data/models/evidence instead |
| Maps | map_service.ts, Maps UI, PMTiles/MapLibre: offline regions + markers | ALREADY PRESENT geographic observations/MapLibre; INVESTIGATE offline PMTiles only for geographic missions | No decorative dashboard map; respect region storage/license/update costs and provenance |
| CyberChef/data tools | service_seeder.ts: containerized CyberChef and IT Tools | INVESTIGATE mission-specific tools; expose catalog metadata first | Separate upstream code/licenses; input isolation; avoid distributing secrets into third-party pages |
| Notes/files/e-books | Flatnotes, File Browser, Calibre Web and document utilities in service_seeder.ts | REJECT duplicate notes/file stores by default; existing workspace/notebooks/artifacts/knowledge remain primary | Filebrowser catalog uses persistent roots separated from secrets but ships known appliance defaults; retain Orqevia authentication and scoped filesystem roots |
| Education/media/radio/inventory/passwords | Kolibri, Jellyfin, Meshtastic, MeshCore, Homebox, Vaultwarden catalog entries | INVESTIGATE only if concrete mission and resource fit; REJECT automatic installation | Many extra services/ports, different licenses and update surfaces; most are irrelevant to current intelligence tasks |
| Creator packs/docs | creator_pack_service.ts, collection_manifest_service.ts, collections/creator-pack-license.md and docs_service.ts: catalog manifests, pack metadata, local manuals | ADAPT content manifests with source/license/freshness/size; ADOPT local task documentation pattern | Creator-pack metadata license is separate from underlying videos/content. No rights to all downloaded content follow from NOMAD's app license |

## Security and supply-chain findings

SECURITY.md explicitly states Command Center authentication is absent by design, trusted LAN is the boundary, and direct public exposure is unsupported. That posture is incompatible with Orqevia's HTTPS paired/owner-scoped access. Do not copy the unauthenticated controller routes.

install/management_compose.yaml binds the admin and updater to Docker's socket, exposes 8080, uses mutable latest images for core services and mounts the host filesystem read-only into a disk collector. No part of this design is a reason to weaken Orqevia's existing credential isolation, permissions, transport or financial boundaries.

LICENSE is Apache-2.0 (copyright Crosstalk Solutions, LLC); admin/package.json also declares Apache-2.0. The source tree snapshot has no separate NOTICE file. If code is reused, preserve the license and any relevant notices and document modifications. The Orqevia implementation should be a clean native adaptation; no NOMAD brand/logo is needed.

Dependency metadata was inspected, not installed. admin/package.json + package-lock requirements must remain upstream evidence; do not copy the dependency stack into Orqevia. Direct component licenses and any fonts/icons actually distributed must be verified at the pinned versions before distribution. A full transitive license/vulnerability review is not claimed.

## Smallest defensible assimilation

1. Replace the shell and all active styles with one shared ivory/olive token source, native geometric Orqevia logo, simple line icons and responsive 3-column Command Center.
2. Keep existing APIs/session/mission/documents/agent notebooks/fabric functions; eliminate duplicate theme systems and old navigation surfaces.
3. Present installed capabilities and real service readiness through a data-driven Supply Depot; do not implement arbitrary Docker execution in the browser.
4. Reuse existing retrieval and Resource Guardian. Test relevance/freshness and transparent resource presentation before adding storage or scheduling dependencies.
5. Publish independent outcome/latency/resource receipts; no capability or performance improvement is established by this reconnaissance alone.

Implementation and deployment are owned by the parent session. This report is the discovery evidence, not a completion claim.
