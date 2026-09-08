"""DEVELOPMENT ONLY: surviving-root model and synthetic Harness capsule.

No production provider adapter or environment switch exists. Python object
privacy is NOT an OS security boundary. The Anchor models the independently
surviving trusted root; copying/compromising that root is not covered evidence.
StableSpine remains the only policy evaluator. The witness frontend has neither
the Spine private key nor a trusted permit/recovery/state-replacement API.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .spine import PLATFORM_POLICY, classify_action


class Denied(PermissionError):
    pass


def canonical(value):
    """Unambiguous signed JSON subset: no floats, duplicate keys or coercion."""
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child)
            return
        raise Denied("noncanonical value")
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sign(key, domain, body):
    return {"domain": domain, "body": copy.deepcopy(body),
            "signature": key.sign(canonical([domain, body])).hex()}


def verify(key, domain, record):
    try:
        if set(record) != {"domain", "body", "signature"} or record["domain"] != domain:
            raise Denied("signature domain/schema mismatch")
        key.verify(bytes.fromhex(record["signature"]), canonical([domain, record["body"]]))
        return copy.deepcopy(record["body"])
    except (InvalidSignature, ValueError, TypeError, KeyError) as exc:
        raise Denied("invalid signed record") from exc


class Anchor:
    """Explicit in-process *surviving root assumption*, never a production anchor.

    Keep this object in the test supervisor, outside restored worker ledgers.
    Restart the journal with this SAME object. Loss never auto-enrolls a root.
    """
    def __init__(self):
        self.lock = threading.RLock()
        self.path = None
        self.sequence = -1
        self.head = None
        self.available = True
        self.pid = os.getpid()
        self.incarnation = str(uuid.uuid4())

    def __reduce_ex__(self, protocol):
        raise Denied("anchor cloning is outside the surviving-root model")


class Journal:
    def __init__(self, path, anchor, *, bootstrap=None):
        self.path = str(Path(path).resolve())
        self.anchor = anchor
        self.fault = lambda point: None
        with anchor.lock:
            if bootstrap is not None:
                if anchor.path is not None or Path(path).exists():
                    raise Denied("root already enrolled")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                with self._db() as db:
                    db.execute("CREATE TABLE records(seq INTEGER PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL)")
                anchor.path = self.path
                self._commit(bootstrap)
            else:
                self.read()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=0)
        try:
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _guard(self):
        a = self.anchor
        if not a.available or a.pid != os.getpid() or a.path != self.path:
            raise Denied("root unavailable, cloned or not enrolled")

    def read(self):
        with self.anchor.lock:
            self._guard()
            try:
                with self._db() as db:
                    row = db.execute("SELECT body,hash FROM records WHERE seq=?", (self.anchor.sequence,)).fetchone()
                if not row or row[1] != self.anchor.head or digest(json.loads(row[0])) != row[1]:
                    raise Denied("root rollback or corrupted committed record")
                return json.loads(row[0])
            except (sqlite3.Error, ValueError) as exc:
                raise Denied("root journal unavailable") from exc

    def _commit(self, state):
        """Private trusted transition sink, never exposed to the frontend."""
        self._guard()
        if self.anchor.sequence >= 0:
            self._validate_transition(self.read(), state)
        seq = self.anchor.sequence + 1
        state = copy.deepcopy(state)
        state["sequence"] = seq
        state["previous"] = self.anchor.head
        state["incarnation"] = self.anchor.incarnation
        self.fault("before_prepare")
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?)",
                       (seq, canonical(state).decode(), digest(state)))
        self.fault("after_prepare")
        # Models the atomic, non-restored head CAS. Only this validator calls it.
        self.anchor.sequence, self.anchor.head = seq, digest(state)
        self.fault("after_head")

    @staticmethod
    def _validate_transition(old, new):
        """Defense in depth: even a fabricated increasing head cannot revive rights."""
        for key, before in old["rights"].items():
            after = new["rights"].get(key)
            if (not after or before["approval"] != after["approval"]
                    or (before["state"] in {"CONSUMED", "DENIED"} and after["state"] != before["state"])):
                raise Denied("root rejects authority resurrection or substitution")
            if any(k in before and after.get(k) != before[k] for k in ("operation", "terminal")):
                raise Denied("execution binding/terminal evidence is immutable")
        for key, after in new["rights"].items():
            if after["state"] not in {"AVAILABLE", "CONSUMED", "DENIED"}:
                raise Denied("unknown rights state")
            if key not in old["rights"]:
                approved = verify(Ed25519PublicKey.from_public_bytes(bytes.fromhex(old["spine_key"])),
                                  "JARVIS/Spine/development-approval/v1", after["approval"])
                if (after["state"] != "AVAILABLE" or approved["id"] != key
                        or any(approved[k] != old[k] for k in ("estate", "epoch", "session", "generation", "policy"))):
                    raise Denied("root rejects fabricated registration")
        consumed = [key for key in old["rights"] if old["rights"][key]["state"] == "AVAILABLE"
                    and new["rights"][key]["state"] == "CONSUMED"]
        if consumed and (len(consumed) != 1 or old["slot"] is not None or new["slot"] != consumed[0]):
            raise Denied("consumption and slot must commit together")
        if old["slot"] is None and new["slot"] is not None and consumed != [new["slot"]]:
            raise Denied("slot acquisition lacks fresh consumption")
        if old["slot"] is not None and new["slot"] != old["slot"]:
            if new["slot"] is not None:
                raise Denied("slot owner cannot transfer")
            right = new["rights"][old["slot"]]
            terminal = verify(Ed25519PublicKey.from_public_bytes(bytes.fromhex(old["provider_key"])),
                              "JARVIS/terminal/v1", right.get("terminal"))
            if (terminal.get("quiescent") is not True
                    or any(terminal.get(k) != v for k, v in old["rights"][old["slot"]]["operation"].items())):
                raise Denied("root rejects unproven slot release")
        header = ("epoch", "generation", "policy", "mode", "session", "spine_key", "provider_key", "revoked")
        if any(new[k] != old[k] for k in header):
            control = new.get("control", {})
            request = verify(Ed25519PublicKey.from_public_bytes(bytes.fromhex(old["spine_key"])),
                             "JARVIS/Spine/transition/v1", control.get("request"))
            if request.get("previous") != digest(old):
                raise Denied("root requires current Spine transition")
            operation = request["operation"]
            changes = {key for key in header if new[key] != old[key]}
            permitted = {"policy": {"policy", "generation"}, "freeze": {"mode"}, "open": {"mode"},
                         "revoke": {"revoked"}, "activate": {"epoch", "session", "spine_key", "provider_key"}}
            if operation not in permitted or not changes <= permitted[operation]:
                raise Denied("root rejects broadened transition")
            if operation == "policy" and (new["generation"] != old["generation"] + 1 or new["policy"] != request["policy"]):
                raise Denied("root rejects substituted policy generation")
            if operation in {"freeze", "open"} and new["mode"] != {"freeze": "FROZEN", "open": "OPEN"}[operation]:
                raise Denied("root rejects mode substitution")
            if operation == "open" and (old["mode"] != "FROZEN" or old["slot"] is not None):
                raise Denied("root rejects unsafe reopening")
            if operation == "revoke" and set(new["revoked"]) != set(old["revoked"]) | {request["id"]}:
                raise Denied("root rejects revocation substitution")
            if operation == "activate":
                approval = verify(Ed25519PublicKey.from_public_bytes(bytes.fromhex(old["owner_key"])),
                                  "JARVIS/owner-recovery/v1", control.get("owner"))
                if (approval != request or old["slot"] is not None or old["mode"] != "FROZEN"
                        or new["epoch"] != old["epoch"] + 1 or new["session"] in old["closed_sessions"] + [old["session"]]
                        or any(new[k] != request[k] for k in ("session", "spine_key", "provider_key"))
                        or new["closed_epochs"] != old["closed_epochs"] + [old["epoch"]]
                        or new["closed_sessions"] != old["closed_sessions"] + [old["session"]]):
                    raise Denied("root rejects unsafe activation")
        if (new["estate"] != old["estate"] or new["owner_key"] != old["owner_key"]
                or not set(old["revoked"]) <= set(new["revoked"])
                or not set(old["closed_epochs"]) <= set(new["closed_epochs"])
                or not set(old["closed_sessions"]) <= set(new["closed_sessions"])):
            raise Denied("root identity/tombstones cannot roll back")


def policy_snapshot(spine):
    with spine.store.connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM trust_registry ORDER BY action_type")]
    return {"platform": dict(PLATFORM_POLICY), "trust": rows}


class SpineSigner:
    """Protected DEVELOPMENT signing facade for the actual StableSpine PDP."""
    def __init__(self, spine, enrollment_harness):
        self.spine = spine
        self.__enrollment_harness = enrollment_harness
        self.__key = Ed25519PrivateKey.generate()
        self.public_key = self.__key.public_key()
        self.pid = os.getpid()

    def __reduce_ex__(self, protocol):
        raise Denied("Spine signing boundary cannot be copied")

    def _current(self, state):
        if (self.pid != os.getpid() or self.public_key.public_bytes_raw().hex() != state["spine_key"]
                or digest(policy_snapshot(self.spine)) != state["policy"]):
            raise Denied("restored signer/policy is not current")

    def validate_decision(self, envelope):
        proposal = {k: v for k, v in envelope.items() if k != "authorization"}
        proposal["schema_version"] = "1.0.0"
        with self.spine.store.connect() as db:
            row = db.execute("SELECT * FROM audit_trail WHERE idempotency_key=?",
                             (envelope["idempotency_key"],)).fetchone()
            trust = db.execute("SELECT * FROM trust_registry WHERE action_type=?", (envelope["action"],)).fetchone()
        if (not row or row["execution_status"] != "AUTHORIZED"
                or json.loads(row["envelope_json"]) != proposal
                or json.loads(row["decision_record_json"])["decision_id"] != envelope["authorization"]["decision_id"]
                or classify_action(proposal, dict(trust) if trust else None)["state"] not in {"AUTO", "BOUNDED_AUTO"}):
            raise Denied("current Stable Spine decision rejected")

    def approval(self, state, envelope):
        self._current(state)
        error, _ = self.__enrollment_harness._validate(envelope, datetime.now(timezone.utc))
        if error:
            raise Denied("legacy envelope cannot be promoted: " + error)
        self.validate_decision(envelope)
        body = {"estate": state["estate"], "epoch": state["epoch"], "session": state["session"],
                "generation": state["generation"], "policy": state["policy"],
                "envelope": envelope, "id": envelope["authorization"]["lease_id"]}
        return sign(self.__key, "JARVIS/Spine/development-approval/v1", body)

    def transition(self, state, operation, **fields):
        if self.pid != os.getpid():
            raise Denied("signer session cloned")
        # Only this PDP can publish its actual policy, never a witness argument.
        body = {"estate": state["estate"], "previous": digest(state), "epoch": state["epoch"],
                "operation": operation, **fields}
        if operation == "policy":
            body["policy"] = digest(policy_snapshot(self.spine))
        else:
            self._current(state)
        return sign(self.__key, "JARVIS/Spine/transition/v1", body)


class FakeProvider:
    """Finite synthetic provider. No URL, socket, SDK or arbitrary callable."""
    def __init__(self, result=None, *, observer=None):
        if observer is not None and not isinstance(observer, Mock):
            raise Denied("only a mock observer is supported")
        self.result = result if result is not None else {"result": "synthetic", "provider": "local"}
        self.observer = observer
        self.starts = 0
        self.active = 0
        self.max_active = 0
        self.seen = set()
        self.receipts = {}
        self.wait = None  # optional test Event, never an inference callback
        self.ambiguous = False
        self.__capability = None
        self.__key = Ed25519PrivateKey.generate()
        self.public_key = self.__key.public_key()

    def _bind(self, capability):
        if self.__capability is not None:
            raise Denied("provider already belongs to a capsule")
        self.__capability = capability

    def _start(self, capability, operation):
        if capability is not self.__capability or capability is None or operation["id"] in self.seen:
            raise Denied("direct or duplicate provider invocation")
        self.seen.add(operation["id"])
        self.starts += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.observer is not None:
            self.observer()

    def _finish(self, capability, operation):
        if capability is not self.__capability or operation["id"] not in self.seen:
            raise Denied("unknown provider operation")
        if self.wait is not None:
            self.wait.wait(timeout=5)
        if self.ambiguous:
            raise Denied("synthetic provider outcome uncertain")
        self.active -= 1
        receipt = sign(self.__key, "JARVIS/terminal/v1", {**operation, "quiescent": True,
                       "outcome": "completed", "result": self.result, "result_digest": digest(self.result)})
        self.receipts[operation["id"]] = receipt
        return receipt

    def _reconcile(self, capability, operation):
        if capability is not self.__capability:
            raise Denied("untrusted recovery caller")
        if operation["id"] in self.receipts:
            return self.receipts[operation["id"]]
        if operation["id"] in self.seen or self.active:
            raise Denied("backend may still execute")
        # In this finite fake provider, absence in the surviving supervisor's
        # start set proves no-start. Never infer this from an application DB.
        return sign(self.__key, "JARVIS/terminal/v1", {**operation, "quiescent": True,
                    "outcome": "failed", "result": None, "result_digest": digest(None)})


class Capsule:
    evidence_class = "DEVELOPMENT_ONLY"
    production_valid = False

    def __init__(self, journal, signer, provider, owner_public_key):
        if type(provider) is not FakeProvider:
            raise Denied("production/custom providers unsupported")
        enrolled = journal.read()
        if (enrolled["spine_key"] != signer.public_key.public_bytes_raw().hex()
                or enrolled["provider_key"] != provider.public_key.public_bytes_raw().hex()
                or enrolled["owner_key"] != owner_public_key.public_bytes_raw().hex()):
            raise Denied("capsule identities are not enrolled")
        self.root, self.signer, self.provider = journal, signer, provider
        self.owner_public_key = owner_public_key
        self.pid = os.getpid()
        self.__capability = object()
        self.provider._bind(self.__capability)
        self.clock = lambda: (int(time.time() * 1000), int(time.time() * 1000) + 1)
        self.fault = lambda point: None
        self.session = journal.read()["session"]

    def __reduce_ex__(self, protocol):
        raise Denied("capsule memory cloning unsupported; production lifecycle HOLD")

    def _state(self):
        state = self.root.read()
        if (self.pid != os.getpid() or state["session"] != self.session
                or state["spine_key"] != self.signer.public_key.public_bytes_raw().hex()
                or state["provider_key"] != self.provider.public_key.public_bytes_raw().hex()):
            raise Denied("old or cloned capsule session")
        return state

    def status(self):
        state = self._state()
        return {k: copy.deepcopy(state[k]) for k in ("epoch", "generation", "mode", "slot", "rights", "events")}

    def _verify(self, state, approval, prompt, *, consumed=False):
        body = verify(self.signer.public_key, "JARVIS/Spine/development-approval/v1", approval)
        if set(body) != {"estate", "epoch", "session", "generation", "policy", "envelope", "id"}:
            raise Denied("unknown approval field")
        if any(body[k] != state[k] for k in ("estate", "epoch", "session", "generation", "policy")):
            raise Denied("stale authority")
        self.signer._current(state)
        envelope = body["envelope"]
        self.signer.validate_decision(envelope)
        params = envelope["parameters"]
        if (envelope["action"] != "agent.infer" or envelope["actor_id"] not in {"a14", "a16", "a21"}
                or params.get("allow_cloud") is not False or params.get("external_execution") is not False
                or params.get("prompt_sha256") != hashlib.sha256(prompt.encode()).hexdigest()
                or envelope["context"].get("policy_limits") != {"cloud": False, "local_concurrency": 1}):
            raise Denied("outside frozen local inference scope")
        low, high = self.clock()
        auth = envelope["authorization"]
        deadlines = [int(datetime.fromisoformat(auth[k]).timestamp() * 1000) for k in ("expires_at", "lease_expires_at")]
        issued = int(datetime.fromisoformat(auth["issued_at"]).timestamp() * 1000)
        if type(low) is not int or type(high) is not int or low > high or low < issued or high >= min(deadlines):
            raise Denied("expired or uncertain time")
        if body["id"] in state["revoked"] or state["mode"] != "OPEN":
            raise Denied("revoked or frozen")
        right = state["rights"].get(body["id"])
        expected = "CONSUMED" if consumed else "AVAILABLE"
        if not right or right["state"] != expected or right["approval"] != approval:
            raise Denied("consumed, denied or unregistered authorization")
        if consumed and state["slot"] != body["id"]:
            raise Denied("consumption does not own slot")
        return body

    def register(self, approval):
        with self.root.anchor.lock:
            state = self._state()
            body = verify(self.signer.public_key, "JARVIS/Spine/development-approval/v1", approval)
            if any(body[k] != state[k] for k in ("estate", "epoch", "session", "generation", "policy")):
                raise Denied("stale registration")
            key = body["id"]
            existing = state["rights"].get(key)
            if existing:
                if existing["approval"] != approval:
                    raise Denied("authorization binding collision")
                return copy.deepcopy(existing)  # status only, never AVAILABLE reset
            state["rights"][key] = {"state": "AVAILABLE", "audit": "authorized", "approval": approval}
            if any(body[k] != state[k] for k in ("estate", "epoch", "session", "generation", "policy")):
                raise Denied("stale registration")
            self.signer._current(state)
            self.signer.validate_decision(body["envelope"])
            state["events"].append([key, "authorized"])
            self.root._commit(state)

    def audit(self, key, target):
        with self.root.anchor.lock:
            state = self._state()
            right = state["rights"][key]
            allowed = {"authorized": "queued", "queued": "claimed"}
            if right["state"] != "AVAILABLE" or allowed.get(right["audit"]) != target:
                raise Denied("illegal scheduling transition")
            right["audit"] = target
            state["events"].append([key, target])
            self.root._commit(state)

    def deny(self, key):
        with self.root.anchor.lock:
            state = self._state()
            right = state["rights"][key]
            if right["state"] != "AVAILABLE":
                raise Denied("consumption is irreversible")
            right.update(state="DENIED", audit="failed")
            self.root._commit(state)

    def execute(self, envelope, prompt):
        key = envelope["authorization"]["lease_id"]
        with self.root.anchor.lock:
            state = self._state()
            right = state["rights"].get(key)
            if not right or right["approval"]["body"]["envelope"] != envelope:
                raise Denied("unregistered or rebound complete envelope")
            approval = right["approval"]
            self._verify(state, approval, prompt)
            if state["slot"] is not None or right["audit"] != "claimed":
                raise Denied("global slot occupied or not claimed")
            right["state"] = "CONSUMED"
            operation = {"id": key, "epoch": state["epoch"], "session": state["session"],
                         "approval": digest(approval), "attempt": 1}
            right["operation"] = operation
            state["slot"] = key
            state["events"].append([key, "consumed"])
            self.root._commit(state)
            # Crash here burns authority even if no provider start happened.
            self.fault("after_consume")
            try:
                state = self._state()
                self._verify(state, approval, prompt, consumed=True)
                self.provider._start(self.__capability, operation)
                state["rights"][key]["audit"] = "started"
                state["rights"][key]["operation"] = operation
                state["events"].append([key, "started"])
                self.root._commit(state)
            except BaseException:
                self._uncertain(key)
                raise
        try:
            self.fault("after_start")
            receipt = self.provider._finish(self.__capability, operation)
            self.fault("before_terminal")
            return self.complete(receipt)
        except BaseException:
            self._uncertain(key)
            raise

    def _uncertain(self, key):
        with self.root.anchor.lock:
            state = self._state()
            if state["slot"] == key:
                state["rights"][key]["audit"] = "uncertain"
                self.root._commit(state)

    def complete(self, receipt):
        with self.root.anchor.lock:
            state = self._state()
            body = verify(self.provider.public_key, "JARVIS/terminal/v1", receipt)
            key = body["id"]
            right = state["rights"].get(key)
            if right and right.get("terminal") == receipt:
                return copy.deepcopy(body["result"])
            if (not right or right["state"] != "CONSUMED" or state["slot"] != key
                    or body.get("outcome") not in {"completed", "failed"}
                    or body != {**right.get("operation", {}), "quiescent": True, "outcome": body.get("outcome"),
                                "result": body.get("result"), "result_digest": digest(body.get("result"))}):
                raise Denied("unauthenticated or conflicting termination")
            right.update(audit=body["outcome"], terminal=receipt)
            state["slot"] = None
            state["events"].append([key, body["outcome"]])
            self.root._commit(state)
            return copy.deepcopy(body["result"])

    def recover(self):
        """Evidence reconciliation only. Never reconstruct an invocation."""
        with self.root.anchor.lock:
            state = self._state()
            key = state["slot"]
            if key is None:
                return self.status()
            self._uncertain(key)
            receipt = self.provider._reconcile(self.__capability, state["rights"][key]["operation"])
            self.complete(receipt)
            return self.status()

    def verify_result(self, key, result_digest, evidence_ref):
        with self.root.anchor.lock:
            state = self._state()
            right = state["rights"][key]
            if (right["audit"] != "completed" or not evidence_ref
                    or right["terminal"]["body"]["result_digest"] != result_digest):
                raise Denied("result verification failed")
            right.update(audit="verified", evidence_ref=evidence_ref)
            state["events"].append([key, "verified"])
            self.root._commit(state)

    def transition(self, request, owner=None):
        with self.root.anchor.lock:
            state = self._state()
            body = verify(self.signer.public_key, "JARVIS/Spine/transition/v1", request)
            if body.get("previous") != digest(state) or body.get("estate") != state["estate"] or body.get("epoch") != state["epoch"]:
                raise Denied("stale transition predecessor")
            operation = body["operation"]
            if operation == "freeze" and set(body) == {"estate", "previous", "epoch", "operation"}:
                state["mode"] = "FROZEN"
            elif operation == "policy" and set(body) == {"estate", "previous", "epoch", "operation", "policy"}:
                if body["policy"] != digest(policy_snapshot(self.signer.spine)):
                    raise Denied("policy content substitution")
                state["policy"] = body["policy"]
                state["generation"] += 1
            elif operation == "revoke" and set(body) == {"estate", "previous", "epoch", "operation", "id"}:
                if body["id"] not in state["revoked"]:
                    state["revoked"].append(body["id"])
            elif operation == "activate" and set(body) == {"estate", "previous", "epoch", "operation", "session", "spine_key", "provider_key"}:
                if verify(self.owner_public_key, "JARVIS/owner-recovery/v1", owner) != body:
                    raise Denied("owner cannot substitute activation")
                if state["mode"] != "FROZEN" or state["slot"] is not None or self.provider.active:
                    raise Denied("old execution not fenced")
                if body["session"] in state["closed_sessions"] + [state["session"]]:
                    raise Denied("fresh lifecycle required")
                state["closed_epochs"].append(state["epoch"])
                state["closed_sessions"].append(state["session"])
                state["epoch"] += 1
                state["session"] = body["session"]
                state["spine_key"] = body["spine_key"]
                state["provider_key"] = body["provider_key"]
            elif operation == "open" and set(body) == {"estate", "previous", "epoch", "operation"}:
                if state["mode"] != "FROZEN" or state["slot"] is not None:
                    raise Denied("continuity readmission requires frozen empty capsule")
                self.signer._current(state)
                state["mode"] = "OPEN"
            else:
                raise Denied("unknown authority transition")
            state["control"] = {"request": request, "owner": owner}
            self.root._commit(state)


class WitnessFrontend:
    """Untrusted transport surface: no method issues permits or mutates rights."""
    def __init__(self, capsule):
        self.__capsule = capsule

    def request(self, operation, payload=None):
        if operation != "status":
            raise Denied("witness cannot grant, activate, complete or replace state")
        return self.__capsule.status()


def bootstrap_development(path, spine, enrollment_harness, *, provider=None):
    """Explicit test enrollment. Never called by application startup/config."""
    anchor = Anchor()
    signer = SpineSigner(spine, enrollment_harness)
    owner = Ed25519PrivateKey.generate()
    provider = provider or FakeProvider()
    state = {"estate": "synthetic-estate", "epoch": 1, "generation": 1,
             "session": str(uuid.uuid4()), "policy": digest(policy_snapshot(spine)), "mode": "OPEN",
             "rights": {}, "revoked": [], "closed_epochs": [], "closed_sessions": [], "slot": None, "events": [],
             "spine_key": signer.public_key.public_bytes_raw().hex(),
             "provider_key": provider.public_key.public_bytes_raw().hex(),
             "owner_key": owner.public_key().public_bytes_raw().hex()}
    journal = Journal(path, anchor, bootstrap=state)
    return Capsule(journal, signer, provider, owner.public_key()), owner


def authorize_development(capsule, envelope):
    """Stable Spine signing then H registration; never a witness approval."""
    with capsule.root.anchor.lock:
        approval = capsule.signer.approval(capsule.root.read(), envelope)
        capsule.register(approval)
        key = approval["body"]["id"]
        capsule.audit(key, "queued")
        capsule.audit(key, "claimed")
        return approval
