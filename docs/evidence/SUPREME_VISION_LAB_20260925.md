# Supreme Vision — Static LAB Gate

Status: **TESTED LAB — static trust boundary; OCR accuracy not yet a candidate claim**

The bounded static contract accepts screenshots, photos and documents with externally produced OCR observations. It records a source digest and separates `OBSERVED`, `INTERPRETED`, `INFERRED` and `UNKNOWN` material.

Chinese and English OCR text remains untrusted data. Visual instructions cannot grant authority or trigger tools. When a visual claim conflicts with authoritative API/database/session truth, the contradiction is preserved and machine-readable authority remains controlling.

This gate does not claim camera monitoring, production OCR accuracy, physical-device acceptance or deployment.

Adversarial coverage now preserves cropped context as UNKNOWN, records competing OCR candidates instead of guessing, and retains fabricated visual deployment/session/authorization claims as explicit contradictions against authoritative state. Independent verifier: 5/5. Focused suite: 25 passed. Canonical suite: 393 passed. Full suite: 764 passed.
