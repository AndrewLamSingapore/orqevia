# ORQEVIA wallet reality audit - 5 November 2026

## Decision

**No transaction-capable agent wallet was found in the inspected ORQEVIA runtime.** The 21 logical agents have compute accounting, not demonstrated money balances. The money-wallet implementation preserved in Git is a synthetic, disabled candidate that was never merged. This resolves the discrepancy between the owner's recollection and current deployment evidence.

**ORQEVIA can nevertheless incur external-service charges.** Historical cloud-inference and Higgsfield image jobs exist, and a cloud model remains configured. Paid API access is financial exposure even when no blockchain wallet exists. Actual provider balances, invoices, payment methods and available credits remain **UNKNOWN**; no billing/account probes were performed.

This audit performed no transactions, signing, funding, account connection, installation, production write, control change or deployment. Only sanitized report files were written in this directory. No key, seed phrase, token or credential value was exported or resolved.

## Evidence scope

- GitHub `main`: `9439c84a99eea5017e7d3caf3e0ceb7dd8ee3b84`; read through local `origin/main` after the parent verified GitHub's tip. Application files in the running backend and intelligence container were inspected independently.
- Nine live Docker services, environment-variable **names**, mount destinations, application-source term searches, installed financial-SDK distribution names, current SQLite schemas/counts, configured numeric budget ceilings and sanitized provider configuration.
- Backend: `orqevia:main-16f1587`; coaching: `orqevia-coaching:main-fe4c4e3`; intelligence: image ID `be7ac5864c58...`. Source/runtime version drift is preserved in `RUNTIME-WALLET-EVIDENCE.json`.
- 25 current backend-visible SQLite databases and intelligence `/data/intelligence/observations.db`; historical backup directories excluded from schema counts. Recursive filename searches of both mounted data volumes found no wallet/treasury/financial/payment/settlement file.
- Adjacent `the-portal` and `authority-engine` source; host Python-process identities, listening ports, finance-named scheduled tasks and the `orqevia-ai` source surface. No wallet daemon or finance-named scheduled task was identified. Browser saved-payment stores were deliberately not opened.

The audit did not inventory unrelated cloud accounts, every host file, encrypted/password-protected storage, browser extensions, WSL distributions or external devices. It establishes runtime truth within the specified inspected surfaces, not universal proof that the owner has no wallet anywhere.

## A. Wallet inventory

| Item | Classification | Owner / type / network | Runtime evidence and actual capability |
|---|---|---|---|
| Active agent wallets | **NOT_FOUND** | No identified address, payment account, currency or network per agent | No wallet/signing modules, financial schemas, financial data filenames or wallet SDK distributions found in active backend/intelligence. No receive/send/sign path or associated funding source established. |
| `sim-wallet:<agent>` | **SIMULATED**; implementation **IMPLEMENTED_NOT_ACTIVE** | Logical synthetic USD-cent account for each canonical agent; no blockchain network | Preserved `codex/financial-candidate-compat-20261012` at `0a7c936`; constructor creates wallet records only when explicitly invoked. No such module or treasury database in inspected runtime. |
| Simulator shared treasury | **SIMULATED**; implementation **IMPLEMENTED_NOT_ACTIVE** | Shared synthetic funding; source default 10,000 cents and 10,000-cent gross ceiling | Source defaults mean a simulated $100 pool, not real funds or $100 in each agent wallet. Real payment adapters unconditionally reject execution. |
| Web3 W3-01 track | **DOCUMENTED_ONLY** | Parked testnet design; original key/network/address unestablished | `repos/authority-engine/recovered-designs/W3-01-RECOVERED-DESIGN.md` expressly says original implementation, tests and chain receipts unrecovered/unknown. Historical PRIME signing authority is design text, not evidence of a live key. |
| Portal Ethereum Evidence Lab | **IMPLEMENTED_NOT_ACTIVE** in this Docker estate | Read-only Ethereum Sepolia evidence verifier | `repos/the-portal/lib/ethereum-evidence.js:12,178` supports transaction types 0/1/2 and excludes signing, submission and contract deployment. Source is present; independent Portal cloud runtime was not probed. It is not a wallet. |
| Provider usage / compute ledger | **VERIFIED** accounting; no funded wallet | Local estimates, agent/provider attribution | `/data/compute-ledger.db` contains 7,378 recorded reasoning attempts at the saved observation; `compute_events` table has 0 rows. Provider balances explicitly remain null/UNKNOWN. No receive/withdrawal/settlement function. |
| Hugging Face-backed cloud inference | **VERIFIED** configuration and historical local job records; present entitlement **UNKNOWN** | Shared external API account; no agent-owned account mapping demonstrated | Enabled classification-only `hf-gemma-nano` catalog entry; historical completed and failed cloud jobs for several provider IDs. No fresh inference/billing request or funding inquiry. |
| Higgsfield media | **VERIFIED** configuration and recorded jobs; present entitlement **UNKNOWN** | Shared owner-authenticated media integration | Enabled runtime flag; 7 `higgsfield/image/completed` rows. These are local recorded results, not invoice verification. Not registered as a tool for the 21 agents. |
| Tavily search | **VERIFIED** implemented key-gated external integration; credit balance **UNKNOWN** | Shared search-service account/plan if configured | Credential variable name exists; `app/web_search.py:79-83` selects Tavily when nonempty. Value was not inspected, no API call or balance inquiry. API may consume plan credits; no claim of actual charge in this audit. |

The full canonical identity set is `a01, a02, a04, a05, a06, a07, a09, a10, a12, a13, a14, a15, a16, a17, a18, a19, a20, a21, a26, a28, a29`. All have the same finding: **no active money wallet found**. The dormant simulator would give each `sim-wallet:<id>`; it does not assign Ethereum addresses or private keys.

The GitHub financial source checkpoint is [PR #270](https://github.com/AndrewLamSingapore/orqevia/pull/270): closed 15 October, draft, **merged=false**, head `e766462...`. The locally preserved compatible checkpoint `0a7c936` was inspected directly. The PR's historical test claims were not rerun, and neither head is represented as the current runtime.

## B. Financial capability matrix

| Capability | Today in inspected runtime | Dormant simulator / future state |
|---|---|---|
| Receive actual funds | **NOT_FOUND** | No external receive adapter |
| Send funds / withdraw / sign transactions | **NOT_FOUND** | External providers **UNAVAILABLE_UNIMPLEMENTED** |
| Agent-owned mainnet/testnet wallet | **NOT_FOUND** | W3-01 **DOCUMENTED_ONLY**; no owned address verified |
| Individual operating allowance | **NOT_FOUND** | Synthetic policy exists only in candidate; source default $5/purchase, $10/day, $50/month, shared synthetic $100 treasury |
| Model service spending | **VERIFIED** configuration and historical execution records | Requires owner-authenticated API access, cloud/disclosure opt-in and budget admission |
| Model cost ceilings | **VERIFIED** runtime numeric configuration: $2/job, $10/day shared | No per-agent monetary allocation; `provider_usage.py:60` reports NOT_CONFIGURED |
| Media spending | **VERIFIED** enabled configuration; owner-authenticated, explicit charge opt-in | Runtime $0.25/job, 3 jobs/day, 1 concurrent; estimated cap, not invoice guarantee |
| API/provider current balances | **UNKNOWN** | Source correctly returns null; account/top-up/funding not inspected |
| Earn revenue, accept payments, reinvest earnings | **NOT_FOUND** | Requires a deliberately selected and authorized future financial integration |
| Automatic authority expansion by prompt/memory | No wallet authority exists to expand; active API permissions/caps are code/config owned | Future signer must enforce policies outside agent reasoning |

Observed queue groups contain 13 `hf-gemma-nano` records (11 completed, 2 failed), additional historical qualified cloud jobs for other provider IDs, and local Ollama work. These counts are evidence of recorded provider execution, not payment receipts or current spending permission for every historical provider ID. The complete per-provider count table, rather than an inferred lifetime bill, is retained in the JSON.

## C. Security exposure assessment

No exploitable wallet vulnerability or unrestricted transaction authority was demonstrated. No adversarial production test was performed.

| Priority | Verified condition | Exposure / confidence |
|---|---|---|
| P1 | Shared authenticated APIs can invoke configured cloud models; Higgsfield API can submit paid work after charge opt-in | Compromise of existing owner-level access could consume service credit within available technical/provider boundaries. This is real-service exposure, not verified key theft. High confidence in code/config; current provider entitlement unknown. |
| P1 | Queue $10/day and media job caps are separate; Tavily source has no shared monetary-reservation check | Do not advertise the queue ceiling as an estate-wide spending ceiling. A model/media/search total is not reconciled to provider invoices. High confidence in inspected source; no overrun demonstrated. |
| P2 | No individual monetary allocations; provider balances are UNKNOWN | Owner cannot infer remaining funds or each agent's spend authority from existing cost telemetry. High confidence. Preserve honest unknowns. |
| P2 | Dormant simulator has local HMAC-protected audit/state, but no independently anchored anti-rollback proof or demonstrated Windows directory isolation | It is suitable as preserved simulation research, not a production financial control. Source/documented limitation; no attack executed. |
| P3 | Legacy “wallet,” PRIME-authority and simulated treasury prose survives in historical artifacts and provider docs | Users can mistake simulated balances for live money. Label source candidates and deployment state explicitly in the replacement interface. High confidence. |

Preserved protections include owner authentication, PWA/device sessions, data-classification checks, cloud opt-in, configured cost ceilings, idempotent submissions, ambiguous-call replay constraints, media explicit charge authorization and secret references. This audit changed none of them. Their source presence is not a full penetration-test certification.

## D. EIP-7702 applicability

**No immediate ORQEVIA delegation remediation is supported by the evidence.** No owned Ethereum address or signer was established, so no public-chain delegation lookup was possible. Delegation status is **UNKNOWN / no identified subject**, not “verified absent.” No speculative address was queried.

EIP-7702 uses type `0x04` authorizations to install a delegation indicator `0xef0100 || address`; the delegated implementation determines practical account permissions. The standard warns that delegated code can control the account, so key isolation alone does not establish safe delegation. The adjacent Portal verifier's type-0/1/2 support is not EIP-7702 verification. These technical facts were checked against the [canonical EIP-7702 specification](https://eips.ethereum.org/EIPS/eip-7702).

If a real account is later deliberately adopted, record chain/address ownership, query its public code read-only, identify and verify the delegation implementation and upgrade powers, and test scoped spending/revocation independently before granting any automated execution. Do not activate a wallet simply to make this assessment applicable.

## E. Minimal recommended financial architecture (not activation authority)

Keep current compute estimates explicitly separate from real funds. Add accurate owner-facing visibility before creating a payment system. If a demonstrated mission later requires earning or payments, select **one** external financial adapter and reuse the existing durable task/event store with integer minor-unit accounting and idempotent external references.

Represent agent budgets as scoped allocations against a shared account; avoid creating 21 funded wallets by default. An independently permissioned signer/payment adapter should enforce authorized chain/provider, recipient/merchant, asset/currency, amount, time window, aggregate limits and replay protection. Agents can prepare requests; prompts, generated code and memory must not widen those scopes. Reconcile uncertain external outcomes to the original provider transaction before any retry. Protect credentials outside agent-readable/writable workspaces. No council, approval queue or permanent financial hierarchy is needed.

## F. Prioritized roadmap

| Order | Change | Why / dependency | Estimated complexity |
|---|---|---|---|
| 1 | Wallet view states “No active financial wallet discovered”; label costs as local estimates and balances UNKNOWN | Prevent fabricated balances and confusion; reuse this inventory | Small |
| 2 | Explicitly distinguish model, media and search spending boundaries; document provider-side caps and selected cost owner | Existing queue ceiling is not estate-wide; no new service needed | Small to medium; account owner must supply authoritative provider billing evidence if required |
| 3 | Add per-mission/per-agent allocation only where actual paid workloads justify it | Use current atomic reservations/idempotency; preserve fail-closed external permission and reconciliation | Medium; independent tests before any production change |
| 4 | Choose one earning/payment use case and threat model | Real demand must precede wallet/provider choice; no financial integration selected here | Medium research; external authorization required for activation |
| 5 | Isolated adapter/signing tests with externally enforced budgets, revocation, ambiguous-result recovery and key isolation | Necessary before any real-funded pilot; simulator history is not this evidence | High; new scoped authorization required |

No financial implementation, account connection or funded pilot is authorized by this report.

## G. Evidence and uncertainty register

- `RUNTIME-WALLET-EVIDENCE.json`: dated sanitized container/source/DB observations; exact image IDs, module hashes, provider groups and numeric caps. Module scanning did not import application code or initialize stores. The six sampled active backend modules match `main` after normalizing Windows CRLF to LF; raw byte hashes are retained separately.
- `SOURCE-REFERENCES.json`: exact source revision/path/line snippets for active and dormant code. Active references include `app/provider_usage.py:17,60,65`, `app/job_queue.py:50,51,487,489`, `app/media_api.py:4,38,95`, `app/higgsfield_media.py:1312,1329`, `app/web_search.py:79-83` and `app/direct_entry.py:37`.
- `GITHUB-FINANCIAL-CANDIDATE.json`: fresh read-only GitHub PR #270 status, distinct from the inspected local compatible checkpoint.
- Dormant source `0a7c936:app/financial_simulation.py:38,80,106,127,197,426` establishes disabled synthetic wallets and the absence of live adapters; not runtime activation.
- Current account funding, invoices, provider credit balances, owner-held external wallets, private browser wallets, hardware wallets and public-chain delegation remain unverified. No access or balance claim is inferred from the presence of a secret variable name.
- Counts can advance while production runs. The report and JSON preserve their own observation times. Parent engineering/release work is outside this read-only financial audit; this audit performed no production mutation.

Reproduce the bounded, read-only Docker/schema/source observations with `python -B operations/reboot-sweep-20261105/wallet-audit/audit_wallet_reality.py`. It writes only sanitized audit artifacts beside the script. It does not re-run historical simulation tests, resolve credentials, call financial providers or issue blockchain transactions.
