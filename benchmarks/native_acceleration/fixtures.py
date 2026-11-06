"""Deterministic synthetic inputs; no production history or numerical dependency."""

import hashlib
import math
import random

from app.pif.core import MarkovModel


def fixture(size):
    rng = random.Random(20261029 + size)
    states = tuple(f"s{i}" for i in range(size))
    rows = []
    for _ in states:
        row = [rng.random() + 0.05 for _ in states]
        total = math.fsum(row)
        rows.append(tuple(x / total for x in row))
    return MarkovModel(
        states,
        tuple(rows),
        tuple(tuple(1 for _ in states) for _ in states),
        (),
        0.0,
        None,
        None,
        hashlib.sha256(f"fixture:{size}".encode()).hexdigest(),
        ("fixture",),
        size,
        tuple((a, b) for a in states for b in states),
    )
