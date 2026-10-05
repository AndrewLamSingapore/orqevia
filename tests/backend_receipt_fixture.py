"""Synthetic operator receipt for tests that exercise other inference behavior.

This file is test-only. Production still requires the trusted operator feed.
"""
import json
import time

from app import backend_admission


def install(monkeypatch, tmp_path, endpoint, *, available_mib=16384):
    path = tmp_path / 'synthetic-backend-receipt.json'
    path.write_text(json.dumps({
        'schema': backend_admission.SCHEMA,
        'endpoint': endpoint.rstrip('/'),
        'instance': 'test-backend',
        'boot_id': 'test-boot',
        'scope_complete': True,
        'capacity_mib': 32768,
        'available_mib': available_mib,
        'captured_at': time.time(),
    }), encoding='utf-8')
    monkeypatch.setenv('PRIME_BACKEND_MEMORY_RECEIPT', str(path))
    return path
