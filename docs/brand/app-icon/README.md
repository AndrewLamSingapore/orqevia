# ORQEVIA app icon — canonical archive

**ORQEVIA (奥启维亚) was born in Singapore in 2026.** This folder stores the
canonical app-icon master as published to GitHub.

## Files

| File | What it is |
|---|---|
| `ORQEVIA-app-icon-1024.png` | The master icon (dark), 1024×1024, sha256 `c4810b9293dc3767d28dadabe5408108e65db8b3400d4a79b82c88bfe3f50c3d` |
| `ORQEVIA-app-icon-light-1024.png` | Light branding variant |
| `ORQEVIA-app-icon.svg` | Vector source (same geometry) |
| `ORQEVIA-favicon.ico` | Multi-size favicon (16/32/48) |

The complete install set (192/512, maskable 512, apple-touch 180, favicons,
service-worker cache) lives in `clients/pwa/icons/orqevia-command-v1-*` and is
what every device actually downloads.

## Design

The "Orbital Command" mark: obsidian field; a cyan command ring with one clean
gap; an emerald orbital satellite in that gap; N/E/S/W precision ticks; a
titanium compass star at centre — intelligence, awareness, precision, command.
Selected 2026-10-16 from three evaluated concepts (orbital / aperture / ascent).

## Regeneration

```
node clients/pwa/make-icons.mjs
```

Zero dependencies; reproduces every `orqevia-command-v1-*.png` and the ICO from
pure geometry. The legacy dark glyph the icon replaced is rejected by
`tests/test_pwa_branding.py` if it ever reappears.

## Deployment

Live at `https://192.168.1.23:8443/pwa/` (manifest + apple-touch + favicons).
Merged via PR #355; this archive added by the brand-archive PR. iPhone install:
delete the old Home Screen icon, open the URL in Safari, Share → Add to Home
Screen.
