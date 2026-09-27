import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.engineering_backlog import EngineeringBacklog, KEY
from app.phase2_intelligence import AuthorityEnvelope, Phase2Kernel

PERMISSIONS = frozenset({"objective.create", "objective.read", "objective.update", "objective.control"})


def auth(role="APPLICATION", actor="isolated-engineering"):
    return AuthorityEnvelope(actor, role, PERMISSIONS, 4_000_000_000)


def backlog(tmp_path):
    store = Phase2Kernel(tmp_path / "continuity.db")
    objective = store.create_objective(objective="Preserve real engineering findings", authority=auth(),
        success_criteria=["governed independent production acceptance"], constraints=["no production mutation"])
    return EngineeringBacklog(store, objective["objective_id"], auth())


def observe(book, raw=b"retained failing output", **changes):
    kwargs = dict(code="P1-LENS-RETRIEVAL", source="production-qualification", severity="P1",
                  evidence_ref="receipt.json", evidence_bytes=raw,
                  expected_sha256=hashlib.sha256(raw).hexdigest(), proposed_action="isolated repair",
                  test="real affected production gate after governed promotion")
    kwargs.update(changes)
    return book.observe(**kwargs)


def test_duplicate_observation_does_not_grow_checkpoint_or_hide_critical_work(tmp_path):
    book = backlog(tmp_path)
    first = observe(book)
    again = observe(book)
    assert first["id"] == again["id"] and again["duplicate"]
    assert first["objective_version"] == again["objective_version"]
    value = book.snapshot()
    assert value["backlog_depth"] == value["unresolved_critical_count"] == 1
    assert value["continuous_improvement"] == "NOT_ESTABLISHED"
    assert not value["quiet_steady_state_qualified"] and not value["execution_authority"]


def test_new_evidence_retains_old_failure_and_reopens_without_lowering_severity(tmp_path):
    book = backlog(tmp_path)
    first = observe(book)
    raw = b"candidate test receipt, not production"
    book.disposition(first["id"], status="CANDIDATE_ONLY", receipt_ref="candidate.json",
                     receipt_bytes=raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    new = observe(book, b"new failing output", severity="P3")
    assert new["item"]["status"] == "OPEN"
    assert new["item"]["severity"] == "P1"
    assert len(new["item"]["observations"]) == 2
    assert len(new["item"]["dispositions"]) == 1
    assert new["item"]["result"] == "UNVERIFIED"


@pytest.mark.parametrize("status", ["VERIFIED", "REPAIRED", "PASS", "COMPLETED", "QUIET"])
def test_model_cannot_close_work_by_status_assertion(tmp_path, status):
    book = backlog(tmp_path)
    item = observe(book)
    with pytest.raises(ValueError):
        book.disposition(item["id"], status=status, receipt_ref="model-claim",
                         receipt_bytes=b"PASS", expected_sha256=hashlib.sha256(b"PASS").hexdigest())
    assert book.snapshot()["items"][0]["status"] == "OPEN"


def test_digest_mismatch_does_not_create_backlog_item(tmp_path):
    book = backlog(tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        observe(book, expected_sha256="0" * 64)
    assert book.snapshot()["backlog_depth"] == 0


def test_member_cross_principal_and_expired_authority_denied(tmp_path):
    book = backlog(tmp_path)
    for principal in (auth("MEMBER"), auth(actor="different-app"),
                      AuthorityEnvelope("isolated-engineering", "APPLICATION", PERMISSIONS, 1)):
        other = EngineeringBacklog(book.store, book.objective_id, principal)
        with pytest.raises(PermissionError):
            observe(other)


def test_actual_new_process_recovers_same_backlog_without_callbacks(tmp_path):
    book = backlog(tmp_path)
    item = observe(book)
    code = """import json,sys
from app.engineering_backlog import EngineeringBacklog
from app.phase2_intelligence import AuthorityEnvelope,Phase2Kernel
authority=AuthorityEnvelope('isolated-engineering','APPLICATION',frozenset({'objective.read'}),4000000000)
book=EngineeringBacklog(Phase2Kernel(sys.argv[1]),sys.argv[2],authority)
print(json.dumps(book.snapshot()))
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    raw = subprocess.check_output([sys.executable, "-c", code, book.store.path, book.objective_id],
                                  cwd=Path(__file__).resolve().parents[1], env=env, timeout=20)
    value = json.loads(raw)
    assert value["items"][0]["id"] == item["id"]
    assert value["items"][0]["observations"][0]["evidence_sha256"] == hashlib.sha256(b"retained failing output").hexdigest()
    assert value["backlog_depth"] == 1 and value["objective_state"] == "ACTIVE"


def test_owner_pause_prevents_further_observations(tmp_path):
    book = backlog(tmp_path)
    observe(book)
    book.store.control(book.objective_id, "pause", authority=auth())
    with pytest.raises(ValueError, match="non-active"):
        observe(book, b"new")
    assert len(book.snapshot()["items"][0]["observations"]) == 1


@pytest.mark.parametrize("expiry", [float('nan'), float('inf'), float('-inf'), True, 'future'])
def test_nonfinite_or_untyped_authority_expiry_is_denied(tmp_path, expiry):
    book = backlog(tmp_path)
    altered = EngineeringBacklog(book.store, book.objective_id,
        AuthorityEnvelope('isolated-engineering', 'APPLICATION', PERMISSIONS, expiry))
    with pytest.raises(PermissionError):
        altered.snapshot()


@pytest.mark.parametrize("field,value", [('status','VERIFIED'), ('result','PASS'),
    ('severity','NONE'), ('receipt',{'status':'VERIFIED'}),
    ('dispositions',[{'status':'REPAIRED'}])])
def test_other_checkpoint_writer_cannot_inflate_existing_backlog_state(tmp_path, field, value):
    book = backlog(tmp_path)
    item = observe(book)
    current = book.store.get_objective(book.objective_id, authority=auth())
    graph = current['checkpoint']['problem_graph']
    graph[KEY][item['id']][field] = value
    book.store.checkpoint(book.objective_id, authority=auth(),
        expected_version=current['objective_version'], updates={'problem_graph':graph},
        next_action='OTHER_CHECKPOINT_WRITER')
    with pytest.raises(ValueError, match='invalid existing'):
        book.snapshot()


@pytest.mark.parametrize("field,value", [('verification','SYSTEM_VERIFIED'),
    ('observation_digest','0'*64), ('evidence_sha256','fabricated-digest')])
def test_checkpoint_writer_cannot_inflate_nested_observation_label(tmp_path, field, value):
    book = backlog(tmp_path)
    item = observe(book)
    current = book.store.get_objective(book.objective_id, authority=auth())
    graph = current['checkpoint']['problem_graph']
    graph[KEY][item['id']]['observations'][0][field] = value
    book.store.checkpoint(book.objective_id, authority=auth(),
        expected_version=current['objective_version'], updates={'problem_graph':graph},
        next_action='OTHER_CHECKPOINT_WRITER')
    with pytest.raises(ValueError, match='invalid existing observation'):
        book.snapshot()
