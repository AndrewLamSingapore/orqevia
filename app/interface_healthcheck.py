"""Check the private Interface listener independently of the public PWA origin.

The public origin can be behind Cloudflare Access and cannot be used as the
container's health endpoint. Keep validating the existing private TLS chain.
"""

import os
import ssl
from urllib.parse import urlsplit
from urllib.request import urlopen


def health_url(environ=None):
    values = os.environ if environ is None else environ
    origin = (values.get("PRIME_INTERFACE_HEALTH_ORIGIN") or values.get("PRIME_PWA_ORIGIN") or "").rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Interface health origin must be an HTTPS origin")
    return origin + "/pwa/"


def check():
    context = ssl.create_default_context(cafile="/run/prime-tls/ca.crt")
    with urlopen(health_url(), context=context, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("Interface health endpoint unavailable")
        response.read(1)


if __name__ == "__main__":
    check()
