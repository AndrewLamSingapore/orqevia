from fastapi import HTTPException
from fastapi.responses import JSONResponse
import pytest


def test_fact_parsing_preserves_semantics_without_recursive_regex(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIME_DATA_DIR", str(tmp_path))
    from app.main import extract_fact, recall_key

    assert extract_fact("Remember my favorite city is Singapore.") == (
        "favorite city",
        "Singapore",
        "preference",
    )
    assert extract_fact("Please remember that my passport office is Central, remember this") == (
        "passport office",
        "Central",
        "fact",
    )
    assert recall_key("What is my favorite city?") == "favorite city"
    assert recall_key("whats my passport office") == "passport office"


def test_proxy_urls_are_fixed_allowlist_values():
    from app.orqevia import ui

    assert set(ui.READ_ONLY_URLS) == ui.READ_ONLY_PATHS
    assert all(ui.READ_ONLY_URLS[path] == f"{ui.UPSTREAM}/{path}" for path in ui.READ_ONLY_PATHS)


def test_cookie_issuance_rejects_noncanonical_tokens():
    from app import pwa_sessions

    with pytest.raises(HTTPException):
        pwa_sessions._cookies(JSONResponse({}), "short", None)
    with pytest.raises(HTTPException):
        pwa_sessions._cookies(JSONResponse({}), None, "invalid cookie value")
