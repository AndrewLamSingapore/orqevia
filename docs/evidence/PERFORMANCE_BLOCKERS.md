# Performance boundaries and unverified items — 2026-10-02

- `HOST_STABILITY=UNQUALIFIED`: seven historical unexpected restarts; latest 28 Sep 0x133 strongly correlates with AMD display ISR/DPC path, not proven common cause. A controlled Windows reboot for performance qualification must be separately safety-checked; app-only restart is not a host stability pass.
- Current Ollama container has no `/dev/dri` or `/dev/kfd`, and `ollama ps` plus logs show CPU inference. GPU comparison on the same production Docker path is unavailable without changing host/device exposure or backend installation. Do not treat GPU as categorically impossible: official Ollama documentation describes AMD ROCm and Vulkan paths, but the installed production container exposes neither device. No driver, firmware, or device mapping change has been made.
- Owner PWA authenticated request, first rendered useful output, tool/agent overhead, sustained long-output throughput, thermal behavior, idle retention past 5 minutes, and restart/reboot persistence remain unverified.
- Model residency uses RAM. The sampled free-memory delta is not a controlled comparison because background processes changed. Sustained memory/paging observation is required.
- PDE is separately paused at `C:/Users/Admin/Documents/ABEX/worktrees/prime-pde-20261002/docs/evidence/PDE_PAUSE_CHECKPOINT_20261002.md`.

Official backend references: [Ollama hardware support](https://docs.ollama.com/gpu), [Ollama Docker GPU requirements](https://docs.ollama.com/docker). These support the *possible* GPU paths, not GPU support on this installed ABEX configuration.
