# Operational single source of truth

`operational-manifest.json` is the sole machine-readable current cursor for the non-VELYQUA portfolio. It separates source, deployment and private-runtime truth so a successful merge can never be mistaken for a completed Dell update.

Authority order:

1. This manifest defines canonical identities, scope, project mappings and intended versions.
2. Live GitHub, Vercel and Dell health evidence proves whether reality matches the manifest.
3. The one Library resume checkpoint is the human-readable mirror.
4. Git and Library history are rollback evidence, not additional current checkpoints.

When reality differs, record the explicit divergence here (`operator_update_required`, `configuration_required`, or another bounded status). Production systems must record their exact deployment ID and a health revision equal to the source SHA; PRIME must record the last green source SHA and immutable image tag. Never copy secret values into governance files. VELYQUA remains parked until the exact phrase `resume VELYQUA` is supplied.
