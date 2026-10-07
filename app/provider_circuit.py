"""Optional process-local provider admission circuit, not a retry policy.

Call ``acquire`` after normal authorization/budget checks and before invoking the
provider. Finish every permit exactly once: ``succeed`` after validated complete
execution, ``fail`` for a sanitized ProviderFailure code, or ``abandon`` for
caller cancellation/local validation failure. No method dispatches, retries,
chooses a fallback, reads credentials, or upgrades readiness into provider health.

State is bounded, thread-safe and monotonic-clock based. Restart loses these
observations; this module deliberately makes no persistence/health qualification
claim. A half-open permit is one new, independently authorized recovery request,
never permission to replay the request which opened the circuit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import threading
import time
from typing import Callable


# Only provider-observed/transport faults count. Local credential readiness,
# budgets, policy denials, user cancellation and shared task deadlines do not.
PROVIDER_FAULTS = frozenset({
    'RATE_LIMIT', 'CAPACITY', 'AUTHENTICATION', 'PROVIDER_HTTP_FAILURE',
    'PROVIDER_TIMEOUT', 'PROVIDER_TRANSPORT_FAILURE', 'PROVIDER_STREAM_FAILURE',
    'MALFORMED_STREAM', 'INVALID_USAGE', 'STREAM_SIZE_EXCEEDED',
    'INCOMPLETE_STREAM', 'EMPTY_OR_INCOMPLETE_RESPONSE',
    'MALFORMED_QA_RESPONSE', 'INVALID_QA_ANSWER_SPAN', 'QA_RESPONSE_SIZE_EXCEEDED',
})
_PROVIDER_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z')


class CircuitRejected(RuntimeError):
    """Sanitized local pre-dispatch refusal; does not imply safe replay."""
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, eq=False)
class CircuitPermit:
    provider_id: str
    generation: int
    recovery_probe: bool
    _ticket: int = field(repr=False)


@dataclass
class _State:
    mode: str = 'CLOSED'
    generation: int = 0
    failures: int = 0
    opened_until: float = 0.0
    last_failure: str | None = None
    last_pre_execution: bool | None = None
    active: dict[int, CircuitPermit] = field(default_factory=dict)


class ProviderCircuits:
    def __init__(self, *, failure_threshold: int = 3,
                 cooldown_seconds: float = 30.0, max_providers: int = 32,
                 max_inflight_per_provider: int = 64,
                 clock: Callable[[], float] = time.monotonic):
        for value, low, high in ((failure_threshold, 1, 100),
                                 (max_providers, 1, 128),
                                 (max_inflight_per_provider, 1, 64)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Invalid circuit bound')
        if (type(cooldown_seconds) not in (int, float) or
                not math.isfinite(cooldown_seconds) or
                not 0 < cooldown_seconds <= 86400 or not callable(clock)):
            raise ValueError('Invalid circuit timing')
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_providers = max_providers
        self.max_inflight = max_inflight_per_provider
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _State] = {}
        self._ticket = 0
        self._last_now: float | None = None

    def _now(self) -> float:
        value = self._clock()
        if (type(value) not in (int, float) or not math.isfinite(value) or
                value < 0 or (self._last_now is not None and value < self._last_now)):
            raise CircuitRejected('CIRCUIT_CLOCK_INVALID')
        self._last_now = float(value)
        return float(value)

    def _state(self, provider_id: str) -> _State:
        if not isinstance(provider_id, str) or not _PROVIDER_ID.fullmatch(provider_id):
            raise CircuitRejected('CIRCUIT_PROVIDER_INVALID')
        if provider_id not in self._states:
            if len(self._states) >= self.max_providers:
                raise CircuitRejected('CIRCUIT_REGISTRY_FULL')
            self._states[provider_id] = _State()
        return self._states[provider_id]

    def acquire(self, provider_id: str) -> CircuitPermit:
        with self._lock:
            now = self._now()
            state = self._state(provider_id)
            if state.mode == 'HALF_OPEN' or (
                    state.mode == 'OPEN' and now < state.opened_until):
                raise CircuitRejected('PROVIDER_CIRCUIT_OPEN')
            if len(state.active) >= self.max_inflight:
                raise CircuitRejected('CIRCUIT_INFLIGHT_LIMIT')
            probe = state.mode == 'OPEN'
            if probe:
                state.mode = 'HALF_OPEN'
            self._ticket += 1
            permit = CircuitPermit(provider_id, state.generation, probe, self._ticket)
            state.active[permit._ticket] = permit
            return permit

    def _take(self, permit: CircuitPermit) -> _State:
        # Object identity prevents copied/forged/cross-instance permits from
        # changing state or releasing someone else's live recovery probe.
        if not isinstance(permit, CircuitPermit):
            raise CircuitRejected('CIRCUIT_PERMIT_INVALID')
        state = self._states.get(permit.provider_id)
        if state is None or state.active.get(permit._ticket) is not permit:
            raise CircuitRejected('CIRCUIT_PERMIT_INVALID')
        del state.active[permit._ticket]
        return state

    def succeed(self, permit: CircuitPermit) -> None:
        with self._lock:
            self._now()
            state = self._take(permit)
            if permit.generation != state.generation:
                return  # Late success cannot close a more recent opened circuit.
            if state.mode == 'HALF_OPEN' and not permit.recovery_probe:
                return
            state.mode = 'CLOSED'
            state.failures = 0
            state.opened_until = 0.0
            state.last_failure = None
            state.last_pre_execution = None

    def fail(self, permit: CircuitPermit, code: str, *, pre_execution: bool = False) -> None:
        if type(pre_execution) is not bool:
            raise ValueError('Invalid failure admission classification')
        with self._lock:
            now = self._now()
            state = self._take(permit)
            if permit.generation != state.generation:
                return
            if not isinstance(code, str) or code not in PROVIDER_FAULTS:
                # Unknown error text is never retained; no caller-supplied raw
                # exception, prompt, credential or endpoint enters the evidence.
                self._release_probe(state, permit)
                return
            state.failures += 1
            state.last_failure = code
            state.last_pre_execution = pre_execution
            if permit.recovery_probe or state.failures >= self.failure_threshold:
                state.mode = 'OPEN'
                state.generation += 1
                state.opened_until = now + self.cooldown_seconds

    @staticmethod
    def _release_probe(state: _State, permit: CircuitPermit) -> None:
        if permit.recovery_probe and state.mode == 'HALF_OPEN':
            # No provider observation occurred. Release the exclusive probe
            # without adding a fault or claiming recovery/closing the circuit.
            state.mode = 'OPEN'

    def abandon(self, permit: CircuitPermit) -> None:
        with self._lock:
            self._now()
            state = self._take(permit)
            if permit.generation == state.generation:
                self._release_probe(state, permit)

    def snapshot(self, provider_id: str) -> dict:
        with self._lock:
            now = self._now()
            state = self._state(provider_id)
            return {
                'provider_id': provider_id, 'circuit_state': state.mode,
                'consecutive_provider_failures': state.failures,
                'retry_after_seconds': max(0.0, state.opened_until - now)
                    if state.mode in {'OPEN', 'HALF_OPEN'} else 0.0,
                'active_permits': len(state.active),
                'recovery_probe_inflight': state.mode == 'HALF_OPEN',
                'last_failure_code': state.last_failure,
                'last_failure_pre_execution': state.last_pre_execution,
                'scope': 'PROCESS_LOCAL_ADMISSION_NOT_PROVIDER_HEALTH',
                'replay_authorized': False,
            }
