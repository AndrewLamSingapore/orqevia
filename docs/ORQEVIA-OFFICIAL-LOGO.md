# Official ORQEVIA logo source and technical icons

The logo is the untouched owner-approved raster at `assets/brands/orqevia/generated-original.png`, imported from `AndrewLamSingapore/orqevia` commit `f03ce95d1752f316bca92257b0f7349a48863472` on `brand-master-register-2026-10-10`. Its SHA-256 is `b3bdd53cc38b24c8be2896f1174b4d5f083be20f94f2042770224c72e2501844`.

Andrew Lam's earlier brand register records the approved white rounded-square background, metallic blue orbital O, champagne-gold sweep/star and bilingual wordmark. The following owner-authored commit uploads the original binary. The register's older “not yet uploaded” sentence is preserved as historical text. No verified vector master exists.

`assets/brands/orqevia/provenance.json` records original custody and each derivative. `scripts/build_official_logo_icons.py` uses Pillow **12.3.0** as a build tool to resize the **full RGB image** with Lanczos. It preserves the source proportions and opaque background; there is no cropping, recoloring, redrawing or reconstructed SVG. The runtime has no Pillow dependency.

```sh
python scripts/build_official_logo_icons.py
python scripts/build_official_logo_icons.py --check
```

The output sizes are 192/512 for the app manifest, 180 for Apple touch and 16/32/48 for favicons. Manifest purpose is `any`; the full wordmark layout has no accepted maskable safe-area variant. Current images use `object-fit: contain` without tint or clipping.

The PWA uses versioned `orqevia-official-v1-*` PNGs and shell `orqevia-shell-v20`. Installation downloads the complete public shell before adoption. Private APIs and client reference storage remain outside that cache. Existing app scope, cookies, enrollment, routes and data are retained. Old icon URLs remain available for compatibility and history; the generated Q icons are unapproved substitutes, not official masters. The old `make-icons.mjs` entry point fails with the original-asset workflow instead of redrawing them.

Existing Core/control HTML serves only the allowed derivative filenames through its current local authorization boundary. The legacy local HTML uses the same fixed public logo assets. API response identities and role prompts are unchanged.

This change covers the primary ORQEVIA PWA and existing local HTML surfaces. The public showcase linked from README lives in the independently owned Authority Engine repository; linking to it does not update its deployment or other consumer products.

Source asset, HTTP delivery, installed home-screen refresh and physical device acceptance are distinct checks. Keep the original installation and session until any refreshed or additional shortcut passes the existing Owner/task/artifact checks.
