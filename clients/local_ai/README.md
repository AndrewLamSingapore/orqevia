# Internal local AI diagnostics

The normal user entry is the trusted ORQEVIA `/pwa/` workspace. These are local
diagnostic clients of that workspace's shared application service. They neither
build an independent index nor launch another model pipeline. Existing V1/V2
indexes and original prototype scripts remain in verified preservation custody.

After the shared replacement passes release checks and operational acceptance,
`scripts/install_local_diagnostics.py` verifies original custody and replaces the
existing prototype entry points reversibly. Its receipt records exact hashes.
Run Streamlit only on loopback (`--server.address 127.0.0.1`); it uses the existing
local operating-system/service authority, not a new public document endpoint.
Do not publish this diagnostic port or disclose its server-side authority.

`orqevia_rag_v3.py QUESTION` retains cited local answer generation;
`--retrieve-only` returns measured retrieval. `ingest.py FILE...` calls shared
bounded ingestion and `--reindex` commits a recoverable generation. The original
`rag.py build|search` command syntax uses the same shared service. No command
implicitly overwrites original index files. The former Singapore map was a
demonstration; attributed operational observations are in the primary God's Eye.
