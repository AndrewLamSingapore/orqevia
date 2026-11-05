"""Existing internal intelligence probe using the native credential name."""

import os
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8100/api/orqevia/intelligence/health",
    headers={"Authorization": "Bearer " + os.environ["ORQEVIA_SPINE_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=3) as response:
    assert response.status == 200
