# JARVIS Candidate Hardening — 2026-09-25

Status: **CANDIDATE — NOT DEPLOYED**

The provider-independent orchestration prompt retains JARVIS identity and applies explicit language requests before input-language defaulting. A separate governed validator rejects missing JARVIS identity, model-as-product identity, ordinary A02/responsibility prefixes and wrong-language final answers; it does not cosmetically rewrite model output.

The PWA now treats Connected as recent authoritative server evidence: protocol, authentication, expiry and a bounded verification age must all pass. Each refresh clears cached connection truth before contacting PRIME, and visible/online operation revalidates periodically. Server unavailability, revocation, expiry and protocol mismatch therefore cannot retain a misleading Connected state.

Read Aloud receives exactly `spokenText(currentTask)`, which is the same current governed result used for visible presentation. It excludes previous revisions and agent metadata and selects `zh-CN` for Chinese final text.

The atomic service-worker shell advances to `jarvis-shell-v6` and includes a standalone recovery script. If application modules fail to finish startup, the user receives a deterministic recovery message rather than an unexplained blank screen. One role-independent canonical manifest/icon set remains active.

Owner/Member identities, sessions and production data were not touched. Physical phone requalification and deployment remain separate gates.
