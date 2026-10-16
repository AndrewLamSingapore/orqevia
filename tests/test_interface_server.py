import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import interface_server


class InterfaceServerTests(unittest.TestCase):
    def test_public_profile_download_headers_preserve_bytes(self):
        from fastapi.responses import Response
        from unittest.mock import AsyncMock
        static = next(r.app for r in interface_server.app.routes if getattr(r, 'path', '') == '/pwa')
        body=b'public-profile-fixture'
        with patch.dict('os.environ', {'PRIME_PWA_ORIGIN':'https://testserver'}), patch.object(static, 'check_config', AsyncMock()), patch.object(static, 'get_response', AsyncMock(return_value=Response(body))), TestClient(interface_server.app, base_url='https://testserver') as client:
            response=client.get('/pwa/ORQEVIA-ABEX-HTTPS.mobileconfig')
            assert response.content==body
            assert response.headers['content-type']=='application/x-apple-aspen-config'
            assert response.headers['content-disposition']=='attachment; filename="ORQEVIA-ABEX-HTTPS.mobileconfig"'
        with patch.dict('os.environ', {'PRIME_PWA_ORIGIN':'https://testserver'}), TestClient(interface_server.app, base_url='https://testserver') as client:
            missing=client.get('/pwa/ORQEVIA-ABEX-HTTPS.mobileconfig')
            assert missing.status_code==404
            assert 'content-disposition' not in missing.headers

    def test_only_adopted_routes_and_protocol_header(self):
        with TestClient(interface_server.app, base_url='https://testserver') as client:
            response=client.get('/health')
            assert response.status_code==404
            assert response.json()['error']['code']=='NOT_FOUND'
            assert response.headers['X-PRIME-Protocol']=='jarvis.interface.v1'
            assert client.get('/api/interface/v1/health').status_code==404
            assert client.get('/docs').status_code==404

    def test_http_is_rejected_before_request_body_validation(self):
        with TestClient(interface_server.app) as client:
            response=client.post('/interface/v1/objectives',headers={'X-Forwarded-Proto':'https'},json={})
            assert response.status_code==426
            assert response.json()['error']['code']=='HTTPS_REQUIRED'

    def test_schema_error_does_not_echo_input(self):
        # Reach schema validation with a fixture-authenticated request. Missing
        # credentials correctly fail earlier with 401 at the contract boundary.
        with patch('app.interface_contract.authorize',return_value=('fixture-client','fixture-auth')), TestClient(interface_server.app,base_url='https://testserver') as client:
            response=client.post('/interface/v1/objectives',json={'objective':{'secret':'fixture-do-not-echo'}})
            assert response.status_code==422
            assert response.json()['error']['code']=='INVALID_REQUEST'
            assert 'fixture-do-not-echo' not in response.text

    def test_unexpected_error_is_sanitized_without_automatic_retry(self):
        with patch('app.interface_contract.node.client_identity',side_effect=RuntimeError('private-fixture-path')):
            with TestClient(interface_server.app,base_url='https://testserver',raise_server_exceptions=False) as client:
                response=client.get('/interface/v1/identity')
        assert response.status_code==500
        assert response.json()['error']['retryable'] is False
        assert 'private-fixture-path' not in response.text


if __name__=='__main__':unittest.main()
