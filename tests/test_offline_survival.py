"""Offline survival acceptance: capability state, classification, store-and-forward, reconciliation."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from app.offline_survival import (
    CapabilityState,
    DependencyClass,
    OfflineSurvival,
    OperationRejected,
    QueueState,
)


def build(tmp_path) -> OfflineSurvival:
    return OfflineSurvival(tmp_path / "offline-queue.db")


def queue_one(survival, *, key="op-1", operation_type="portal.publish", objective="obj-1", now=None):
    return survival.enqueue(
        objective_id=objective,
        operation_type=operation_type,
        payload_ref="artifact://report/1",
        idempotency_key=key,
        authorization_ref="owner:lam",
        payload={"report_id": "r-1"},
        now=now,
    )


class TestCapabilityState:
    def test_deliberate_transitions_through_degraded_and_back(self, tmp_path):
        survival = build(tmp_path)
        assert survival.state is CapabilityState.ONLINE
        assert survival.observe(network=False, provider=False) is CapabilityState.OFFLINE
        assert survival.observe(network=True, provider=False) is CapabilityState.DEGRADED
        assert survival.observe(network=True, provider=True) is CapabilityState.RECONNECTING
        assert survival.confirm_online() is CapabilityState.ONLINE

    def test_confirm_online_is_refused_outside_reconnecting(self, tmp_path):
        survival = build(tmp_path)
        with pytest.raises(RuntimeError):
            survival.confirm_online()

    def test_offline_never_reports_whole_system_failure(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=False, provider=False)
        view = survival.offline_actions(local_model_ready=True, memory_ready=True, local_tools_ready=True)
        assert view["mode"].startswith("OFFLINE")
        assert view["local_model"] == "READY"
        assert view["memory"] == "READY"
        assert view["cloud_model"] == "UNAVAILABLE"

    def test_classification_separates_local_from_deferable(self, tmp_path):
        survival = build(tmp_path)
        assert survival.classify("memory.index") is DependencyClass.LOCAL_AVAILABLE
        assert survival.classify("artifact.write") is DependencyClass.LOCAL_AVAILABLE
        assert survival.classify("portal.publish") is DependencyClass.DEFERABLE
        assert survival.classify("github.push") is DependencyClass.DEFERABLE
        assert survival.classify("web.research") is DependencyClass.NETWORK_REQUIRED
        assert survival.classify("model.frontier") is DependencyClass.PROVIDER_REQUIRED
        assert survival.classify("unknown.side.effect") is DependencyClass.NON_DEFERABLE

    def test_degraded_status_does_not_claim_cloud_or_local_readiness(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=True, provider=False)
        view = survival.offline_actions()
        assert view["internet"] == "AVAILABLE"
        assert view["cloud_model"] == "UNAVAILABLE"
        assert view["local_model"] == "UNVERIFIED"
        assert view["memory"] == "UNVERIFIED"


class TestStoreAndForward:
    def test_queue_survives_process_restart(self, tmp_path):
        first = build(tmp_path)
        first.observe(network=False, provider=False)
        operation = queue_one(first)
        assert operation.state is QueueState.DEFERRED_OFFLINE

        reopened = OfflineSurvival(tmp_path / "offline-queue.db")
        recovered = reopened.get(operation.id)
        assert recovered.idempotency_key == "op-1"
        assert recovered.payload_digest == operation.payload_digest
        assert recovered.authorization_ref == "owner:lam"
        assert len(reopened.pending()) == 1

    def test_local_operation_must_not_be_deferred(self, tmp_path):
        survival = build(tmp_path)
        with pytest.raises(OperationRejected):
            queue_one(survival, operation_type="artifact.write")

    def test_credentials_are_refused_into_the_queue(self, tmp_path):
        survival = build(tmp_path)
        with pytest.raises(OperationRejected):
            survival.enqueue(
                objective_id="obj-1",
                operation_type="portal.publish",
                payload_ref="artifact://report/1",
                idempotency_key="op-secret",
                authorization_ref="owner:lam",
                payload={"portal_result_token": "not-stored"},
            )

    def test_credentials_nested_inside_lists_are_refused(self, tmp_path):
        survival = build(tmp_path)
        with pytest.raises(OperationRejected):
            survival.enqueue(
                objective_id="obj-1",
                operation_type="portal.publish",
                payload_ref="artifact://report/1",
                idempotency_key="op-nested-secret",
                authorization_ref="owner:lam",
                payload={"items": [{"api_key": "not-stored"}]},
            )

    def test_unknown_operation_is_rejected_before_queueing(self, tmp_path):
        survival = build(tmp_path)
        with pytest.raises(OperationRejected):
            queue_one(survival, operation_type="mystery.side.effect")

    def test_duplicate_enqueue_is_idempotent(self, tmp_path):
        survival = build(tmp_path)
        first = queue_one(survival)
        second = queue_one(survival)
        assert first.id == second.id
        assert len(survival.all()) == 1


class TestReconciliation:
    def test_degraded_reconciles_only_explicitly_revalidated_dependency(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=True, provider=False)
        operation = queue_one(survival, operation_type="web.research")
        calls = []
        results = survival.reconcile(
            executors={"web.research": lambda op: calls.append(op.id) or {"accepted": True}},
            authority_valid=lambda op: True,
            dependency_available=lambda op: op.dependency is DependencyClass.NETWORK_REQUIRED,
        )
        assert calls == [operation.id]
        assert results[0].state is QueueState.RECONCILED

    def test_degraded_without_dependency_proof_executes_nothing(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=True, provider=False)
        operation = queue_one(survival)
        calls = []
        assert survival.reconcile(
            executors={"portal.publish": lambda op: calls.append(op.id) or {"accepted": True}},
            authority_valid=lambda op: True,
        ) == []
        assert calls == []
        assert survival.get(operation.id).state is QueueState.DEFERRED_OFFLINE

    def test_offline_reconcile_does_nothing(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=False, provider=False)
        queue_one(survival)
        called = []
        results = survival.reconcile(
            executors={"portal.publish": lambda op: called.append(op) or {"accepted": True}},
            authority_valid=lambda op: True,
        )
        assert results == []
        assert called == []
        assert survival.get(survival.pending()[0].id).state is QueueState.DEFERRED_OFFLINE

    def test_happy_path_executes_once_and_records_a_receipt(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=False, provider=False)
        operation = queue_one(survival)
        survival.observe(network=True, provider=True)
        survival.confirm_online()
        calls = []

        def executor(op):
            calls.append(op.id)
            return {"accepted": True, "remote_id": "portal-9", "receipt_at": "2026-09-24T01:00:00Z"}

        results = survival.reconcile(
            executors={"portal.publish": executor},
            authority_valid=lambda op: True,
            still_relevant=lambda op: True,
            remote_applied=lambda op: False,
        )
        assert calls == [operation.id]
        assert results[0].state is QueueState.RECONCILED
        assert results[0].executed is True
        assert results[0].receipt["remote_id"] == "portal-9"
        stored = survival.get(operation.id)
        assert stored.state is QueueState.RECONCILED
        assert stored.reconciled_at is not None
        assert stored.receipt["remote_id"] == "portal-9"

        # a second sweep must not re-execute a reconciled operation
        survival.reconcile(executors={"portal.publish": executor}, authority_valid=lambda op: True)
        assert calls == [operation.id]

    def test_concurrent_reconcilers_claim_an_operation_once(self, tmp_path):
        first = build(tmp_path)
        second = OfflineSurvival(tmp_path / "offline-queue.db")
        operation = queue_one(first)
        start = threading.Barrier(2)
        calls = []

        def executor(op):
            calls.append(op.id)
            time.sleep(0.1)
            return {"accepted": True, "remote_id": "portal-once"}

        def reconcile(instance):
            start.wait()
            return instance.reconcile(
                executors={"portal.publish": executor},
                authority_valid=lambda op: True,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(reconcile, (first, second)))

        assert calls == [operation.id]
        assert first.get(operation.id).state is QueueState.RECONCILED

    def test_remote_already_applied_is_not_duplicated(self, tmp_path):
        survival = build(tmp_path)
        operation = queue_one(survival)
        called = []
        results = survival.reconcile(
            executors={"portal.publish": lambda op: called.append(op) or {"accepted": True}},
            authority_valid=lambda op: True,
            remote_applied=lambda op: True,
        )
        assert called == []
        assert results[0].state is QueueState.RECONCILED
        assert results[0].executed is False
        assert survival.get(operation.id).receipt["already_applied"] is True

    def test_authority_revoked_while_offline_stops_execution(self, tmp_path):
        survival = build(tmp_path)
        operation = queue_one(survival)
        called = []
        results = survival.reconcile(
            executors={"portal.publish": lambda op: called.append(op) or {"accepted": True}},
            authority_valid=lambda op: False,
        )
        assert called == []
        assert results[0].state is QueueState.SUPERSEDED
        assert results[0].reason == "authority_invalid"
        assert "authority changed" in survival.get(operation.id).reason

    def test_stale_operation_is_not_executed_blindly(self, tmp_path):
        survival = build(tmp_path)
        queue_one(survival)
        called = []
        results = survival.reconcile(
            executors={"portal.publish": lambda op: called.append(op) or {"accepted": True}},
            authority_valid=lambda op: True,
            still_relevant=lambda op: False,
        )
        assert called == []
        assert results[0].state is QueueState.SUPERSEDED
        assert results[0].reason == "stale"

    def test_failure_is_retained_with_retry_state(self, tmp_path):
        survival = build(tmp_path)
        operation = queue_one(survival)
        moment = time.time()

        def boom(op):
            raise TimeoutError("relay timeout")

        results = survival.reconcile(
            executors={"portal.publish": boom}, authority_valid=lambda op: True, now=moment
        )
        assert results[0].state is QueueState.FAILED
        stored = survival.get(operation.id)
        assert stored.attempt_count == 1
        assert "TimeoutError" in stored.last_error
        assert stored.next_retry_at > moment
        assert stored.state is QueueState.FAILED
        assert stored in survival.pending()

        # nothing may be retried before next_retry_at
        assert survival.reconcile(
            executors={"portal.publish": boom}, authority_valid=lambda op: True, now=moment
        ) == []

    def test_refusal_by_remote_keeps_the_item(self, tmp_path):
        survival = build(tmp_path)
        operation = queue_one(survival)
        results = survival.reconcile(
            executors={"portal.publish": lambda op: {"accepted": False, "detail": "403 no mapping"}},
            authority_valid=lambda op: True,
        )
        assert results[0].state is QueueState.FAILED
        assert "403 no mapping" in survival.get(operation.id).last_error

    def test_receipt_credentials_are_redacted_after_remote_acceptance(self, tmp_path):
        survival = build(tmp_path)
        operation = queue_one(survival)
        survival.reconcile(
            executors={"portal.publish": lambda op: {"accepted": True, "result": {"access_token": "never-store"}}},
            authority_valid=lambda op: True,
        )
        assert survival.get(operation.id).receipt["result"]["access_token"] == "<redacted>"

    def test_expired_operation_is_never_executed(self, tmp_path):
        survival = build(tmp_path)
        moment = time.time()
        operation = survival.enqueue(
            objective_id="obj-1",
            operation_type="portal.publish",
            payload_ref="artifact://report/1",
            idempotency_key="op-expiring",
            authorization_ref="owner:lam",
            expires_at=moment - 1,
            now=moment - 60,
        )
        called = []
        results = survival.reconcile(
            executors={"portal.publish": lambda op: called.append(op) or {"accepted": True}},
            authority_valid=lambda op: True,
            now=moment,
        )
        assert called == []
        assert results == []
        stored = survival.get(operation.id)
        assert stored.state is QueueState.EXPIRED

    def test_view_reports_queued_count(self, tmp_path):
        survival = build(tmp_path)
        survival.observe(network=False, provider=False)
        queue_one(survival, key="op-a")
        queue_one(survival, key="op-b")
        assert survival.offline_actions()["portal_sync"] == "2 ITEMS QUEUED"
