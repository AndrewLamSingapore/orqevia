"""Dual-accept round: responses carry legacy and new protocol headers."""

from starlette.testclient import TestClient

from app.interface_server import ORQEVIA_PROTOCOL, PROTOCOL, app, error_response


def test_error_responses_carry_both_protocol_headers():
    response = error_response(409)
    assert response.headers['X-PRIME-Protocol'] == PROTOCOL == 'jarvis.interface.v1'
    assert response.headers['X-ORQEVIA-Protocol'] == ORQEVIA_PROTOCOL == 'orqevia.interface.v1'


def test_https_responses_carry_both_protocol_headers():
    client = TestClient(app)
    response = client.get('https://testserver/interface/v1/does-not-exist')
    assert response.status_code == 404
    assert response.headers['X-PRIME-Protocol'] == 'jarvis.interface.v1'
    assert response.headers['X-ORQEVIA-Protocol'] == 'orqevia.interface.v1'
