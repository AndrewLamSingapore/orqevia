"""Optional existing-library acceleration for wider deterministic state models.

No model artifacts, execution authority, registry mutation or network access.
The caller retains validation and the original Python fallback.
"""

from __future__ import annotations


def forecast(matrix, initial, steps):
    import numpy as np

    size = len(initial)
    power = np.asarray(matrix, dtype=np.float64)
    current = np.asarray(initial, dtype=np.float64)
    if power.shape != (size, size) or current.shape != (size,):
        raise ValueError("Invalid probability dimensions")
    if not np.isfinite(power).all() or not np.isfinite(current).all():
        raise ValueError("Nonfinite probability input")
    exponent = steps
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        while exponent:
            if exponent & 1:
                current = current @ power
                current = current / current.sum()
            exponent >>= 1
            if exponent:
                power = power @ power
                power = power / power.sum(axis=1, keepdims=True)
    result = current.tolist()
    if not all(0 <= value <= 1 for value in result) or abs(sum(result) - 1) > 1e-10:
        raise ValueError("Numerical probability validation failed")
    return result
