from decimal import Decimal

import pytest

from app.media_generation import (
    MediaJob,
    MediaJobRequest,
    MediaJobStore,
    MediaProviderError,
)


def request(**changes):
    values = {
        "task_id": "task-media-1",
        "operation": "image",
        "model_path": "official/model/path",
        "payload": {"prompt": "a neutral fixture image"},
        "data_classification": "CLOUD_PERMITTED",
        "max_cost_usd": Decimal("0.10"),
        "charge_authorized": True,
        "idempotency_key": "fixture-idempotency-key",
    }
    values.update(changes)
    return MediaJobRequest.create(**values)


def test_media_request_rejects_unbounded_or_secret_payloads():
    with pytest.raises(MediaProviderError, match="INVALID_MODEL_PATH"):
        request(model_path="../escape")
    with pytest.raises(MediaProviderError, match="MEDIA_PAYLOAD_CONTAINS_SECRET_FIELD"):
        request(payload={"api_key": "must-not-cross-boundary"})
    with pytest.raises(MediaProviderError, match="INVALID_CHARGE_AUTHORIZATION"):
        request(charge_authorized="yes")
    with pytest.raises(MediaProviderError, match="INVALID_MAX_COST_USD"):
        request(max_cost_usd=0)


def test_media_job_store_is_idempotent_and_does_not_store_payload(tmp_path):
    store = MediaJobStore(tmp_path / "media-jobs.db")
    value = request()
    row = store.begin(value, owner_id="owner", provider_id="higgsfield")
    replay = store.begin(value, owner_id="owner", provider_id="higgsfield")
    assert row["idempotency_key"] == replay["idempotency_key"]
    job = MediaJob(
        request_id="d7e6c0f3-6699-4f6c-bb45-2ad7fd9158ff",
        status="queued",
        provider="higgsfield",
        operation="image",
        model_path="official/model/path",
        task_id="task-media-1",
    )
    store.set_submitted(value.idempotency_key, job)
    assert store.active_count(owner_id="owner", provider_id="higgsfield") == 1
    with pytest.raises(MediaProviderError, match="IDEMPOTENCY_CONFLICT"):
        store.begin(request(payload={"prompt": "different"}), owner_id="owner", provider_id="higgsfield")
    with store._connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(media_jobs)")}
    assert "payload" not in columns


def test_media_job_store_owner_scope_and_status_update(tmp_path):
    store = MediaJobStore(tmp_path / "media-jobs.db")
    value = request()
    store.begin(value, owner_id="owner-a", provider_id="higgsfield")
    job = MediaJob(
        request_id="d7e6c0f3-6699-4f6c-bb45-2ad7fd9158ff",
        status="queued",
        provider="higgsfield",
        operation="image",
        model_path="official/model/path",
        task_id="task-media-1",
        estimated_usd=Decimal("0.01"),
    )
    store.set_submitted(value.idempotency_key, job)
    assert store.get(job.request_id, owner_id="owner-a")["status"] == "queued"
    assert store.get(job.request_id, owner_id="owner-b") is None
    completed = MediaJob(
        request_id=job.request_id,
        status="completed",
        provider="higgsfield",
        operation="image",
        model_path="official/model/path",
        task_id="task-media-1",
        outputs=({"type": "image", "url": "https://cdn.example.com/out.png"},),
        estimated_usd=Decimal("0.01"),
    )
    store.update(job.request_id, completed)
    assert store.get(job.request_id, owner_id="owner-a")["status"] == "completed"
