# Final static rendering correction

Actual production acceptance of 0de3026 passed 98 runtime/API/security checks
and 28 of 30 browser captures. Two remaining rendering defects were identified:
MapLibre's embedded data-image controls violated the existing closed CSP, and a
full 64-character approval reference widened mobile Settings to 489 pixels.

The map asset builder now verifies pinned MapLibre 6.14.0 input and original CSS
SHA256, then materializes its 39 embedded SVG references as 31 deduplicated files.
The decoded SVG bytes are unchanged. Generated CSS references only same-origin
files; CSP remains strict. Upstream modules and the BSD notice are unchanged.
The original CSS is retained under `docs/third-party/maplibre-gl/6.14.0/`, outside
the served application. Public asset provenance records source and output hashes.
All generated icons and required notices are in the static offline allowlist.
Raw-byte Git attributes preserve integrity across Windows and Linux checkouts.

Approval metadata wraps without truncating its identifier or hiding overflow.
Page and service worker advance together to v46 while retaining existing session,
draft and cache-boundary protections.

Source validation passed 136 Node tests, 120 browser cases in Chromium, Firefox
and WebKit, and 23 focused worker/packaging cases. Nine new rendering cases use the
closed production CSP, initialize the actual native map, and exercise complete
metadata at 320 and 390 pixels. Two builder runs produce identical bytes; staged
Git blobs match all 37 recorded source/asset hashes and the provenance manifest.

Python application, runtime configuration, model and dependency files are
unchanged from the qualified 0de3026 core (7,169 full Linux test passes and 98
actual runtime/API/auth checks). The final deployment therefore updates only the
interface container; model workers, collector and native knowledge remain in
place. Component source/image versions must be reported individually. Production
screenshots must still verify this static release before rendering is accepted.
