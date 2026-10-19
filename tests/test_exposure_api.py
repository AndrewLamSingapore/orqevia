"""Actual ASGI owner-local view tests; not a production deployment proof."""
import httpx
import pytest
import asyncio

from app.exposure_api import exposure_view


def test_missing_read_view_has_no_write_or_network(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path / 'not-created'))
    result = exposure_view()
    assert result['findings'] == [] and result['monitoring_active'] is False
    assert not (tmp_path / 'not-created').exists()


def test_owner_local_route_and_origin_denials(monkeypatch, tmp_path):
    asyncio.run(_owner_local_route_and_origin_denials(monkeypatch, tmp_path))


async def _owner_local_route_and_origin_denials(monkeypatch, tmp_path):
    from app.production_entry import app
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path / 'not-created'))
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN', 'synthetic-pxi-owner')
    transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 5678))
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8000') as client:
        response = await client.get('/control/api/exposure-intelligence')
        assert response.status_code == 200 and response.json()['permanent_agents_added'] == 0
        denied = await client.get('/control/api/exposure-intelligence', headers={'Origin': 'https://evil.example'})
        assert denied.status_code == 403
        denied = await client.get('/control/api/exposure-intelligence', headers={'Host': 'evil.example'})
        assert denied.status_code == 403
    assert not (tmp_path / 'not-created').exists()


def test_remote_peer_cannot_read_owner_findings(monkeypatch):
    asyncio.run(_remote_peer_cannot_read_owner_findings(monkeypatch))


async def _remote_peer_cannot_read_owner_findings(monkeypatch):
    from app.production_entry import app
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN', 'synthetic-pxi-owner')
    transport = httpx.ASGITransport(app=app, client=('192.0.2.5', 1234))
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8000') as client:
        assert (await client.get('/control/api/exposure-intelligence')).status_code == 403


def test_existing_exposure_view_preserves_ledger_bytes_and_integrity(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    import hashlib
    import json
    from app.evidence_product import EvidenceLedger
    from app.exposure_intelligence import ExposureIntelligence
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    path = tmp_path / 'evidence-lens.db'
    service = ExposureIntelligence(EvidenceLedger(path),
                                  clock=lambda: datetime(2026, 10, 8, 9, tzinfo=timezone.utc))
    raw = json.dumps({'dateReleased': '2026-10-08T08:00:00Z',
                      'vulnerabilities': [{'cveID': 'CVE-2026-12345'}]}).encode()
    service.ingest_kev(raw, retrieved_at='2026-10-08T09:00:00Z')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    view = exposure_view()
    assert len(view['findings']) == 1 and len(view['alerts']) == 1
    assert view['semantic']['grants_authority'] is False
    assert view['monitoring_active'] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_corrupt_exposure_ledger_fails_without_repairing_or_overwriting(monkeypatch, tmp_path):
    import sqlite3
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    path = tmp_path / 'evidence-lens.db'
    raw = b'not a database'
    path.write_bytes(raw)
    with pytest.raises(sqlite3.DatabaseError):
        exposure_view()
    assert path.read_bytes() == raw
