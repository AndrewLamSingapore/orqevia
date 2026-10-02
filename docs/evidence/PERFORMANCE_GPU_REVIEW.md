# ABEX GPU/backend review — 2026-10-02

Scope: read-only inspection of the running Windows/Docker/Ollama configuration. No driver, container, model, host setting, or production file was changed by this review. This is a capability assessment, not a GPU performance benchmark.

## Observed state

| Evidence | Observation |
| --- | --- |
| Windows display adapter (CIM) | AMD Radeon 780M Graphics, PCI `VEN_1002&DEV_1900`, driver `32.0.31035.1003` dated 2026-07-24; Windows reports status `OK`. This does not establish compute-backend support or stability. |
| WSL | `wsl --version`: WSL 2.7.14.0, kernel 6.18.33.2-2. |
| Docker | Client/server 29.8.0; the Ollama container runs a Linux kernel under WSL 2. |
| Production Ollama | `ollama version is 0.34.2`; image ID `sha256:da6e0dc5651df159e45686fd663c4dbe1624a52c44d7280eeac1551d8f865532`; healthy, restart count 0 when inspected. |
| GPU allocation | `docker inspect` showed runtime `runc`, `DeviceRequests=null`, `Devices=null`. Inside the container, `/dev/dri`, `/dev/kfd`, and `/dev/dxg` were absent. |
| Model allocation | `ollama ps` showed `gemma3:4b`, 2.9 GB resident, `100% CPU`, context 8192, warm-retention deadline about 29 minutes out at inspection. |
| Installed image backend | `/usr/lib/ollama` contains CPU, CUDA and Vulkan libraries. Presence of a library does not imply usable GPU passthrough. |
| Available models | `gemma3:4b`, `gemma3:1b`, `embeddinggemma:300m-qat-q4_0`. This is an inventory, not a comparative benchmark. |

Commands used: `Get-CimInstance Win32_VideoController`, `wsl --version`, `docker version`, `docker inspect` with selected non-secret fields, and `docker exec ... ollama --version/ps/list` plus read-only device/library directory listings. Environment values and credentials were not printed.

## Official documentation and interpretation

- [Docker Desktop Windows GPU passthrough](https://docs.docker.com/desktop/features/gpu/) describes its `--gpus` WSL 2 path for **NVIDIA** GPU-PV and lists an NVIDIA GPU as a prerequisite. It does not document an AMD Radeon 780M passthrough path for Docker Desktop on Windows.
- [Ollama Docker instructions](https://docs.ollama.com/docker) show AMD ROCm and Vulkan container paths using `/dev/kfd` and `/dev/dri`. Neither device exists in the current Ollama container, and no device was requested in its Docker configuration. Its current `100% CPU` model report is therefore consistent with its configuration.
- [Ollama hardware support](https://docs.ollama.com/gpu) lists specific AMD ROCm GPUs for Linux and Windows. Radeon 780M is not in the published Windows ROCm list. Ollama also documents additional Vulkan support on Windows/Linux, but this does **not** prove this particular Docker Desktop/WSL/Radeon combination is functional. The current image has a Vulkan library but lacks GPU device access.

## Conclusion and safe boundary

**Proven current state:** production Ollama is running `gemma3:4b` CPU-only in the observed session. **Not proven:** that Radeon 780M acceleration would work, outperform the current CPU path, remain correct, or remain stable on this host. The Docker Desktop and Ollama official documentation do not justify an in-place production GPU switch.

Potential future experiment, only after the host-stability and production-change gates permit it: a separately isolated, reversible native-Windows Ollama/Vulkan or supported Linux GPU-device path could be evaluated with fixed prompts, quality checks, time-to-first-token, prompt-eval rate, generation tokens/sec, warm/cold behavior, GPU utilization, memory pressure, and crash/WHEA monitoring. Do not install drivers, force ROCm GFX overrides, alter Docker security/device access, or replace Golden Gen 2 based on this review. For the current mission, prioritize measured critical-path improvements available within the existing CPU backend.
