# JARVIS PRIME Runtime Independence Contract

PRIME is a logical control plane, not a laptop process. Compute nodes host PRIME capabilities but do not own PRIME identity, policy or durable history.

## Invariants

1. `/data` is durable and external to the PRIME container lifecycle.
2. Ollama model storage is durable and external to the model-runtime container lifecycle.
3. Replacing a container must not replace PRIME identity or history.
4. The Stable Spine remains approval-gated and no-actuation by default.
5. Remote integration is mediated by the integration gateway and requires a token.
6. The Control Surface remains local-only unless a separately reviewed policy changes that boundary.
7. Every host advertises a node identity; the default Dell host is `prime-node-01`.
8. Model failure may degrade intelligence but must not silently grant authority or mutate policy.

## Recovery acceptance test

Before testing, ensure durable state is backed up using the existing JARVIS operations/checkpoint workflow.

1. Record `/health`, `/api/status`, and Control Surface manifest results.
2. Record durable volume names and database presence.
3. Restart/recreate only the PRIME application container.
4. Wait for health to become OK.
5. Confirm the same durable volumes are mounted.
6. Confirm runtime integrity remains OK and approval/no-actuation boundaries are unchanged.
7. Confirm durable databases/history remain present.
8. Run the existing JARVIS contract check.

A failed invariant is a failed deployment. Do not delete or recreate durable volumes as a repair step.

## Migration model

Future machines join as nodes. They may supply inference, device ingress, or other capabilities, while PRIME's durable state and authority contract remain explicit. Migration to an always-on host is therefore a controlled relocation/replication of the control plane rather than a redesign of JARVIS.
