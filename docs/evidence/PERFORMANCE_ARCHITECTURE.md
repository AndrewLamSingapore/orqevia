# Current response path and critical path

Production Owner-like work flows through the TLS Interface/PWA, authenticated objective contract, PRIME objective orchestration, governed dispatch/one-slot queue, Ollama, result store, task status/events, and PWA rendering. The measured fixture covered authenticated PRIME loopback dispatch → queue → Ollama → terminal job poll, not the full Owner PWA path.

The tested cold short request spent 9.155 s on Ollama model load out of 12.195 s client wall time. After warming, the next measured portion is CPU generation (about 1.0 s for 10 tokens), prompt evaluation (0.212 s for 178 tokens in a direct warm backend probe), and client polling/HTTP overhead. PRIME dispatch (~0.04–0.07 s) and queue wait (~0.03–0.05 s) are not first optimization targets for this fixture.

The PWA is status-snapshot based rather than token-streaming. See `PERFORMANCE_STREAMING_REVIEW.md`. Do not equate model first token with first useful Owner-visible content until instrumented on an authenticated device.

The current production CPU path is documented in `PERFORMANCE_GPU_REVIEW.md`. GPU acceleration is not proven available on the installed Docker/WSL configuration. Keep routing and governance requirements intact while comparing any future execution backend.
