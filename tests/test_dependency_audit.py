from unittest.mock import Mock
import httpx
from scripts import audit_dependencies


def test_incomplete_response_is_unverified_not_clean(monkeypatch):
    response = Mock(); response.json.return_value = {"results": []}
    post = Mock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(audit_dependencies.time, "sleep", lambda _: None)
    result = audit_dependencies.audit([('fixture', '1.0')])
    assert result['status'] == 'UNVERIFIED'
    assert post.call_count == 3


def test_advisories_fail_the_gate_without_transmitting_private_data(monkeypatch):
    response = Mock(); response.json.return_value = {"results": [{"vulns": [{"id": "fixture-advisory"}]}]}
    post = Mock(return_value=response); monkeypatch.setattr(httpx, "post", post)
    result = audit_dependencies.audit([('fixture', '1.0')])
    assert result['status'] == 'FINDINGS'
    assert post.call_args.kwargs['json'] == {'queries': [{'package': {'name': 'fixture', 'ecosystem': 'PyPI'}, 'version': '1.0'}]}


def test_complete_empty_findings_pass(monkeypatch):
    response = Mock(); response.json.return_value = {"results": [{}]}
    monkeypatch.setattr(httpx, "post", Mock(return_value=response))
    assert audit_dependencies.audit([('fixture', '1.0')])['status'] == 'NO_KNOWN_FINDINGS'
