from app.protected_env import install_signed_closure_env_lookup


def test_pinned_lookup_reads_current_name(monkeypatch):
    install_signed_closure_env_lookup()
    monkeypatch.setenv("ORQEVIA_DATA_DIR", "/data")
    monkeypatch.delenv("PRIME_DATA_DIR", raising=False)

    assert __import__("os").getenv("PRIME_DATA_DIR") == "/data"


def test_explicit_legacy_value_still_wins(monkeypatch):
    install_signed_closure_env_lookup()
    monkeypatch.setenv("ORQEVIA_DATA_DIR", "/current")
    monkeypatch.setenv("PRIME_DATA_DIR", "/legacy")

    assert __import__("os").getenv("PRIME_DATA_DIR") == "/legacy"
