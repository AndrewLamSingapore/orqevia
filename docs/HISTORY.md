# Historical recovery

Historical architecture, 29-agent registries and old workflows are preserved in
Git history, not duplicated in the active tree. The pre-unification main revision
is fd90ea15604473b0ade8cc2278176a36a0b658ab and the integrated candidate revision is
bd11e2373894f9d8806d6aaf1e3557cb8823c0f7. These are recovery references, not current
instructions. Current status authority is STATUS.md; governance/operational-manifest.json
is retained as a machine-readable component reference only.


## September 16 public alignment

The old `COMPUTE.md`, `DEPLOYMENT.md` and `governance/OPERATIONAL_BASELINE_v1.md` redirect stubs are removed from the active tree. Use `docs/ARCHITECTURE_V1.md`, `deploy/product-runtime-v1.json` and the canonical operational manifest. Their earlier content remains available in Git history.

Historical Dell image/revision evidence now lives under `systems.prime.historical_dell_release` and `dell_runtime`; it no longer fills current PRIME runtime fields. The public JARVIS showcase replaces the old external J Console and local-control links.
