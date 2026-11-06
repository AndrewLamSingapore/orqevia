# Logging resilience: source changed, running service preserved

Live orqevia-intelligence-1 is API-managed, not Compose-owned. Inspect shows
json-file with empty options. Current identity/image/configuration digest is bound
in evidence/intelligence-logging-plan.json; any drift requires reconciliation.
All other8containers already have explicit rotation; coaching2m/2, others10m/3.

The dated creator chain is operations/open-access-20261016/recreate-intelligence-nosanbox.ps1
then operations/release-qualification-20261023/promote_intelligence_capacity.py.
The latter created the current capacity image by copying old HostConfig and
therefore inherited unlimited logging. It is an old recreation procedure with a
stale base-image assertion, not an approved command to execute now.

Safe changes made:

- Repository deploy/intelligence-abex.compose.yml now specifies json-file,
  max-size "10m", max-file "3". config/docker-intelligence-logging.json records
  the same Docker API LogConfig. Compose was parsed with an empty credential
  fixture: PASS. No real token was used or exported by the validation.
- Local authoritative dated creator source now assigns that LogConfig after its
  HostConfig copy. Original bytes are preserved and before/after hashes are in
  evidence/creator-source-change.json. It was syntax-checked, NEVER EXECUTED.
- Monitor emits an identity-bound proposed plan. It has no apply/recreate mode.

For a future explicitly approved service maintenance window: preserve current
configuration privately and existing image; reconcile current ID/image/config
SHA, environment, mounted data, network aliases, ports, restart/health settings and
concurrent work. Use the existing narrowly scoped deployment procedure, changing
only HostConfig.LogConfig to the proposed value. Do not run broad Compose up or
replay old scripts with stale image assertions. Retain original container/image
for rollback. Confirm application HTTPS/authentication and data before and after,
then inspect actual new LogConfig and health. Do not truncate current log files.
The prepared10m/3 cap retains approximately30MB of active/rotated JSON logs, plus
rotation overhead; it does not bound all application/database storage.

Docker documents that changed defaults do not update existing containers:
[JSON logging driver](https://docs.docker.com/engine/logging/drivers/json-file/).
The daemon default is local, but these9containers explicitly use json-file.
The [local driver](https://docs.docker.com/engine/logging/drivers/local/) has
rotation/compression defaults; that does not repair this existing explicit policy.
No central OTel pipeline configuration or historical log contents were modified.

Rollback source-only changes with Git or the exact saved original creator bytes;
never overwrite concurrent edits. Running state needs no rollback today because
it was not recreated. After future deployment, roll back with the retained image
and configuration under an approved window; retain the persistent volume.
