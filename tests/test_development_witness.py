"""A01-A45: executable development adversaries; no production qualification.

BOUNDARY cases prove denial when required platform evidence is absent, never
claim to simulate TPM/kernel compromise away. Transition cross-product below
supplements (does not replace) the unchanged standalone checkpoint oracle.
"""
import copy
import json
import pickle
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.development_witness import (Anchor, Capsule, Denied, FakeProvider, Journal,
                                     WitnessFrontend, authorize_development,
                                     bootstrap_development, canonical, digest, sign)
from app.spine import PLATFORM_POLICY
from tests.test_harness_execution import rig, queued, run


@pytest.fixture
def model(rig, tmp_path):
    job, envelope = queued(rig)
    cap, owner = bootstrap_development(tmp_path / "independent" / "root.db", rig[2], rig[1])
    approval = authorize_development(cap, envelope)
    return cap, owner, job, envelope, approval


def execute(model):
    cap, _, job, envelope, _ = model
    return cap.execute(envelope, job["prompt"])


def command(cap, operation, **fields):
    if operation == "activate":
        fields.setdefault("spine_key", cap.root.read()["spine_key"])
        fields.setdefault("provider_key", cap.root.read()["provider_key"])
    return cap.signer.transition(cap.root.read(), operation, **fields)


def right(model):
    return model[0].root.read()["rights"][model[3]["authorization"]["lease_id"]]


def fail_at(point):
    def fail(observed):
        if observed == point:
            raise RuntimeError("synthetic crash: " + point)
    return fail


def test_A01_existing_checkpoint_oracle():
    from scripts.probe_checkpoint_replay import main
    assert main() == 0


def test_A02_concurrent_cloned_requests(model):
    cap = model[0]
    def attempt(_):
        try:
            execute(model)
            return True
        except Denied:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(16))) == 1
    assert cap.provider.starts == cap.provider.max_active == 1


def test_A03_root_rollback_and_fabricated_head(model, tmp_path):
    cap = model[0]
    backup = tmp_path / "before.db"
    shutil.copyfile(cap.root.path, backup)
    execute(model)
    shutil.copyfile(backup, cap.root.path)
    with pytest.raises(Denied):
        execute(model)
    with pytest.raises(Denied):
        WitnessFrontend(cap).request("replace_head", {"sequence": 999999, "slot": None})
    assert cap.provider.starts == 1


def test_A04_root_loss_no_bootstrap(model):
    cap = model[0]
    cap.root.anchor.available = False
    with pytest.raises(Denied):
        execute(model)
    with pytest.raises(Denied):
        Journal(cap.root.path, Anchor())
    assert cap.provider.starts == 0


def test_A05_worker_snapshot_and_capsule_clone(model):
    restored_envelope = pickle.loads(pickle.dumps(model[3]))
    execute(model)
    with pytest.raises(Denied):
        model[0].execute(restored_envelope, model[2]["prompt"])
    with pytest.raises(Denied):
        copy.copy(model[0])
    assert model[0].provider.starts == 1


@pytest.mark.parametrize("op", ["approve", "derive", "replace_head", "complete", "activate", "reset", "release", "reissue"])
def test_A06_frontend_has_no_authority_operations(model, op):
    with pytest.raises(Denied):
        WitnessFrontend(model[0]).request(op, model[4])
    assert model[0].provider.starts == 0


@pytest.mark.parametrize("field", ["signature", "domain", "estate", "epoch", "session", "generation", "policy", "id", "envelope"])
def test_A07_every_signed_binding_rejects_tamper(model, field):
    approval = copy.deepcopy(model[4])
    if field in {"signature", "domain"}:
        approval[field] = "forged"
    else:
        approval["body"][field] = "forged"
    with pytest.raises(Denied):
        model[0].register(approval)
    assert model[0].provider.starts == 0


@pytest.mark.parametrize("stage", ["before", "after_consume"])
def test_A08_effective_revocation_before_actual_start(model, stage):
    cap = model[0]
    revoke = lambda: cap.transition(command(cap, "revoke", id=model[3]["authorization"]["lease_id"]))
    if stage == "before":
        revoke()
    else:
        cap.fault = lambda point: revoke() if point == "after_consume" else None
    with pytest.raises(Denied):
        execute(model)
    assert cap.provider.starts == 0


@pytest.mark.parametrize("interval", [(0, 1), (2**62, 2**62 + 1), (10, 9), (None, None)])
def test_A09_time_uncertainty_or_expiry_denies(model, interval):
    model[0].clock = lambda: interval
    with pytest.raises(Denied):
        execute(model)
    assert model[0].provider.starts == 0


def test_A10_status_and_registration_never_reissue(model):
    execute(model)
    assert model[0].register(model[4])["state"] == "CONSUMED"
    WitnessFrontend(model[0]).request("status")
    with pytest.raises(Denied):
        execute(model)
    assert model[0].provider.starts == 1


@pytest.mark.parametrize("point,consumed", [("before_prepare", False), ("after_prepare", False), ("after_head", True)])
def test_A11_consumption_crash_boundaries(model, point, consumed):
    cap = model[0]
    cap.root.fault = fail_at(point)
    with pytest.raises(RuntimeError):
        execute(model)
    cap.root.fault = lambda _: None
    cap.root = Journal(cap.root.path, cap.root.anchor)
    state = cap.root.read()
    key = model[3]["authorization"]["lease_id"]
    assert (state["rights"][key]["state"] == "CONSUMED") == consumed
    assert (state["slot"] == key) == consumed
    assert cap.provider.starts == 0
    if consumed:
        with pytest.raises(Denied):
            execute(model)


@pytest.mark.parametrize("point", ["after_consume", "after_start", "before_terminal"])
def test_A12_crash_never_replays_consumed_attempt(model, point):
    cap = model[0]
    cap.fault = fail_at(point)
    with pytest.raises(RuntimeError):
        execute(model)
    cap.fault = lambda _: None
    starts = cap.provider.starts
    with pytest.raises(Denied):
        execute(model)
    assert cap.provider.starts == starts
    assert right(model)["state"] == "CONSUMED"


def test_A13_terminal_recovery_no_inference(model):
    cap = model[0]
    cap.fault = fail_at("before_terminal")
    with pytest.raises(RuntimeError):
        execute(model)
    assert cap.status()["slot"] is not None
    cap.recover()
    cap.recover()
    assert cap.status()["slot"] is None
    assert right(model)["audit"] == "completed"
    assert cap.provider.starts == 1


def test_A14_distinct_jobs_global_slot(model, rig):
    cap = model[0]
    # An independent/restored queue may consider the first job finished. The
    # surviving witness must still enforce its own estate-wide occupancy.
    rig[3].finish(model[2]["id"], result="untrusted queue bookkeeping")
    job2, env2 = queued(rig, "a16")
    authorize_development(cap, env2)
    cap.provider.wait = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, model)
        # Block until the first call has actually entered the provider.
        for _ in range(1000):
            if cap.provider.active:
                break
            threading.Event().wait(.001)
        assert cap.provider.active == 1
        with pytest.raises(Denied):
            cap.execute(env2, job2["prompt"])
        cap.provider.wait.set()
        first.result(timeout=5)
    assert cap.provider.max_active == 1


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:11434", "http://ollama:11434", "http://[::1]:11434", "docker.sock", "sdk", "exec"])
def test_A15_unqualified_provider_and_direct_entry_denied(model, endpoint):
    cap = model[0]
    with pytest.raises(Denied):
        Capsule(cap.root, cap.signer, endpoint, cap.owner_public_key)
    with pytest.raises(Denied):
        cap.provider._start(object(), {"id": "bypass"})
    assert cap.provider.starts == 0


@pytest.mark.parametrize("field", ["allow_cloud", "external_execution", "prompt_sha256"])
def test_A16_cloud_or_input_expansion_denied(model, field):
    env = copy.deepcopy(model[3])
    env["parameters"][field] = True
    with pytest.raises(Denied):
        model[0].execute(env, model[2]["prompt"])
    assert model[0].provider.starts == 0


def test_A17_partition_after_consumption_denies_start(model):
    cap = model[0]
    cap.fault = lambda point: setattr(cap.root.anchor, "available", False) if point == "after_consume" else None
    with pytest.raises(Denied):
        execute(model)
    cap.root.anchor.available = True
    assert right(model)["state"] == "CONSUMED"
    assert cap.status()["slot"] is not None
    assert cap.provider.starts == 0


def test_A18_epoch_rotation_exact_predecessor_and_no_overlap(model):
    cap, owner = model[:2]
    cap.transition(command(cap, "freeze"))
    request = command(cap, "activate", session="new-independent-session")
    owner_record = sign(owner, "JARVIS/owner-recovery/v1", request["body"])
    cap.transition(request, owner_record)
    state = cap.root.read()
    assert state["epoch"] == 2 and state["closed_epochs"] == [1]
    assert state["mode"] == "FROZEN"
    with pytest.raises(Denied):
        execute(model)
    with pytest.raises(Denied):
        cap.transition(request, owner_record)


def test_A19_missing_hardware_not_promoted(model):
    assert model[0].production_valid is False
    with pytest.raises(Denied):
        Journal(model[0].root.path, Anchor())
    with pytest.raises(Denied):
        pickle.dumps(model[0].root.anchor)


def test_A20_new_authority_cannot_escape_uncertainty(model, rig):
    cap = model[0]
    cap.provider.ambiguous = True
    with pytest.raises(Denied):
        execute(model)
    rig[3].finish(model[2]["id"], result="untrusted queue bookkeeping")
    job2, env2 = queued(rig, "a21")
    authorize_development(cap, env2)
    with pytest.raises(Denied):
        cap.execute(env2, job2["prompt"])
    with pytest.raises(Denied):
        cap.recover()
    assert cap.provider.starts == cap.provider.active == 1


def test_A21_compromised_decision_ledger(model):
    cap = model[0]
    with cap.signer.spine.store.connect() as db:
        db.execute("UPDATE audit_trail SET envelope_json='{}'")
    with pytest.raises(Denied):
        execute(model)
    assert cap.provider.starts == 0


def test_A22_checkpoint_ci_gate_is_mandatory():
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert "scripts.probe_checkpoint_replay" in workflow
    assert "continue-on-error" not in workflow
    assert "test_development_witness.py" in workflow


def test_A23_evidence_remains_stale_and_production_pending():
    manifest = json.loads(Path("governance/operational-manifest.json").read_text(encoding="utf-8-sig"))
    assert "STALE" in json.dumps(manifest)
    assert Capsule.production_valid is False


def test_A24_malicious_witness_receipt_cannot_resurrect(model):
    execute(model)
    fake_key = Ed25519PrivateKey.generate()
    approval = sign(fake_key, model[4]["domain"], model[4]["body"])
    with pytest.raises(Denied):
        model[0].register(approval)
    assert right(model)["state"] == "CONSUMED"
    assert model[0].provider.starts == 1


def test_A25_total_root_compromise_is_not_a_production_claim(model):
    # Boundary test, not an impossible proof of resistance to all-root compromise.
    assert model[0].evidence_class == "DEVELOPMENT_ONLY"
    assert model[0].production_valid is False
    with pytest.raises(Denied):
        WitnessFrontend(model[0]).request("compromise_root_and_grant")


def test_A26_policy_substitution_and_frontend_signing_denied(model):
    cap = model[0]
    request = command(cap, "freeze")
    request["body"]["operation"] = "policy"
    request["body"]["policy"] = "attacker-policy"
    with pytest.raises(Denied):
        cap.transition(request)
    assert cap.status()["mode"] == "OPEN"


def test_A27_restored_policy_and_modified_old_signature_denied(model, monkeypatch):
    cap = model[0]
    envelope = copy.deepcopy(model[3])
    envelope["authorization"]["expires_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(Denied):
        cap.signer.approval(cap.root.read(), envelope)
    monkeypatch.setitem(PLATFORM_POLICY, "agent.infer", "PROHIBITED")
    with pytest.raises(Denied):
        execute(model)
    assert cap.provider.starts == 0


def test_A28_backend_continues_after_lost_response(model):
    cap = model[0]
    cap.provider.ambiguous = True
    with pytest.raises(Denied):
        execute(model)
    assert cap.provider.active == 1 and cap.status()["slot"] is not None
    with pytest.raises(Denied):
        cap.recover()


def test_A29_restart_preserves_consumption(model):
    execute(model)
    cap = model[0]
    cap.root = Journal(cap.root.path, cap.root.anchor)
    with pytest.raises(Denied):
        execute(model)
    assert right(model)["state"] == "CONSUMED"


def test_A30_maintenance_cannot_infer(model):
    cap = model[0]
    cap.transition(command(cap, "freeze"))
    with pytest.raises(Denied):
        execute(model)
    with pytest.raises(Denied):
        WitnessFrontend(cap).request("maintenance_infer")


def test_A31_production_switch_does_not_exist(model, monkeypatch):
    monkeypatch.setenv("PRIME_WITNESS_PRODUCTION_VALID", "1")
    assert model[0].production_valid is False
    with pytest.raises(Denied):
        FakeProvider(observer=lambda: "real network adapter")


@pytest.mark.parametrize("target", ["authorized", "queued", "claimed", "started", "completed", "verified", "failed", "uncertain"])
def test_A32_illegal_audit_edges_never_restore_rights(model, target):
    execute(model)
    with pytest.raises(Denied):
        model[0].audit(model[3]["authorization"]["lease_id"], target)
    assert right(model)["state"] == "CONSUMED"


def test_A33_denied_registration_is_not_available_again(model):
    cap = model[0]
    cap.deny(model[3]["authorization"]["lease_id"])
    assert cap.register(model[4])["state"] == "DENIED"
    with pytest.raises(Denied):
        execute(model)


def test_A34_claim_failure_denies_but_consumed_is_irreversible(model):
    execute(model)
    with pytest.raises(Denied):
        model[0].deny(model[3]["authorization"]["lease_id"])
    assert right(model)["state"] == "CONSUMED"


def test_A35_consumption_and_slot_share_committed_record(model):
    cap = model[0]
    cap.fault = fail_at("after_consume")
    with pytest.raises(RuntimeError):
        execute(model)
    state = cap.root.read()
    assert state["slot"] == model[3]["authorization"]["lease_id"]
    assert state["rights"][state["slot"]]["state"] == "CONSUMED"
    assert not any(event[1] == "started" for event in state["events"])


def test_A36_expire_after_consume_before_actual_primitive(model):
    cap = model[0]
    cap.fault = lambda point: setattr(cap, "clock", lambda: (2**62, 2**62)) if point == "after_consume" else None
    with pytest.raises(Denied):
        execute(model)
    assert cap.provider.starts == 0 and right(model)["state"] == "CONSUMED"
    cap.recover()
    assert cap.status()["slot"] is None and right(model)["audit"] == "failed"


def test_A37_wrong_process_lifecycle_denies(model):
    model[0].pid = -1
    with pytest.raises(Denied):
        execute(model)
    assert model[0].provider.starts == 0


def test_A38_forged_terminal_cannot_release(model):
    cap = model[0]
    cap.provider.ambiguous = True
    with pytest.raises(Denied):
        execute(model)
    fake = sign(Ed25519PrivateKey.generate(), "JARVIS/terminal/v1", {"id": model[4]["body"]["id"], "quiescent": True})
    with pytest.raises(Denied):
        cap.complete(fake)
    assert cap.status()["slot"] is not None


def test_A39_duplicate_completion_separate_verification(model):
    cap = model[0]
    execute(model)
    terminal = right(model)["terminal"]
    assert cap.complete(terminal) == terminal["body"]["result"]
    key = model[4]["body"]["id"]
    with pytest.raises(Denied):
        cap.verify_result(key, "wrong", "fixture")
    assert right(model)["audit"] == "completed"
    cap.verify_result(key, terminal["body"]["result_digest"], "fixture-verifier")
    assert right(model)["audit"] == "verified" and cap.provider.starts == 1


def test_A40_unknown_outcome_owner_cannot_release(model):
    cap = model[0]
    cap.provider.ambiguous = True
    with pytest.raises(Denied):
        execute(model)
    cap.transition(command(cap, "freeze"))
    request = command(cap, "activate", session="replacement")
    with pytest.raises(Denied):
        cap.transition(request, sign(model[1], "JARVIS/owner-recovery/v1", request["body"]))
    assert cap.root.read()["epoch"] == 1


def test_A41_policy_transition_monotonic_and_stale_command_denied(model):
    cap = model[0]
    request = command(cap, "policy")
    cap.transition(request)
    assert cap.status()["generation"] == 2
    with pytest.raises(Denied):
        cap.transition(request)
    with pytest.raises(Denied):
        execute(model)


def test_A42_missing_recovery_signature_denies(model):
    cap = model[0]
    cap.transition(command(cap, "freeze"))
    with pytest.raises((Denied, TypeError)):
        cap.transition(command(cap, "activate", session="replacement"), {})
    assert cap.root.read()["epoch"] == 1


def test_A43_auto_enrollment_and_clone_path_denied(model, tmp_path):
    cap = model[0]
    path = tmp_path / "cloned-root.db"
    shutil.copyfile(cap.root.path, path)
    with pytest.raises(Denied):
        Journal(path, cap.root.anchor)
    with pytest.raises(Denied):
        Journal(cap.root.path, cap.root.anchor, bootstrap={})


def test_A44_old_code_cannot_use_development_provider(model):
    with pytest.raises(Denied):
        model[0].provider._start(None, {"id": "old-binary"})
    assert model[0].provider.starts == 0


def test_A45_transition_sequence_retains_consumed_history(model):
    cap = model[0]
    execute(model)
    key = model[4]["body"]["id"]
    for operation in ("policy", "freeze"):
        cap.transition(command(cap, operation))
        assert cap.root.read()["rights"][key]["state"] == "CONSUMED"
    for action in (lambda: cap.deny(key), lambda: cap.audit(key, "queued"), lambda: execute(model)):
        with pytest.raises(Denied):
            action()
    assert cap.provider.starts == 1


@pytest.mark.parametrize("value", [float("nan"), 1.5, {1: "bad key"}, {"nested": object()}])
def test_noncanonical_signed_payload_denied(value):
    with pytest.raises(Denied):
        canonical(value)


def test_existing_harness_uses_capsule_not_callback(model, rig):
    from unittest.mock import Mock
    forbidden = Mock(side_effect=AssertionError("production callback reached"))
    run(rig, model[2], forbidden, development_boundary=model[0])
    forbidden.assert_not_called()
    assert model[0].provider.starts == 1


class ConsumedStop(BaseException):
    pass


def prepare_transition(family, model, rig):
    """Return the real transition command and its target journal commit index."""
    cap, owner = model[:2]
    key = model[4]["body"]["id"]
    if family == "T01":
        rig[3].finish(model[2]["id"], result="fixture scheduling only")
        _, envelope = queued(rig)
        approval = cap.signer.approval(cap.root.read(), envelope)
        return lambda: cap.register(approval), 1
    if family == "T02":
        return lambda: cap.deny(key), 1
    if family in {"T03", "T04"}:
        cap.fault = lambda point: (_ for _ in ()).throw(ConsumedStop()) if point == (
            "after_consume" if family == "T03" else "after_start") else None
        def consume_or_start():
            try:
                execute(model)
            except ConsumedStop:
                pass
        return consume_or_start, 1 if family == "T03" else 2
    if family == "T05":
        cap.provider.ambiguous = True
        def uncertain():
            try:
                execute(model)
            except Denied:
                pass
        return uncertain, 3
    if family in {"T06", "T09"}:
        cap.fault = fail_at("before_terminal")
        with pytest.raises(RuntimeError):
            execute(model)
        cap.fault = lambda _: None
        if family == "T06":
            return lambda: cap.complete(cap.provider.receipts[key]), 1
        return cap.recover, 2
    if family == "T07":
        cap.fault = fail_at("after_consume")
        with pytest.raises(RuntimeError):
            execute(model)
        cap.fault = lambda _: None
        return cap.recover, 2
    if family == "T08":
        execute(model)
        return lambda: cap.verify_result(key, right(model)["terminal"]["body"]["result_digest"], "test-verifier"), 1
    if family in {"T10", "T11"}:
        request = command(cap, "policy" if family == "T10" else "freeze")
        return lambda: cap.transition(request), 1
    if family == "T12":
        cap.transition(command(cap, "freeze"))
        request = command(cap, "activate", session="transition-successor")
        recovery = sign(owner, "JARVIS/owner-recovery/v1", request["body"])
        return lambda: cap.transition(request, recovery), 1
    if family == "T13":
        cap.transition(command(cap, "freeze"))
        request = command(cap, "open")
        return lambda: cap.transition(request), 1
    raise AssertionError(family)


@pytest.mark.parametrize("family", [f"T{i:02}" for i in range(1, 14)])
@pytest.mark.parametrize("fault", [None, "before_prepare", "after_prepare", "after_head", "root_loss", "duplicate"])
def test_transition_family_fault_cross_product(model, rig, family, fault):
    cap = model[0]
    action, target_commit = prepare_transition(family, model, rig)
    before = cap.root.read()
    counter = 0
    fired = False
    def inject(point):
        nonlocal counter, fired
        if point == "before_prepare":
            counter += 1
        if point == fault and counter == target_commit and not fired:
            fired = True
            raise RuntimeError("transition fault")
    if fault == "root_loss":
        cap.root.anchor.available = False
        try:
            action()
        except Denied:
            pass
        cap.root.anchor.available = True
        assert cap.root.read() == before
    elif fault in {"before_prepare", "after_prepare", "after_head"}:
        cap.root.fault = inject
        with pytest.raises(RuntimeError):
            action()
        assert fired
        cap.root.fault = lambda _: None
    else:
        action()
        if fault == "duplicate":
            try:
                action()
            except Denied:
                pass
    after = cap.root.read()
    for key, record in before["rights"].items():
        if record["state"] in {"CONSUMED", "DENIED"}:
            assert after["rights"][key]["state"] == record["state"]
    if after["slot"] is not None:
        assert after["rights"][after["slot"]]["state"] == "CONSUMED"
    assert cap.provider.max_active <= 1
    assert len(after["closed_epochs"]) == after["epoch"] - 1


@pytest.mark.parametrize("restore", ["intact", "missing_head", "corrupt_body", "cloned_path", "lost_anchor"])
def test_T14_recovery_never_reconstructs_start(model, tmp_path, restore):
    cap = model[0]
    execute(model)
    if restore == "missing_head":
        with sqlite3.connect(cap.root.path) as db:
            db.execute("DELETE FROM records WHERE seq=?", (cap.root.anchor.sequence,))
    elif restore == "corrupt_body":
        with sqlite3.connect(cap.root.path) as db:
            db.execute("UPDATE records SET body='{}'")
    path, anchor = cap.root.path, cap.root.anchor
    if restore == "cloned_path":
        path = tmp_path / "other.db"
        shutil.copyfile(cap.root.path, path)
    if restore == "lost_anchor":
        anchor = Anchor()
    if restore == "intact":
        cap.root = Journal(path, anchor)
        cap.recover()
    else:
        with pytest.raises(Denied):
            Journal(path, anchor)
    assert cap.provider.starts == 1


@pytest.mark.parametrize("attack", ["resurrect", "erase", "rebind", "release", "generation", "substitute_key"])
def test_validator_rejects_fabricated_increasing_state(model, attack):
    cap = model[0]
    cap.fault = fail_at("after_consume")
    with pytest.raises(RuntimeError):
        execute(model)
    state = cap.root.read()
    key = state["slot"]
    if attack == "resurrect":
        state["rights"][key]["state"] = "AVAILABLE"
    elif attack == "erase":
        del state["rights"][key]
    elif attack == "rebind":
        state["rights"][key]["operation"]["attempt"] = 2
    elif attack == "release":
        state["slot"] = None
    elif attack == "generation":
        state["generation"] += 100
    else:
        state["spine_key"] = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    with pytest.raises(Denied):
        cap.root._commit(state)
    assert right(model)["state"] == "CONSUMED" and cap.root.read()["slot"] == key


def test_key_rotation_requires_both_signatures_and_fresh_capsule(model, rig):
    from app.development_witness import SpineSigner
    cap, owner = model[:2]
    cap.transition(command(cap, "freeze"))
    new_signer = SpineSigner(rig[2], rig[1])
    new_provider = FakeProvider()
    request = command(cap, "activate", session="new-boot", spine_key=new_signer.public_key.public_bytes_raw().hex(),
                      provider_key=new_provider.public_key.public_bytes_raw().hex())
    cap.transition(request, sign(owner, "JARVIS/owner-recovery/v1", request["body"]))
    with pytest.raises(Denied):
        execute(model)
    successor = Capsule(cap.root, new_signer, new_provider, owner.public_key())
    successor.transition(command(successor, "open"))
    with pytest.raises(Denied):
        successor.register(model[4])
    rig[3].finish(model[2]["id"], result="old epoch scheduling closed")
    job, env = queued(rig)
    authorize_development(successor, env)
    successor.execute(env, job["prompt"])
    assert successor.provider.starts == 1 and cap.provider.starts == 0
