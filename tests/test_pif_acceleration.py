"""Numerical boundaries and seeded reproducibility for optional acceleration."""

import random

import pytest

from app.pif import core, numpy_backend
from benchmarks.native_acceleration.fixtures import fixture


@pytest.mark.parametrize("size", [24, 48])
@pytest.mark.parametrize("steps", [0, 1, 2, 64, 256])
def test_optional_forecast_matches_validated_python(monkeypatch, size, steps):
    pytest.importorskip("numpy")
    model = fixture(size)
    initial = {model.states[0]: 0.4, model.states[-1]: 0.6}
    monkeypatch.delenv("ORQEVIA_PIF_NUMPY_ENABLED", raising=False)
    expected = model.forecast(initial, steps)
    version = model.version
    monkeypatch.setenv("ORQEVIA_PIF_NUMPY_ENABLED", "1")
    actual = model.forecast(initial, steps)
    assert actual == pytest.approx(expected, abs=1e-12, rel=1e-12)
    assert sum(actual.values()) == pytest.approx(1, abs=1e-12)
    assert all(0 <= p <= 1 for p in actual.values())
    assert model.version == version


@pytest.mark.parametrize("failure", [ImportError, ValueError, FloatingPointError])
def test_optional_dependency_failure_preserves_original(monkeypatch, failure):
    model = fixture(24)
    monkeypatch.delenv("ORQEVIA_PIF_NUMPY_ENABLED", raising=False)
    expected = model.forecast("s0", 64)

    def fail(*args):
        raise failure("fixture")

    monkeypatch.setattr(numpy_backend, "forecast", fail)
    monkeypatch.setenv("ORQEVIA_PIF_NUMPY_ENABLED", "1")
    assert model.forecast("s0", 64) == expected


@pytest.mark.parametrize("size,flag", [(8, "1"), (16, "1"), (24, "0"), (24, "true")])
def test_unqualified_or_disabled_models_keep_python(monkeypatch, size, flag):
    def forbidden(*args):
        raise AssertionError("optional backend must not be entered")

    monkeypatch.setattr(numpy_backend, "forecast", forbidden)
    monkeypatch.setenv("ORQEVIA_PIF_NUMPY_ENABLED", flag)
    assert sum(fixture(size).forecast("s0", 64).values()) == pytest.approx(1)


@pytest.mark.parametrize("seed", [0, 42, 20261029])
@pytest.mark.parametrize("steps,samples", [(0, 1), (1, 7), (32, 100)])
def test_cached_sampling_exactly_preserves_original_rng(seed, steps, samples):
    model = fixture(8)
    start = {"s0": 0.35, "s7": 0.65}
    rng = random.Random(seed)
    original = []
    for _ in range(samples):
        state = rng.choices(range(8), weights=model.initial(start), k=1)[0]
        trajectory = [model.states[state]]
        for _ in range(steps):
            state = rng.choices(range(8), weights=model.matrix[state], k=1)[0]
            trajectory.append(model.states[state])
        original.append(trajectory)
    result = core.simulate(model, start, steps=steps, samples=samples, seed=seed)
    assert result["trajectories"] == original
    counts = {name: sum(t[-1] == name for t in original) for name in model.states}
    assert result["monte_carlo_95pct_intervals"] == {
        name: list(core.wilson(counts[name], samples)) for name in model.states
    }
    assert result["causal_intervention"] is False


def test_optional_backend_rejects_nonfinite_and_wrong_shapes():
    pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        numpy_backend.forecast(((float("nan"),),), (1,), 2)
    with pytest.raises(ValueError):
        numpy_backend.forecast(((1,),), (0.5, 0.5), 2)


@pytest.mark.parametrize("escape", [0.0, 1e-14])
def test_wide_reducible_nearly_absorbing_long_horizon(monkeypatch, escape):
    pytest.importorskip("numpy")
    values = fixture(24).as_dict()
    values["matrix"] = [[float(i == j) for j in range(24)] for i in range(24)]
    values["matrix"][0][0] = 1 - escape
    values["matrix"][0][1] = escape
    model = core.MarkovModel.from_dict(values)
    monkeypatch.setenv("ORQEVIA_PIF_NUMPY_ENABLED", "0")
    expected = model.forecast("s0", 1_000_000)
    monkeypatch.setenv("ORQEVIA_PIF_NUMPY_ENABLED", "1")
    assert model.forecast("s0", 1_000_000) == pytest.approx(expected, abs=1e-12, rel=1e-12)
