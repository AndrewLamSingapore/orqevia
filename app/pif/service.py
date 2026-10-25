"""Optional evidence-bearing probabilistic service, independent of execution."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import (
    History,
    MarkovModel,
    absorbing_analysis,
    identifier,
    integer,
    simulate,
    stationary_distribution,
    validate_histories,
    estimate_markov,
)
from .store import PIFStore, utcnow
from .validation import chronological_validation


ASSUMPTIONS = [
    "FIRST_ORDER_STATE_SUFFICIENCY_NOT_ESTABLISHED",
    "TIME_HOMOGENEITY_NOT_ESTABLISHED",
    "HORIZON_COUNTS_STATE_CHANGES_NOT_SECONDS",
    "OBSERVATIONAL_ASSOCIATION_NOT_CAUSAL_EFFECT",
    "PROSPECTIVE_PRODUCTION_QUALITY_NOT_VALIDATED",
]


class PIFService:
    """Eight stable service methods; adapters supply established auth/tenant scope.

    Construction and disabled calls have no persistence or networking effects.
    All returned predictions remain shadow decision support. No method dispatches
    an agent, changes a queue/job/objective, or grants operational authority.
    """

    def __init__(
        self,
        registry_path: str | Path | None = None,
        *,
        enabled: bool | None = None,
        tenant_id: str = "owner",
        min_transitions: int = 30,
        min_source_transitions: int = 5,
    ):
        identifier(tenant_id)
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled must be boolean or None")
        integer(min_transitions, minimum=1)
        integer(min_source_transitions, minimum=1)
        self._enabled = enabled
        self.tenant_id = tenant_id
        self.store = PIFStore(registry_path)
        self.min_transitions = min_transitions
        self.min_source_transitions = min_source_transitions

    @property
    def enabled(self) -> bool:
        return self._enabled if self._enabled is not None else os.getenv("ORQEVIA_PIF_ENABLED", "0") == "1"

    def _result(
        self,
        operation: str,
        status: str,
        *,
        reason: str | None = None,
        model: MarkovModel | None = None,
        model_id: str | None = None,
        horizon: int | None = None,
        data: Any = None,
    ) -> dict[str, Any]:
        return {
            "schema": "orqevia.pif.result.v1",
            "operation": operation,
            "status": status,
            "reason": reason,
            "trace_id": str(uuid.uuid4()),
            "generated_at": utcnow(),
            "model_id": model_id,
            "model_version": model.version if model else None,
            "model_provenance": {
                "method": "DISCRETE_MARKOV_ADDITIVE_SMOOTHING",
                "evidence_digest": model.evidence_digest,
                "evidence_kinds": list(model.evidence_kinds),
                "entities": model.entity_count,
                "transitions": model.transition_count,
            }
            if model
            else None,
            "observation_period": [model.observation_start, model.observation_end] if model else None,
            "forecast_horizon": horizon,
            "horizon_unit": "STATE_CHANGE_EVENTS",
            "reliability": "SHADOW_UNVALIDATED" if model else "UNAVAILABLE",
            "assumptions": list(ASSUMPTIONS),
            "grants_execution_authority": False,
            "data": data,
        }

    def _unavailable(self, operation: str, status: str, reason: str) -> dict[str, Any]:
        return self._result(operation, status, reason=reason)

    def health(self) -> dict[str, Any]:
        # Health is configuration/service availability, not a forecast-quality
        # assertion. No registry creation or heavy work on this startup path.
        storage = "NOT_INITIALIZED"
        if self.enabled and self.store.path.exists():
            try:
                db = sqlite3.connect(self.store.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
                try:
                    db.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
                finally:
                    db.close()
                storage = "READABLE"
            except (OSError, sqlite3.Error):
                storage = "UNAVAILABLE"
        status = "DISABLED" if not self.enabled else "DEGRADED" if storage == "UNAVAILABLE" else "AVAILABLE_SHADOW"
        return {
            "capability": "PIF",
            "enabled": self.enabled,
            "status": status,
            "storage_initialized": self.store.path.is_file(),
            "storage_status": storage,
            "hidden_state_inference": "UNAVAILABLE_VALIDATION_REQUIRED",
            "intervention_estimation": "UNAVAILABLE_ACTION_REWARD_EVIDENCE_REQUIRED",
            "core_dependency": False,
            "grants_execution_authority": False,
        }

    def fit_history(
        self,
        histories: Iterable[History],
        *,
        model_id: str = "queue-state",
        states: Sequence[str],
        absorbing_states: Sequence[str] = (),
        alpha: float = 0.5,
        allowed_edges: Iterable[tuple[str, str]] | None = None,
        since: str | None = None,
        until: str | None = None,
        validation_cutoff: str | None = None,
        source_revision: str | None = None,
        evidence_source: str = "EXPLICIT_OBSERVATION_HISTORIES",
    ) -> dict[str, Any]:
        operation = "fit_history"
        if not self.enabled:
            return self._unavailable(operation, "DISABLED", "PIF_FLAG_DISABLED")
        identifier(model_id)
        identifier(evidence_source)
        if source_revision is not None:
            if not isinstance(source_revision, str) or not re.fullmatch("[0-9a-f]{40}", source_revision):
                raise ValueError("source revision must be an exact Git SHA")
        rows = validate_histories(histories)
        edges = tuple(allowed_edges) if allowed_edges is not None else None
        model = estimate_markov(
            rows,
            states=states,
            absorbing_states=absorbing_states,
            alpha=alpha,
            allowed_edges=edges,
            since=since,
            until=until,
        )
        if not model.transition_count:
            return self._result(
                operation, "INSUFFICIENT_DATA", reason="NO_OBSERVED_TRANSITIONS", model=model, model_id=model_id
            )
        # Validation receives only observations within the same fit window;
        # never evaluate off-window data as evidence for this artifact.
        windowed = []
        from .core import timestamp

        lower, upper = timestamp(since) if since else None, timestamp(until) if until else None
        for history in rows:
            observations = tuple(
                row
                for row in history.observations
                if (lower is None or row.timestamp >= lower) and (upper is None or row.timestamp <= upper)
            )
            if observations:
                windowed.append(History(history.entity_id, observations, history.evidence_kind))
        evaluation = chronological_validation(
            windowed,
            states=states,
            absorbing_states=absorbing_states,
            alpha=alpha,
            allowed_edges=edges,
            cutoff=validation_cutoff,
            min_train_transitions=self.min_transitions,
        )
        metadata = {
            "source_revision": source_revision,
            "evidence_source": evidence_source,
            "evaluation": evaluation,
            "deployment_mode": "SHADOW_ONLY",
            "min_transitions": self.min_transitions,
            "min_source_transitions": self.min_source_transitions,
            "observation_time_semantics": "STATE_CHANGE_EVENTS",
            "production_quality_validated": False,
        }
        try:
            self.store.save_model(self.tenant_id, model_id, model, metadata)
            _, recorded = self.store.load_model(self.tenant_id, model_id, model.version)
        except (OSError, sqlite3.Error, ValueError, KeyError):
            return self._unavailable(operation, "UNAVAILABLE", "PIF_REGISTRY_UNAVAILABLE_OR_INVALID")
        return self._result(
            operation,
            "SHADOW" if model.transition_count >= self.min_transitions else "INSUFFICIENT_DATA",
            reason="FIT_RECORDED_NO_PRODUCTION_PROMOTION",
            model=model,
            model_id=model_id,
            data={
                "metadata": recorded,
                "analysis": {"absorption": absorbing_analysis(model), "stationary": stationary_distribution(model)},
            },
        )

    def _load(self, operation: str, model_id: str, version: str | None):
        if not self.enabled:
            return None, None, self._unavailable(operation, "DISABLED", "PIF_FLAG_DISABLED")
        try:
            model, metadata = self.store.load_model(self.tenant_id, model_id, version)
        except KeyError:
            return None, None, self._unavailable(operation, "INSUFFICIENT_DATA", "NO_OBSERVED_MODEL_IN_SCOPE")
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return None, None, self._unavailable(operation, "UNAVAILABLE", "PIF_REGISTRY_UNAVAILABLE_OR_INVALID")
        try:
            if not isinstance(metadata, dict) or metadata.get("deployment_mode") != "SHADOW_ONLY":
                raise ValueError("invalid shadow model metadata")
            integer(metadata["min_transitions"], minimum=1)
            integer(metadata["min_source_transitions"], minimum=1)
            if (
                not isinstance(metadata["evaluation"], dict)
                or metadata.get("production_quality_validated") is not False
            ):
                raise ValueError("invalid quality metadata")
            return model, metadata, None
        except (KeyError, ValueError, TypeError):
            return None, None, self._unavailable(operation, "UNAVAILABLE", "PIF_REGISTRY_UNAVAILABLE_OR_INVALID")

    def _forecast(
        self, operation: str, start: str | Mapping[str, float], *, steps: int, model_id: str, version: str | None
    ) -> tuple[MarkovModel | None, dict[str, Any]]:
        integer(steps)
        model, metadata, failure = self._load(operation, model_id, version)
        if failure:
            return None, failure
        model.initial(start)  # Validate even for zero-horizon or insufficient fits.
        minimum = max(self.min_transitions, metadata["min_transitions"])
        source_minimum = max(self.min_source_transitions, metadata["min_source_transitions"])
        if model.transition_count < minimum:
            return None, self._result(
                operation,
                "INSUFFICIENT_DATA",
                reason="MINIMUM_OBSERVED_TRANSITIONS_NOT_MET",
                model=model,
                model_id=model_id,
                horizon=steps,
            )
        unsupported = model.unsupported_states(start, steps, source_minimum)
        if unsupported:
            return None, self._result(
                operation,
                "INSUFFICIENT_DATA",
                reason="REACHABLE_STATE_LACKS_EVIDENCE",
                model=model,
                model_id=model_id,
                horizon=steps,
                data={"unsupported_states": unsupported},
            )
        result = self._result(
            operation,
            "SHADOW",
            model=model,
            model_id=model_id,
            horizon=steps,
            data={
                "probabilities": model.forecast(start, steps),
                "initial_state": start if isinstance(start, str) else dict(start),
                "quality_evaluation": metadata["evaluation"],
            },
        )
        return model, result

    def _record(self, result: dict[str, Any]) -> dict[str, Any]:
        if result["status"] != "SHADOW":
            return result
        try:
            self.store.record_prediction(self.tenant_id, result)
        except (OSError, sqlite3.Error, ValueError):
            return self._unavailable(result["operation"], "UNAVAILABLE", "PREDICTION_EVIDENCE_NOT_PERSISTED")
        return result

    def predict_transition(
        self, start: str | Mapping[str, float], *, model_id: str = "queue-state", version: str | None = None
    ) -> dict[str, Any]:
        _, result = self._forecast("predict_transition", start, steps=1, model_id=model_id, version=version)
        return self._record(result)

    def forecast_state(
        self,
        start: str | Mapping[str, float],
        *,
        steps: int = 1,
        model_id: str = "queue-state",
        version: str | None = None,
    ) -> dict[str, Any]:
        _, result = self._forecast("forecast_state", start, steps=steps, model_id=model_id, version=version)
        return self._record(result)

    def estimate_failure_risk(
        self,
        start: str | Mapping[str, float],
        *,
        steps: int = 2,
        failure_states: Sequence[str] = ("failed",),
        model_id: str = "queue-state",
        version: str | None = None,
    ) -> dict[str, Any]:
        model, result = self._forecast("estimate_failure_risk", start, steps=steps, model_id=model_id, version=version)
        if model:
            if not failure_states or not set(failure_states) <= set(model.absorbing_states):
                raise ValueError("failure-risk targets must be known, absorbing states")
            result["data"]["failure_states"] = sorted(set(failure_states))
            result["data"]["failure_probability_by_horizon"] = sum(
                result["data"]["probabilities"][s] for s in set(failure_states)
            )
            result["data"]["definition"] = "ABSORBING_FAILURE_OCCUPANCY_BY_EVENT_HORIZON"
        return self._record(result)

    def simulate_scenario(
        self,
        start: str | Mapping[str, float],
        *,
        steps: int,
        samples: int,
        seed: int,
        model_id: str = "queue-state",
        version: str | None = None,
    ) -> dict[str, Any]:
        integer(samples, minimum=1)
        integer(seed)
        model, result = self._forecast("simulate_scenario", start, steps=steps, model_id=model_id, version=version)
        if model:
            result["data"]["simulation"] = simulate(model, start, steps=steps, samples=samples, seed=seed)
        return self._record(result)

    def infer_hidden_state(self, *args, **kwargs) -> dict[str, Any]:
        return self._unavailable(
            "infer_hidden_state",
            "UNAVAILABLE" if self.enabled else "DISABLED",
            "NO_VALIDATED_HIDDEN_STATE_EMISSION_MODEL" if self.enabled else "PIF_FLAG_DISABLED",
        )

    def compare_scenarios(
        self,
        scenarios: Mapping[str, str | Mapping[str, float]],
        *,
        steps: int,
        model_id: str = "queue-state",
        version: str | None = None,
    ) -> dict[str, Any]:
        """Compare predictive initial conditions under one pinned model version.

        This compares conditional scenarios, not effects of manipulating actions.
        A changed initial condition is not an identified causal intervention.
        """
        if not isinstance(scenarios, Mapping) or len(scenarios) < 2:
            raise ValueError("comparison requires at least two named scenarios")
        integer(steps)
        for name in scenarios:
            identifier(name)
        model, _, failure = self._load("compare_scenarios", model_id, version)
        if failure:
            return failure
        results = {
            name: self.forecast_state(start, steps=steps, model_id=model_id, version=model.version)
            for name, start in scenarios.items()
        }
        if any(result["status"] != "SHADOW" for result in results.values()):
            return self._result(
                "compare_scenarios",
                "INSUFFICIENT_DATA",
                reason="SCENARIO_EVIDENCE_INCOMPLETE",
                model=model,
                model_id=model_id,
                horizon=steps,
                data={"scenarios": results, "causal_intervention": False},
            )
        reference = next(iter(scenarios))
        baseline = results[reference]["data"]["probabilities"]
        deltas = {
            name: {state: result["data"]["probabilities"][state] - baseline[state] for state in model.states}
            for name, result in results.items()
        }
        return self._record(
            self._result(
                "compare_scenarios",
                "SHADOW",
                model=model,
                model_id=model_id,
                horizon=steps,
                data={
                    "reference_scenario": reference,
                    "scenarios": results,
                    "probability_deltas": deltas,
                    "causal_intervention": False,
                },
            )
        )

    def evaluate_intervention(self, *args, **kwargs) -> dict[str, Any]:
        return self._unavailable(
            "evaluate_intervention",
            "UNAVAILABLE" if self.enabled else "DISABLED",
            "NO_VALIDATED_ACTION_REWARD_CAUSAL_EVIDENCE" if self.enabled else "PIF_FLAG_DISABLED",
        )

    def get_prediction_evidence(self, trace_id: str) -> dict[str, Any]:
        if not self.enabled:
            return self._unavailable("get_prediction_evidence", "DISABLED", "PIF_FLAG_DISABLED")
        try:
            prediction = self.store.prediction(self.tenant_id, trace_id)
        except KeyError:
            return self._unavailable("get_prediction_evidence", "UNAVAILABLE", "NO_PREDICTION_IN_TENANT_SCOPE")
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return self._unavailable(
                "get_prediction_evidence", "UNAVAILABLE", "PREDICTION_EVIDENCE_INVALID_OR_UNAVAILABLE"
            )
        return self._result("get_prediction_evidence", "AVAILABLE", data=prediction)

    def get_model_metadata(self, *, model_id: str = "queue-state", version: str | None = None) -> dict[str, Any]:
        model, metadata, failure = self._load("get_model_metadata", model_id, version)
        if failure:
            return failure
        return self._result(
            "get_model_metadata",
            "AVAILABLE",
            model=model,
            model_id=model_id,
            data={"metadata": metadata, "artifact": model.as_dict()},
        )

    def select_model_version(self, model_id: str, version: str) -> dict[str, Any]:
        if not self.enabled:
            return self._unavailable("select_model_version", "DISABLED", "PIF_FLAG_DISABLED")
        try:
            self.store.load_model(self.tenant_id, model_id, version)
            self.store.select_version(self.tenant_id, model_id, version)
        except KeyError:
            return self._unavailable("select_model_version", "UNAVAILABLE", "MODEL_VERSION_NOT_IN_TENANT_SCOPE")
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return self._unavailable("select_model_version", "UNAVAILABLE", "MODEL_VERSION_INVALID_OR_UNAVAILABLE")
        return self.get_model_metadata(model_id=model_id, version=version)
