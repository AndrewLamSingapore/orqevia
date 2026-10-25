"""Mathematical, provenance, isolation and independent-failure acceptance."""

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.pif.core import (
    History,
    MarkovModel,
    Observation,
    absorbing_analysis,
    estimate_markov,
    hidden_filter,
    simulate,
    stationary_distribution,
)
from app.pif.history import QUEUE_ABSORBING, QUEUE_EDGES, QUEUE_STATES, read_compute_history
from app.pif.service import PIFService
from app.pif.store import PIFStore
from app.pif.validation import chronological_validation


BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def history(number, states, *, kind="fixture", day=None):
    start = BASE + timedelta(days=number if day is None else day)
    return History(
        f"job-{number}",
        tuple(
            Observation(s, (start + timedelta(seconds=i)).isoformat(), f"e-{number}-{i}") for i, s in enumerate(states)
        ),
        kind,
    )


def fit_model():
    rows = [history(i, ("pending", "running", "failed" if i % 4 == 0 else "completed")) for i in range(80)]
    model = estimate_markov(
        rows,
        states=("pending", "running", "completed", "failed"),
        absorbing_states=("completed", "failed"),
        alpha=0,
        allowed_edges=(
            ("pending", "running"),
            ("running", "completed"),
            ("running", "failed"),
            ("completed", "completed"),
            ("failed", "failed"),
        ),
    )
    return rows, model


def service(tmp_path, **kwargs):
    rows, model = fit_model()
    svc = PIFService(tmp_path / "model-registry.db", enabled=True, **kwargs)
    fit = svc.fit_history(
        rows,
        states=model.states,
        absorbing_states=model.absorbing_states,
        allowed_edges=model.allowed_edges,
        alpha=0,
        source_revision="a" * 40,
    )
    assert fit["status"] == "SHADOW"
    return svc, fit


def test_markov_transition_matrix_exact_and_conserves_probability():
    _, model = fit_model()
    assert model.matrix == ((0, 1, 0, 0), (0, 0, 0.75, 0.25), (0, 0, 1, 0), (0, 0, 0, 1))
    for horizon in (0, 1, 2, 3, 100, 100_000):
        forecast = model.forecast("pending", horizon)
        assert sum(forecast.values()) == pytest.approx(1)
        assert all(0 <= p <= 1 for p in forecast.values())
    assert model.forecast("pending", 2) == {"pending": 0, "running": 0, "completed": 0.75, "failed": 0.25}
    assert model.forecast({"pending": 0.4, "running": 0.6}, 1)["failed"] == pytest.approx(0.15)


def test_sparse_smoothing_does_not_reopen_absorbing_state():
    model = estimate_markov([history(1, ("a", "done"))], states=("a", "done"), absorbing_states=("done",), alpha=1)
    assert model.matrix[0] == (1 / 3, 2 / 3)
    assert model.matrix[1] == (0, 1)
    assert model.counts[1] == (0, 0)


def test_empty_rows_are_normalized_but_explicitly_unsupported():
    model = estimate_markov([], states=("a", "b"), alpha=0)
    assert model.matrix == ((0.5, 0.5), (0.5, 0.5))
    assert model.unsupported_states("a", 0) == []
    assert model.unsupported_states("a", 1) == ["a"]
    assert model.unsupported_states("a", 2) == ["a", "b"]


def test_topology_zeroes_forbidden_edges_and_rejects_conflicting_evidence():
    edges = (("a", "done"), ("done", "done"))
    model = estimate_markov([], states=("a", "done"), absorbing_states=("done",), allowed_edges=edges)
    assert model.matrix == ((0, 1), (0, 1))
    with pytest.raises(ValueError, match="topology"):
        estimate_markov([history(1, ("a", "a"))], states=("a", "done"), absorbing_states=("done",), allowed_edges=edges)


@pytest.mark.parametrize("bad", [-1, True, 1.5, "2"])
def test_invalid_horizon(bad):
    _, model = fit_model()
    with pytest.raises(ValueError):
        model.forecast("pending", bad)


@pytest.mark.parametrize(
    "start", ["unknown", {"pending": 0.9}, {"pending": math.nan}, {"pending": -0.1, "running": 1.1}, {"other": 1}]
)
def test_invalid_initial_distribution(start):
    _, model = fit_model()
    with pytest.raises(ValueError):
        model.forecast(start, 1)


@pytest.mark.parametrize("alpha", [-1, math.nan, math.inf, True, "0"])
def test_invalid_smoothing(alpha):
    with pytest.raises(ValueError):
        estimate_markov([], states=("a",), alpha=alpha)


def test_absorption_probabilities_and_expected_steps():
    _, model = fit_model()
    result = absorbing_analysis(model)
    assert result["status"] == "AVAILABLE"
    assert result["states"]["pending"]["expected_state_changes_to_absorption"] == pytest.approx(2)
    assert result["states"]["pending"]["absorption_probabilities"] == {"completed": 0.75, "failed": 0.25}
    assert result["states"]["completed"]["expected_state_changes_to_absorption"] == 0


def test_absorption_refuses_nonabsorbing_closed_class():
    rows = [history(1, ("a", "b", "a")), history(2, ("c", "done"))]
    model = estimate_markov(rows, states=("a", "b", "c", "done"), absorbing_states=("done",), alpha=0)
    assert absorbing_analysis(model)["reason"] == "NONABSORBING_CLOSED_CLASS"


def test_stationary_solution_is_not_a_limiting_distribution_claim():
    rows = [history(i, ("a", "b", "a")) for i in range(10)]
    model = estimate_markov(rows, states=("a", "b"), alpha=0)
    stationary = stationary_distribution(model)
    assert stationary["probabilities"] == {"a": 0.5, "b": 0.5}
    assert stationary["residual"] < 1e-12
    assert stationary["limiting_distribution_claimed"] is False
    _, absorbing = fit_model()
    assert stationary_distribution(absorbing)["status"] == "NOT_APPLICABLE"


def test_forecast_reproducible_version_and_roundtrip():
    histories, model = fit_model()
    repeated = estimate_markov(
        reversed(histories),
        states=model.states,
        alpha=0,
        absorbing_states=model.absorbing_states,
        allowed_edges=model.allowed_edges,
    )
    assert repeated.version == model.version
    restored = MarkovModel.from_dict(json.loads(json.dumps(model.as_dict())))
    assert restored == model
    assert restored.version == model.version
    changed = estimate_markov(
        histories,
        states=model.states,
        alpha=0.5,
        absorbing_states=model.absorbing_states,
        allowed_edges=model.allowed_edges,
    )
    assert changed.version != model.version


def test_time_window_excludes_both_outside_observations():
    rows = [history(i, ("a", "b", "a")) for i in range(10)]
    model = estimate_markov(
        rows,
        states=("a", "b"),
        since=(BASE + timedelta(days=3)).isoformat(),
        until=(BASE + timedelta(days=5)).isoformat(),
    )
    assert model.entity_count == 2
    assert model.transition_count == 4
    assert model.observation_start == rows[3].observations[0].timestamp
    with pytest.raises(ValueError):
        estimate_markov(rows, states=("a", "b"), since="2026-10-05T00:00:00Z", until="2026-10-01T00:00:00Z")


def test_repeated_entities_and_events_rejected():
    row = history(1, ("a", "b"))
    with pytest.raises(ValueError):
        estimate_markov([row, row], states=("a", "b"))
    with pytest.raises(ValueError):
        estimate_markov([row, History("other", row.observations)], states=("a", "b"))
    with pytest.raises(ValueError):
        History("bad", tuple(reversed(row.observations)))
    with pytest.raises(ValueError):
        Observation("a", "2026-10-01T00:00:00", "event")


def test_monte_carlo_repeatability_analytic_agreement_and_intervals():
    _, model = fit_model()
    a = simulate(model, "pending", steps=2, samples=2000, seed=17)
    b = simulate(model, "pending", steps=2, samples=2000, seed=17)
    assert a == b
    assert a["final_distribution"]["failed"] == pytest.approx(0.25, abs=0.03)
    lower, upper = a["monte_carlo_95pct_intervals"]["failed"]
    assert lower < a["final_distribution"]["failed"] < upper
    assert a["causal_intervention"] is False
    assert a["interval_scope"] == "MONTE_CARLO_SAMPLING_ONLY"


def test_hidden_filter_matches_hand_calculation_and_scaled_likelihood():
    result = hidden_filter(
        states=("healthy", "degraded"),
        transitions=((0.8, 0.2), (0.3, 0.7)),
        initial=(0.6, 0.4),
        emissions={"success": (0.9, 0.2), "failure": (0.1, 0.8)},
        observations=("success", "failure"),
    )
    # First observation likelihood .62; posterior healthy .54/.62.
    p0 = 0.54 / 0.62
    prior_healthy = p0 * 0.8 + (1 - p0) * 0.3
    likelihood_2 = prior_healthy * 0.1 + (1 - prior_healthy) * 0.8
    assert result["posterior"]["healthy"] == pytest.approx(prior_healthy * 0.1 / likelihood_2)
    assert result["log_likelihood"] == pytest.approx(math.log(0.62) + math.log(likelihood_2))
    assert result["forecasting_quality"] == "NOT_VALIDATED"
    long = hidden_filter(
        states=("a",),
        transitions=((1,),),
        initial=(1,),
        emissions={"x": (0.01,), "y": (0.99,)},
        observations=["x"] * 1000,
    )
    assert math.isfinite(long["log_likelihood"])
    assert long["log_likelihood"] == pytest.approx(1000 * math.log(0.01))


def test_hidden_filter_impossible_and_invalid_emissions():
    result = hidden_filter(
        states=("a",), transitions=((1,),), initial=(1,), emissions={"x": (0,), "y": (1,)}, observations=["x"]
    )
    assert result["status"] == "IMPOSSIBLE_OBSERVATION"
    with pytest.raises(ValueError):
        hidden_filter(states=("a",), transitions=((1,),), initial=(1,), emissions={"x": (0.5,)}, observations=["x"])


def test_chronological_validation_keeps_entities_disjoint_and_compares_baselines():
    rows, model = fit_model()
    report = chronological_validation(
        rows, states=model.states, absorbing_states=model.absorbing_states, allowed_edges=model.allowed_edges, alpha=0
    )
    assert report["status"] == "EVALUATED"
    assert report["train_entities"] == 64
    assert report["test_entities"] == 16
    assert report["train_transitions"] == 128
    assert report["test_transitions"] == 32
    assert report["production_quality_validated"] is False
    assert report["evidence_kinds"] == ["fixture"]
    assert report["scores"]["markov_brier"] < report["scores"]["persistence_brier"]
    assert sum(b["count"] for b in report["calibration_bins"]) == 32 * len(model.states)


def test_crossing_histories_and_future_outcomes_do_not_leak():
    earlier = [history(i, ("a", "done")) for i in range(30)]
    crossing = History(
        "cross",
        (Observation("a", "2026-10-30T00:00:00Z", "cross-a"), Observation("done", "2026-11-05T00:00:00Z", "cross-b")),
        "fixture",
    )
    later = [history(i, ("a", "done")) for i in range(35, 60)]
    report = chronological_validation(
        earlier + [crossing] + later, states=("a", "done"), absorbing_states=("done",), cutoff="2026-11-01T00:00:00Z"
    )
    assert report["crossing_entities_excluded"] == 1
    assert report["train_entities"] == 30
    assert report["test_entities"] == 25
    modified = [history(i, ("a", "a", "done")) for i in range(35, 60)]
    other = chronological_validation(
        earlier + [crossing] + modified, states=("a", "done"), absorbing_states=("done",), cutoff="2026-11-01T00:00:00Z"
    )
    assert other["training_model_digest"] == report["training_model_digest"]
    assert other["test_evidence_digest"] != report["test_evidence_digest"]


def test_insufficient_data_and_disabled_are_explicit_no_database_side_effects(tmp_path, monkeypatch):
    path = tmp_path / "missing" / "registry.db"
    monkeypatch.delenv("ORQEVIA_PIF_ENABLED", raising=False)
    svc = PIFService(path)
    assert svc.health()["status"] == "DISABLED"
    assert svc.forecast_state("queued")["status"] == "DISABLED"
    assert svc.infer_hidden_state()["status"] == "DISABLED"
    assert svc.evaluate_intervention()["status"] == "DISABLED"
    assert svc.get_prediction_evidence("whatever")["status"] == "DISABLED"
    assert not path.parent.exists()
    monkeypatch.setenv("ORQEVIA_PIF_ENABLED", "1")
    assert svc.health()["enabled"] is True
    assert svc.forecast_state("queued")["reason"] == "NO_OBSERVED_MODEL_IN_SCOPE"
    assert svc.fit_history([], states=("queued",))["reason"] == "NO_OBSERVED_TRANSITIONS"


def test_service_prediction_provenance_and_tenant_scoped_evidence(tmp_path):
    svc, fit = service(tmp_path)
    result = svc.forecast_state("pending", steps=2)
    assert result["status"] == "SHADOW"
    assert result["data"]["probabilities"]["failed"] == 0.25
    assert result["grants_execution_authority"] is False
    assert result["model_version"] == fit["model_version"]
    assert result["model_provenance"]["evidence_kinds"] == ["fixture"]
    assert result["horizon_unit"] == "STATE_CHANGE_EVENTS"
    evidence = svc.get_prediction_evidence(result["trace_id"])
    assert evidence["data"] == result
    other = PIFService(svc.store.path, enabled=True, tenant_id="other")
    assert other.get_prediction_evidence(result["trace_id"])["status"] == "UNAVAILABLE"
    assert other.get_model_metadata()["status"] == "INSUFFICIENT_DATA"


def test_failure_risk_only_absorbing_states_and_hidden_or_intervention_unavailable(tmp_path):
    svc, _ = service(tmp_path)
    risk = svc.estimate_failure_risk("pending", steps=2)
    assert risk["data"]["failure_probability_by_horizon"] == 0.25
    with pytest.raises(ValueError):
        svc.estimate_failure_risk("pending", failure_states=("running",))
    assert svc.infer_hidden_state()["reason"] == "NO_VALIDATED_HIDDEN_STATE_EMISSION_MODEL"
    assert svc.evaluate_intervention()["reason"] == "NO_VALIDATED_ACTION_REWARD_CAUSAL_EVIDENCE"
    scenario = svc.simulate_scenario("pending", steps=2, samples=10, seed=42)
    assert scenario["data"]["simulation"]["seed"] == 42
    assert scenario["grants_execution_authority"] is False


def test_scenario_comparison_pins_model_and_reports_conditional_probability_differences(tmp_path):
    svc, _ = service(tmp_path)
    result = svc.compare_scenarios({"baseline": "pending", "already_failed": "failed"}, steps=2)
    assert result["status"] == "SHADOW"
    assert result["data"]["probability_deltas"]["already_failed"]["failed"] == pytest.approx(0.75)
    assert result["data"]["causal_intervention"] is False
    versions = {v["model_version"] for v in result["data"]["scenarios"].values()}
    assert versions == {result["model_version"]}
    assert svc.get_prediction_evidence(result["trace_id"])["data"] == result


def test_unsupported_reachable_rows_produce_no_invented_prediction(tmp_path):
    svc = PIFService(tmp_path / "registry.db", enabled=True, min_transitions=1)
    result = svc.fit_history([history(1, ("a", "b"))], states=("a", "b"), alpha=1)
    assert result["status"] == "SHADOW"
    unavailable = svc.forecast_state("a", steps=2)
    assert unavailable["status"] == "INSUFFICIENT_DATA"
    assert "probabilities" not in unavailable["data"]


def test_registry_corruption_failure_isolated_and_no_executable_artifacts(tmp_path):
    svc, fit = service(tmp_path)
    with sqlite3.connect(svc.store.path) as db:
        db.execute("UPDATE pif_models SET artifact_json='{}'")
    assert svc.forecast_state("pending")["status"] == "UNAVAILABLE"
    assert svc.get_model_metadata()["status"] == "UNAVAILABLE"
    assert svc.select_model_version("queue-state", fit["model_version"])["status"] == "UNAVAILABLE"
    svc2 = PIFService(tmp_path, enabled=True)
    assert svc2.forecast_state("pending")["status"] == "UNAVAILABLE"


def test_prediction_tampering_detected(tmp_path):
    svc, _ = service(tmp_path)
    prediction = svc.predict_transition("pending")
    with sqlite3.connect(svc.store.path) as db:
        db.execute("UPDATE pif_predictions SET result_json='{}'")
    assert svc.get_prediction_evidence(prediction["trace_id"])["status"] == "UNAVAILABLE"


def test_independent_rollback_keeps_versions_events_and_core_registry(tmp_path):
    svc, first = service(tmp_path)
    rows, model = fit_model()
    second = svc.fit_history(
        rows, states=model.states, absorbing_states=model.absorbing_states, allowed_edges=model.allowed_edges, alpha=0.5
    )
    assert second["model_version"] != first["model_version"]
    rollback = svc.select_model_version("queue-state", first["model_version"])
    assert rollback["model_version"] == first["model_version"]
    with sqlite3.connect(svc.store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM pif_models").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM pif_events").fetchone()[0] == 5
    from app.model_registry import ModelRegistryStore

    existing = ModelRegistryStore(svc.store.path)
    assert existing.health()["models"] == 0
    assert existing.health()["events"] == 0


def create_ledger(path):
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE compute_jobs(id TEXT,agent TEXT,status TEXT,created_at TEXT,updated_at TEXT,prompt TEXT,result TEXT);"
        "CREATE TABLE compute_events(id TEXT,job_id TEXT,event_type TEXT,details_json TEXT,created_at TEXT);"
    )
    return db


def add_job(db, number, events, *, status="completed", agent="abex"):
    row = history(number, ["queued"] * len(events))
    db.execute(
        "INSERT INTO compute_jobs VALUES(?,?,?,?,?,?,?)",
        (
            row.entity_id,
            agent,
            status,
            row.observations[0].timestamp,
            row.observations[-1].timestamp,
            "PRIVATE_PROMPT_NEVER_EXPORTED",
            "PRIVATE_RESULT_NEVER_EXPORTED",
        ),
    )
    for observation, (kind, details) in zip(row.observations, events):
        db.execute(
            "INSERT INTO compute_events VALUES(?,?,?,?,?)",
            (observation.event_id, row.entity_id, kind, json.dumps(details), observation.timestamp),
        )


def test_readonly_queue_adapter_uses_real_semantics_preserves_ledger_and_omits_text(tmp_path):
    path = tmp_path / "queue.db"
    with create_ledger(path) as db:
        add_job(
            db,
            1,
            [
                ("submitted", {"status": "queued"}),
                ("claimed", {"worker": "worker"}),
                ("lease_expired", {"next_status": "queued"}),
                ("claimed", {}),
                ("completed", {}),
            ],
        )
        add_job(db, 2, [("cloud_reserved", {}), ("reservation_expired", {})], status="cancelled")
        add_job(db, 3, [("submitted", {"status": "queued"}), ("registry_denied", {})], status="failed")
    before = path.read_bytes()
    rows, report = read_compute_history(path)
    assert len(rows) == 3
    assert [o.state for o in rows[0].observations] == ["queued", "running", "queued", "running", "completed"]
    assert [o.state for o in rows[1].observations] == ["held", "cancelled"]
    assert all(h.evidence_kind == "observational_unclassified" for h in rows)
    assert "PRIVATE" not in json.dumps(report)
    assert "PRIVATE" not in json.dumps([h.as_dict() for h in rows])
    assert path.read_bytes() == before
    model = estimate_markov(rows, states=QUEUE_STATES, absorbing_states=QUEUE_ABSORBING, allowed_edges=QUEUE_EDGES)
    assert model.transition_count == 6
    filtered, _ = read_compute_history(path, agent="unknown")
    assert not filtered


def test_malformed_missing_mismatched_or_unknown_history_is_excluded_not_imputed(tmp_path):
    path = tmp_path / "queue.db"
    with create_ledger(path) as db:
        add_job(db, 1, [("completed", {})])
        add_job(db, 2, [("submitted", {"status": "queued"}), ("unknown-state-event", {})])
        add_job(db, 3, [("submitted", {"status": "queued"}), ("claimed", {})], status="completed")
        add_job(db, 4, [("submitted", {"status": "queued"}), ("completed", {}), ("claimed", {})], status="running")
    rows, report = read_compute_history(path)
    assert not rows
    assert report["diagnostics"]["missing_initial_event"] == 1
    assert report["diagnostics"]["invalid_histories_excluded"] == 2
    assert report["diagnostics"]["current_state_mismatch"] == 1


def test_queue_adapter_window_does_not_use_future_completion(tmp_path):
    path = tmp_path / "queue.db"
    with create_ledger(path) as db:
        add_job(db, 1, [("submitted", {"status": "queued"}), ("claimed", {}), ("completed", {})])
    cutoff = (BASE + timedelta(days=1, seconds=1)).isoformat()
    rows, _ = read_compute_history(path, until=cutoff)
    assert [o.state for o in rows[0].observations] == ["queued", "running"]
    assert read_compute_history(tmp_path / "missing.db")[1]["status"] == "UNAVAILABLE"


def test_store_queries_parameterized_and_identifiers_reject_path_or_sql(tmp_path):
    store = PIFStore(tmp_path / "registry.db")
    for tenant in ("../other", "x';DROP TABLE pif_models;--", "", "x" * 129):
        with pytest.raises(ValueError):
            store.load_model(tenant, "queue-state")
    assert not store.path.exists()


def test_actual_existing_queue_lifecycle_is_read_without_migration_or_dispatch(tmp_path):
    from app.job_queue import JobQueue, Provider, QueuePolicy

    path = tmp_path / "actual-queue.db"
    queue = JobQueue(path, QueuePolicy(local_ram_mb=8192))
    job = queue.submit(agent="a01", prompt="synthetic acceptance workload")
    provider = Provider("ollama", "local", "fast", 1024, 0, 1)
    assert queue.claim("test-worker", [provider])["id"] == job["id"]
    queue.finish(job["id"], result="synthetic completed result")
    rows, diagnostics = read_compute_history(path)
    assert len(rows) == 1
    assert [row.state for row in rows[0].observations] == ["queued", "running", "completed"]
    assert diagnostics["transition_count"] == 2
    assert queue.get(job["id"])["result"] == "synthetic completed result"
    assert queue.metrics()["statuses"] == {"completed": 1}


def test_missing_metadata_and_corrupt_storage_report_unavailable_independently(tmp_path):
    svc, _ = service(tmp_path)
    with sqlite3.connect(svc.store.path) as db:
        db.execute("UPDATE pif_models SET metadata_json='{}'")
    assert svc.forecast_state("pending")["status"] == "UNAVAILABLE"
    assert svc.health()["storage_status"] == "READABLE"
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a sqlite database")
    separate = PIFService(corrupt, enabled=True)
    assert separate.health()["status"] == "DEGRADED"
    assert separate.forecast_state("pending")["status"] == "UNAVAILABLE"
    assert svc.enabled is True


def test_shadow_report_end_to_end_uses_explicit_paths_preserves_original_and_refuses_overwrite(tmp_path):
    from scripts.pif_shadow_report import main

    path = tmp_path / "queue.db"
    with create_ledger(path) as db:
        for number in range(80):
            add_job(db, number, [("submitted", {"status": "queued"}), ("claimed", {}), ("completed", {})])
    before = path.read_bytes()
    output = tmp_path / "report.json"
    args = [
        "--queue",
        str(path),
        "--registry",
        str(tmp_path / "registry.db"),
        "--output",
        str(output),
        "--source-revision",
        "a" * 40,
    ]
    assert main(args) == 0
    report = json.loads(output.read_text())
    assert report["fit"]["status"] == "SHADOW"
    assert report["predictions"]["queued"]["status"] == "SHADOW"
    assert report["predictions"]["held"]["status"] == "INSUFFICIENT_DATA"
    assert report["production_quality_validated"] is False
    assert path.read_bytes() == before
    assert "PRIVATE" not in output.read_text()
    with pytest.raises(SystemExit):
        main(args)
