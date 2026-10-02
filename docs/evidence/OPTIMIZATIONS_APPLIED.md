# Performance changes applied — 2026-10-02

## Production runtime configuration (reversible)

At about 16:01 SGT, changed only `PRIME_MODEL_KEEP_ALIVE` in `C:/Users/Admin/Documents/ABEX/runtime/prime-epoch-20260919/.env` from `5m` to `30m` and recreated only the PRIME container with the pre-existing Golden image (`--no-deps --no-build --force-recreate prime`). This preserves production source/image, databases, Interface, and Ollama containers. PRIME reported `keep_alive=30m` and all three services were healthy with zero restarts immediately afterward. Rollback: restore the exact prior value `5m` and perform the same PRIME-only controlled recreation after checking for running jobs.

A bounded direct Ollama probe before the configuration change used `keep_alive=30m` transiently; `ollama ps` showed 29 minutes remaining, at 3.543 GiB Ollama memory. This was a reversible runtime proof, not persistent configuration.

After the persistent change, three identical PRIME requests completed in 1.895342, 1.366924, and 1.362313 s. Their model-load events were 0.002093, 0.001007, and 0.001529 s. Ollama showed the 4B model with 29 minutes remaining after the requests. Free host RAM was 17,220 MB and Ollama memory 3.51 GiB at 16:02:41 SGT. An idle interval beyond the old 5-minute limit and restart/reboot persistence are still pending; no VERIFIED closure is claimed.

No driver, BIOS, firmware, security, database, Golden image, or identity change was made.
