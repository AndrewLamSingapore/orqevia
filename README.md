# JARVIS PRIME v1

Canonical product source. Read docs/ARCHITECTURE_V1.md and system.manifest.json. The successor explicitly supersedes conflicting governance/OPERATIONAL_BASELINE_v1.md and legacy deployment guidance; originals remain historical. Git defines intended state; runtime defines deployed state; evidence proves correspondence.

Run `python scripts/validate_ssot.py`, then deterministic tests using isolated PRIME_DATA_DIR and PRIME_COMPUTE_QUEUE_DB. Build with `python scripts/build_source_release.py --output <new-directory>`. PWA tests: `node clients/pwa/tests.mjs`, `node clients/pwa/followup-tests.mjs`, `node clients/pwa/revision-tests.mjs`. Dell package instructions: clients/dell/PACKAGING.md.

Production data, credentials, certificates, model files, provider selections and qualification remain external. Examples are not live deployment settings. Physical acceptance is proved separately.
