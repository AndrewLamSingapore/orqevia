# Unified ORQEVIA design system — 5 November 2026

Implementation: `clients/shared/tokens.css`, `clients/pwa/style.css`,
`clients/pwa/projects.css`, `clients/pwa/command-map.css`, and
`clients/public/assets/site.css`. Shared tokens are the only palette and
typography authority. The other sheets contain layouts for their surfaces.

## Verified reference and visual limits

Project NOMAD revision `54ee30a44902e5c252b477f8685c26ec3064ab72`:
`admin/inertia/css/app.css`, `pages/home.tsx`, `layouts/AppLayout.tsx` and
`admin/public/docs/dashboard.webp`. The upstream dashboard image was inspected
alongside the replacement desktop/mobile captures. The Owner-selected image was
not attached to this conversation, so exact matching to that image is unverified.

| Purpose | Token/value | Reference/implementation |
|---|---|---|
| Page | `--oq-bg: #f7eedc` | NOMAD desert-sand |
| Functional panel | `--oq-panel: #424420` | NOMAD desert-green |
| Panel text | `--oq-panel-text: #f6f6f4` | NOMAD desert-white |
| Heading/ink | `--oq-text: #2a2a15` | NOMAD desert-green-darker |
| Card/detail surface | `--oq-surface: #fffcf4` | Native warm-white adaptation |
| Secondary surface | `--oq-raised: #eee4cf` | Native ivory adaptation |
| Secondary text | `--oq-muted: #5a593f` | Native high-contrast olive adaptation |
| Outline | `--oq-line: #424420` | Same olive as functional panel |
| Radius | `4px` | Small geometric corners |
| Font | system UI sans stack | Upstream declares no custom family/font assets |
| Code/logs | system monospace stack | Local fonts; no external font service |

No NOMAD logo, trademark treatment, downloaded font or icon package is shipped.
The geometric ORQEVIA mark and simple inline line icons are native assets.
Seven install/favicon PNG sizes were rasterized from the original SVG; old
images remain preserved in source history and are not the current manifest.

## Components

- Command Center: centered original 132px geometric mark, bold compact heading,
  3-column grid at 1024px+, 2 columns at 640–1023px, 1 column below 640px.
  Tiles have 2px olive outlines, 192px desktop height, 48px line icons, 24px
  headings and concise descriptions. Mobile tiles are 168px high.
- Navigation: capability tiles at home; compact horizontal page navigation on
  desktop; five fixed accessible mobile targets and a scrollable full menu.
- Buttons/forms: 44px minimum target; solid olive primary actions; outlined
  secondary actions; visible focus; disabled state reflects existing permissions.
- Detail cards/tables/logs: warm-white surfaces, small corners, clear outlines,
  source/freshness metadata, wrapping long hashes and labels, no decorative glow.
- Modals: native accessible dialog elements with opaque ivory surfaces and
  bounded scrolling. Account, voice-consent and task-recovery behavior is retained.
- Notifications/status: explicit loading, unavailable, offline, source-only and
  error states. A registered capability is not labelled live/qualified by default.
- Maps/charts: the existing MapLibre geography tool is retained with matching
  ivory/olive fills and controls; source attribution and compact-device lazy
  startup remain intact. No decorative new map service was added.
- Motion: no decorative animation; reduced-motion preferences are respected.

## Route and capability mapping

| Canonical view | Functional surface |
|---|---|
| `home` | Command Center and mission draft shortcut |
| `intelligence` | Model/memory observations, planning, geographic/integration tools |
| `agents` | Existing agent capability/activity/provenance projection |
| `missions` | Owned objective submission, continuation, recovery, results/artifacts |
| `knowledge` | Existing owner-scoped documents, local retrieval and cited answers |
| `workspace` | Ideas, candidate construction, fixed checks, service/release metadata, export |
| `assets` | Manifest-driven source/runtime capability inventory |
| `wallets` | Read-only audited financial capability; funds never inferred from usage |
| `live-systems` | Real service/hardware/work observations and freshness |
| `evolution` | Learning/evaluation, fixed comparison and saved experiment evidence |
| `console` | Existing fabric/collective operations and explicit Evidence Lens actions |
| `settings` | Connection, recovery and consequential action permissions |

Projects/notebooks and the cache-repair page use the same shared identity.
Public pages use the same design and contain no private operational data.
Server authentication and scoped APIs enforce public/private separation.

Old view query names resolve to these canonical views. They cannot select an old
layout or theme. The retired theme endpoint is inert for installed-client
compatibility; there is no appearance switch or alternate palette. The former
PWA overlay sheets contain retirement comments only and are not linked by the
new shell. Original frontend bytes and their hashes are preserved outside the
served tree in `../frontend-before/`.

## Acceptance evidence

See `VISUAL-ROUTE-RECEIPT.json` and `screenshots/` for the desktop/mobile route
captures and measured widths; see browser logs for actual interactions.
These are explicitly labelled source previews with API fixtures. Live runtime,
physical iPhone installation and deployment receipts are separate parent-session
responsibilities. Visual consistency does not prove model quality or runtime
capability activation.
