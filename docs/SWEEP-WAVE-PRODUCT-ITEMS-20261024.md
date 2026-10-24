# Sweep wave: product-scope items — 2026-10-24 (marked clearly)

Owner approved the product-scope findings from sweep round 1. Implemented in
bounded, non-financial form; premium paths remain Owner decisions.

## Live web search (a06, a13, a28)

- Default: credential-free DuckDuckGo adapter, no account, no key, no cost
  (app/web_search.py). Optional Tavily path stays dormant unless the Owner
  sets ORQEVIA_TAVILY_API_KEY (app.tavily.com, free plan, no card).
- Owner-scoped endpoint: POST /api/orqevia/knowledge/websearch
  {query, max_results} under the existing knowledge boundary.
- Results are marked source data, never instructions or verified truth.

## Privacy masking (a12)

- app/privacy_masking.py masks emails, phone numbers and bearer tokens
  deterministically for exported reports.

## Platform registry (a19)

- config/platform-registry.json: curated public-safe external platform
  registry (observed, not endorsed).
- Exposed at GET /api/public/orqevia/platforms with no-store / noindex.

## Contribution ledger (a16, non-financial)

- app/contribution_ledger.py: durable internal merit counts for sweep rounds,
  coaching cohorts and reported findings. Explicitly NOT a token, no monetary
  value, no transfer, no authority. A real tokenized reward system remains an
  Owner product decision with legal/payment review.

## Competitor discovery (a17)

- scripts/competitor_discovery.py: bounded discovery report from the search
  adapter; source data only, no verified claims.

## Explicitly not done (recorded in SWEEP-FINDINGS-TRIAGE-20261024.md)

- Predictive compute scaling, SSM/MoE/VLA/privacy-model pilots, dynamic
  cross-agent assignment: PILOT-DEFERRED with entry criteria.
- Tokenized rewards with real value, email-product features: Owner decision.
