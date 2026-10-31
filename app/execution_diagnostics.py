"""Value-free failure provenance for the existing execution-event journal.

Never serialize exception messages, request/response objects, frame locals,
URLs or source paths. Reason codes describe only known application conditions.
"""

from __future__ import annotations

from pathlib import PurePath
import re


_REASONS = {
    "Model is outside measured Compute Profile": "MODEL_OUTSIDE_MEASURED_PROFILE",
    "Measured Compute Profile memory reserve reached; local inference held": "MEMORY_ADMISSION_RESERVE",
    "Measured Compute Profile memory reserve reached; bounded work held": "MEMORY_ADMISSION_RESERVE",
    "Local provider is not an existing configured role": "LOCAL_PROVIDER_NOT_CONFIGURED",
    "Task cancelled by client": "CLIENT_CANCELLATION",
    "MODEL_FIRST_PROGRESS_TIMEOUT": "MODEL_FIRST_PROGRESS_TIMEOUT",
    "MODEL_PROGRESS_STALLED": "MODEL_PROGRESS_STALLED",
    "ACTIVE_INFERENCE_BUDGET_EXCEEDED": "ACTIVE_INFERENCE_BUDGET_EXCEEDED",
    "Malformed model response": "MALFORMED_MODEL_RESPONSE",
    "Malformed model completion": "MALFORMED_MODEL_COMPLETION",
    "Incomplete or empty model response": "INCOMPLETE_MODEL_RESPONSE",
}


def _identifier(value, maximum=120):
    return (
        value
        if type(value) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,119}", value) and len(value) <= maximum
        else "UNKNOWN"
    )


def failure_details(error: BaseException, *, stage="UNKNOWN", provider_kind="UNKNOWN") -> dict:
    """Retain bounded class/cause/stack metadata without untrusted values."""
    chain = []
    seen = set()
    current = error
    while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        chain.append({"module": _identifier(type(current).__module__), "class": _identifier(type(current).__name__)})
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    frames = []
    frame = error.__traceback__
    while frame is not None:
        code = frame.tb_frame.f_code
        name = PurePath(code.co_filename).name
        if not re.fullmatch(r"[A-Za-z0-9_.<>-]{1,100}", name):
            name = "UNKNOWN"
        function = code.co_name if re.fullmatch(r"[A-Za-z0-9_<>]{1,100}", code.co_name) else "UNKNOWN"
        frames.append({"file": name, "function": function, "line": frame.tb_lineno})
        frames = frames[-8:]
        frame = frame.tb_next
    # Only exact built-in application exception messages can select a fixed
    # code. Arbitrary upstream exception text is never copied or hashed.
    reason = "UNCLASSIFIED_EXECUTION_FAILURE"
    if type(error) in (RuntimeError, PermissionError, TimeoutError, ValueError):
        try:
            reason = _REASONS.get(str(error), reason)
        except Exception:
            pass
    if isinstance(error, TimeoutError) and reason == "UNCLASSIFIED_EXECUTION_FAILURE":
        reason = "EXECUTION_TIMEOUT"
    if type(error).__name__ == "CancelledError":
        reason = "EXECUTION_CANCELLED"
    if isinstance(error, MemoryError):
        reason = "MEMORY_EXHAUSTED"
    return {
        "schema_version": "orqevia.execution-failure.v1",
        "exception_class": _identifier(type(error).__name__),
        "cause_chain": chain,
        "stage": stage if type(stage) is str and re.fullmatch(r"[A-Z_]{1,40}", stage) else "UNKNOWN",
        "provider_kind": provider_kind if provider_kind in ("local", "cloud") else "UNKNOWN",
        "reason_code": reason,
        "frames": frames,
        "message_recorded": False,
    }
