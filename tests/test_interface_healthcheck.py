import unittest
from unittest.mock import MagicMock, patch

from app.interface_healthcheck import check, health_url


class InterfaceHealthcheckTests(unittest.TestCase):
    def test_private_health_origin_is_separate_from_public_pwa_origin(self):
        self.assertEqual(health_url({
            "PRIME_PWA_ORIGIN": "https://jarvis.lamjarvis.com",
            "PRIME_INTERFACE_HEALTH_ORIGIN": "https://192.168.1.23:8443",
        }), "https://192.168.1.23:8443/pwa/")

    def test_existing_lan_configuration_still_works_without_override(self):
        self.assertEqual(health_url({"PRIME_PWA_ORIGIN": "https://192.168.1.23:8443"}), "https://192.168.1.23:8443/pwa/")

    def test_invalid_health_origin_fails_closed(self):
        for origin in ("http://127.0.0.1:8443", "https://example.test/path", "https://user@example.test", "https://example.test?x=1", ""):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                health_url({"PRIME_INTERFACE_HEALTH_ORIGIN": origin})

    def test_health_check_uses_ca_validation_and_private_origin(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch.dict("os.environ", {
            "PRIME_PWA_ORIGIN": "https://jarvis.lamjarvis.com",
            "PRIME_INTERFACE_HEALTH_ORIGIN": "https://192.168.1.23:8443",
        }), patch("app.interface_healthcheck.ssl.create_default_context", return_value="trusted-ca") as ca, patch("app.interface_healthcheck.urlopen", return_value=response) as open_url:
            check()
        ca.assert_called_once_with(cafile="/run/prime-tls/ca.crt")
        open_url.assert_called_once_with("https://192.168.1.23:8443/pwa/", context="trusted-ca", timeout=5)


if __name__ == "__main__":
    unittest.main()
