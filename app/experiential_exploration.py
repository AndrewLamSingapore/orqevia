"""Bounded, local-only retrieval adaptation; never model training or L7 proof.

This opt-in library reuses the registry, handoff enforcement, governed memory
and Phase2 continuity kernel. It does not register a production route, execute
arbitrary code, call a model, or authorize production skill promotion.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .agent_registry import agent_record, registered_agent_ids
from .agent_runtime import AgentAuthorityRuntime
from .general_intelligence import evaluate_lesson
from .memory import MemoryStore
from .phase2_intelligence import AuthorityEnvelope, Phase2Kernel, canonical, digest

STRATEGIES = ("preserve", "reverse", "ascending")
TRAIN = ((3, 1, 2), (4, 2, 2, -1), (7, 0, 5))
HELD_OUT = ((19, -8, 0, 19), (2, -11, 5), (6, 3, -4, 1))


def simulate(strategy: str, values: tuple[int, ...]) -> dict:
    """Finite symbolic environment: only whitelisted bounded integer operations."""
    if strategy not in STRATEGIES:
        raise ValueError("unknown strategy")
    if not isinstance(values, tuple) or not 1 <= len(values) <= 32:
        raise ValueError("bounded tuple required")
    if any(type(value) is not int or abs(value) > 100_000 for value in values):
        raise ValueError("bounded integers required")
    result = tuple(values if strategy == "preserve" else reversed(values)
                   if strategy == "reverse" else sorted(values))
    # Observations, not a scalar reward or model evaluation.
    return {"input": list(values), "output": list(result),
            "permutation": sorted(result) == sorted(values),
            "ordered": all(a <= b for a, b in zip(result, result[1:])),
            "mode": "deterministic_symbolic_simulation"}


class ExplorationSandbox:
    """Explicit isolated directory and persistent per-agent call budgets.

    Independent challenge is local fixture evidence. Promotion authorization is
    an injected, existing-trust-boundary verifier, deny by default; even accepted
    promotion only admits this sandbox's versioned procedure, never production.
    """

    def __init__(self, root: str | Path, *, max_trials: int = 12,
                 promotion_verifier=None, clock=time.time):
        if type(max_trials) is not int or not 9 <= max_trials <= 100:
            raise ValueError("trial budget must be 9..100")
        original = Path(root).absolute()
        if any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
               for parent in (original, *original.parents)):
            raise ValueError("sandbox may not use symbolic links")
        self.root = original.resolve()
        if self.root.exists() and any(self.root.iterdir()) and not (self.root / "EXPLORATION-SANDBOX.json").is_file():
            raise ValueError("refuse existing unmarked directory")
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / "EXPLORATION-SANDBOX.json"
        expected = {"schema": 1, "scope": "local-simulation-only", "production": False}
        if marker.exists() and json.loads(marker.read_text()) != expected:
            raise ValueError("invalid sandbox marker")
        marker.write_text(canonical(expected), encoding="utf-8")
        self.clock = clock
        self.max_trials = max_trials
        self.verify_promotion = promotion_verifier or (lambda *_: False)
        for name in ("experience.sqlite", "continuity.sqlite", "authority.sqlite"):
            if (self.root / name).is_symlink():
                raise ValueError("sandbox database may not use symbolic links")
        self.memory = MemoryStore(str(self.root / "experience.sqlite"))
        self.kernel = Phase2Kernel(self.root / "continuity.sqlite", clock=clock)
        self.runtime = AgentAuthorityRuntime(self.root / "authority.sqlite")
        with self.memory.connect() as db:
            db.executescript("""
              create table if not exists exploration_runs(
                run_id text primary key, agent_id text not null, objective_id text not null,
                trials integer not null default 0, trial_limit integer not null);
              create table if not exists exploration_candidates(
                candidate_id text primary key, body text not null, sha256 text not null);
              create table if not exists exploration_reviews(
                candidate_id text primary key, reviewer text not null, body text not null, sha256 text not null);
              create table if not exists exploration_versions(
                agent_id text not null, version integer not null, candidate_id text not null,
                authorization_hash text not null, active integer not null,
                primary key(agent_id,version));
              create table if not exists exploration_authorizations(
                receipt_hash text primary key, binding_hash text not null);
            """)

    def _agent(self, agent: str) -> dict:
        if agent not in registered_agent_ids(include_orchestrator=False):
            raise ValueError("canonical registered specialist required")
        return agent_record(agent)

    def _authority(self, agent: str) -> AuthorityEnvelope:
        return AuthorityEnvelope(agent, "APPLICATION", frozenset({
            "objective.create", "objective.read", "objective.update"}), self.clock() + 60)

    def start(self, agent: str) -> str:
        self._agent(agent)
        objective = self.kernel.create_objective(
            objective="Explore permutation-preserving ordering in the isolated symbolic environment",
            success_criteria=["Preserve attributable observations, including counterexamples"],
            constraints=["No network, model calls, arbitrary code or production mutation"],
            authority=self._authority(agent))
        run = str(uuid.uuid4())
        with self.memory.connect() as db:
            db.execute("insert into exploration_runs values(?,?,?,0,?)",
                       (run, agent, objective["objective_id"], self.max_trials))
        return run

    def observe(self, run_id: str, strategy: str, values: tuple[int, ...]) -> dict:
        observation = simulate(strategy, values)
        # Reserve a trial atomically before invoking persistence. A failed write
        # consumes budget; restart cannot recover a fresh infinite retry window.
        with self.memory.connect() as db:
            db.execute("begin immediate")
            row = db.execute("select * from exploration_runs where run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("unknown run")
            self._agent(row["agent_id"])
            if row["trials"] >= row["trial_limit"]:
                raise ValueError("persistent trial budget exhausted")
            db.execute("update exploration_runs set trials=trials+1 where run_id=?", (run_id,))
        episode = self.memory.record_episode(event_type="exploration_observation",
            content={"run_id": run_id, "agent_id": row["agent_id"], "strategy": strategy,
                     "observation": observation, "contamination": "simulation_fixture"},
            source="isolated-symbolic-environment")
        self.kernel.record_attempt(row["objective_id"], authority=self._authority(row["agent_id"]),
            strategy={"strategy": strategy}, evidence=observation,
            outcome="ORDERED" if observation["ordered"] else "COUNTEREXAMPLE")
        return {**observation, "episode_id": episode["episode_id"]}

    def explore(self, run_id: str) -> dict:
        """Deterministic strategy discovery without a user task or scalar reward.

        This is a finite algorithmic search, explicitly not model self-direction.
        No held-out observations are supplied to this discovery procedure.
        """
        with self.memory.connect() as db:
            run = db.execute("select * from exploration_runs where run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("unknown run")
        with self.memory.connect() as db:
            candidates = db.execute("select candidate_id,body from exploration_candidates").fetchall()
            episodes = db.execute("select episode_id,content_json from episodic_memory where event_type='exploration_observation'").fetchall()
        for existing in candidates:
            if json.loads(existing["body"])["run_id"] == run_id:
                return {"candidate_id": existing["candidate_id"], **self.candidate(existing["candidate_id"])}
        retained = {}
        for episode in episodes:
            content = json.loads(episode["content_json"])
            if content["run_id"] == run_id:
                if content["observation"] != simulate(content["strategy"], tuple(content["observation"]["input"])):
                    raise ValueError("retained observation differs from reproducible environment")
                retained[(content["strategy"], tuple(content["observation"]["input"]))] = {
                    **content["observation"], "episode_id": episode["episode_id"]}
        failures, observations = [], []
        selected = None
        for strategy in STRATEGIES:
            hypothesis = self.kernel.add_hypothesis(run["objective_id"],
                authority=self._authority(run["agent_id"]),
                proposition=f"{strategy} preserves permutation and establishes ordering",
                test={"environment": "integer-ordering", "training_cases": len(TRAIN)})
            results = [retained[(strategy, values)] if (strategy, values) in retained
                       else self.observe(run_id, strategy, values) for values in TRAIN]
            observations.extend(results)
            support = [result["episode_id"] for result in results if result["ordered"]]
            counterexamples = [result["episode_id"] for result in results if not result["ordered"]]
            self.kernel.evaluate_hypothesis(hypothesis, support=support,
                contradictions=counterexamples, authority=self._authority(run["agent_id"]))
            if counterexamples:
                failures.append(strategy)
            elif all(result["permutation"] for result in results):
                selected = strategy
                break
        if selected is None:
            raise ValueError("no supported strategy within budget")
        with self.memory.connect() as db:
            episode_hashes = {o["episode_id"]: digest(json.loads(db.execute(
                "select content_json from episodic_memory where episode_id=?",
                (o["episode_id"],)).fetchone()[0])) for o in observations}
        candidate = {"agent_id": run["agent_id"], "run_id": run_id,
            "strategy": selected, "failed_strategies": failures,
            "episodes": [o["episode_id"] for o in observations],
            "episode_hashes": episode_hashes,
            "scope": "simulation_fixture", "training_case_hash": digest(TRAIN),
            "grants_authority": False, "model_weight_training": False}
        candidate_id = digest(candidate)
        with self.memory.connect() as db:
            db.execute("insert into exploration_candidates values(?,?,?)",
                       (candidate_id, canonical(candidate), digest(candidate)))
        return {"candidate_id": candidate_id, **candidate}

    def candidate(self, candidate_id: str) -> dict:
        with self.memory.connect() as db:
            row = db.execute("select * from exploration_candidates where candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise ValueError("unknown candidate")
        body = json.loads(row["body"])
        if digest(body) != row["sha256"] or digest(body) != candidate_id:
            raise ValueError("candidate provenance changed")
        self._agent(body["agent_id"])
        with self.memory.connect() as db:
            for episode_id in body["episodes"]:
                episode = db.execute("select content_json from episodic_memory where episode_id=?",
                                     (episode_id,)).fetchone()
                if episode is None or digest(json.loads(episode[0])) != body["episode_hashes"][episode_id]:
                    raise ValueError("experience provenance changed")
        return body

    def challenge(self, candidate_id: str, reviewer: str) -> dict:
        candidate = self.candidate(candidate_id)
        self._agent(reviewer)
        if reviewer == candidate["agent_id"]:
            raise PermissionError("independent registered reviewer required")
        self.runtime.handoff(source=candidate["agent_id"], target=reviewer, relation="consult")
        results = [simulate(candidate["strategy"], values) for values in HELD_OUT]
        decision = evaluate_lesson(candidate["strategy"],
            [r["ordered"] and r["permutation"] for r in results],
            provenance=tuple(candidate["episodes"]), counterexample_checked=True)
        body = {"candidate_id": candidate_id, "reviewer": reviewer,
            "disposition": decision.disposition, "held_out_hash": digest(HELD_OUT),
            "observations": results, "scope": "simulation_fixture", "production_authorized": False}
        with self.memory.connect() as db:
            db.execute("insert into exploration_reviews values(?,?,?,?)",
                       (candidate_id, reviewer, canonical(body), digest(body)))
        return body

    def _review(self, candidate_id: str) -> dict:
        with self.memory.connect() as db:
            row = db.execute("select * from exploration_reviews where candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise PermissionError("independent verification missing")
        body = json.loads(row["body"])
        if (digest(body) != row["sha256"] or body.get("disposition") != "STORE"
                or body.get("candidate_id") != candidate_id or body.get("scope") != "simulation_fixture"
                or body.get("production_authorized") is not False or body.get("held_out_hash") != digest(HELD_OUT)):
            raise PermissionError("verified review required")
        return body

    def admit(self, candidate_id: str, *, authorization: dict) -> int:
        candidate = self.candidate(candidate_id)
        self._review(candidate_id)
        binding = {"operation": "sandbox-skill-admission", "candidate_id": candidate_id,
                   "scope": "simulation_fixture", "agent_id": candidate["agent_id"]}
        if self.verify_promotion(authorization, binding) is not True:
            raise PermissionError("separate admission authorization required")
        with self.memory.connect() as db:
            db.execute("begin immediate")
            db.execute("insert into exploration_authorizations values(?,?)",
                       (digest(authorization), digest(binding)))
            version = db.execute("select coalesce(max(version),0)+1 from exploration_versions where agent_id=?",
                                 (candidate["agent_id"],)).fetchone()[0]
            db.execute("update exploration_versions set active=0 where agent_id=?", (candidate["agent_id"],))
            db.execute("insert into exploration_versions values(?,?,?,?,1)",
                       (candidate["agent_id"], version, candidate_id, digest(authorization)))
        # This is a verified local candidate, never MemoryStore procedural owner
        # privilege. The production governed procedural path remains unchanged.
        self.memory.record_episode(event_type="sandbox_skill_admitted",
            content={**binding, "version": version}, source="verified-sandbox-admission")
        return version

    def rollback(self, agent: str, version: int, *, authorization: dict) -> None:
        self._agent(agent)
        binding = {"operation": "sandbox-skill-rollback", "agent_id": agent,
                   "version": version, "scope": "simulation_fixture"}
        if self.verify_promotion(authorization, binding) is not True:
            raise PermissionError("separate rollback authorization required")
        with self.memory.connect() as db:
            db.execute("begin immediate")
            target = db.execute("select candidate_id from exploration_versions where agent_id=? and version=?",
                                (agent, version)).fetchone()
            if target is None:
                raise ValueError("unknown skill version")
            self.candidate(target[0]); self._review(target[0])
            db.execute("insert into exploration_authorizations values(?,?)",
                       (digest(authorization), digest(binding)))
            db.execute("update exploration_versions set active=(version=?) where agent_id=?", (version, agent))
        self.memory.record_episode(event_type="sandbox_skill_rollback", content=binding,
                                   source="verified-sandbox-rollback")

    def transfer(self, producer: str, consumer: str, values: tuple[int, ...]) -> dict:
        producer_record = self._agent(producer); consumer_record = self._agent(consumer)
        producer_lead = producer if producer_record["can_delegate"] else producer_record["reports_to"]
        consumer_lead = consumer if consumer_record["can_delegate"] else consumer_record["reports_to"]
        # Existing consultation graph: specialists consult their own leads;
        # only leads consult other leads. Knowledge does not transfer authority.
        for source, target in {(producer, producer_lead), (consumer, consumer_lead),
                               (consumer_lead, producer_lead)}:
            if source != target:
                self.runtime.handoff(source=source, target=target, relation="consult")
        with self.memory.connect() as db:
            row = db.execute("select * from exploration_versions where agent_id=? and active=1", (producer,)).fetchone()
        if row is None:
            raise PermissionError("unadmitted skill cannot propagate")
        candidate = self.candidate(row["candidate_id"]); self._review(row["candidate_id"])
        if candidate["agent_id"] != producer:
            raise ValueError("skill ownership provenance changed")
        result = simulate(candidate["strategy"], values)
        self.memory.record_episode(event_type="validated_sandbox_transfer", source="canonical-consultation",
            content={"producer": producer, "consumer": consumer, "candidate_id": row["candidate_id"],
                     "observation": result, "scope": "simulation_fixture"})
        return {**result, "producer": producer, "consumer": consumer, "skill_version": row["version"]}

    def history(self, agent: str, *, query: str = "", limit: int = 100) -> list[dict]:
        self._agent(agent)
        if type(limit) is not int or not 1 <= limit <= 1000 or len(query) > 1000:
            raise ValueError("bounded history query required")
        with self.memory.connect() as db:
            rows = db.execute("select content_json from episodic_memory where event_type='exploration_observation'").fetchall()
        return [json.loads(row[0]) for row in rows
                if json.loads(row[0])["agent_id"] == agent and query.casefold() in row[0].casefold()][:limit]
