"""Fixed-path file-secret contract for the optional Higgsfield provider."""

import pytest

from app import secret_refs
from app.higgsfield_media import HiggsfieldApiProvider, HiggsfieldMediaSettings


def provider(reference="file:HIGGSFIELD_API_KEY"):
    return HiggsfieldApiProvider(
        HiggsfieldMediaSettings(
            enabled=False,
            api_key_ref=reference,
        )
    )


def test_higgsfield_file_secret_is_fixed_read_only_reference(monkeypatch, tmp_path):
    mounted = tmp_path / "higgsfield_api_key"
    mounted.write_text("key-id:key-secret", encoding="ascii")
    monkeypatch.setattr(secret_refs, "HIGGSFIELD_API_KEY_FILE", str(mounted))

    assert secret_refs.resolve_secret("file:HIGGSFIELD_API_KEY") == "key-id:key-secret"
    health = provider().health()
    assert health["readiness"] == "READY"
    assert health["enabled"] is False
    for reference in (
        "file:../higgsfield_api_key",
        f"file:{mounted}",
        "file:OTHER_API_KEY",
        "file:",
    ):
        with pytest.raises(secret_refs.SecretUnavailable):
            secret_refs.resolve_secret(reference)


@pytest.mark.parametrize(
    "contents",
    ("", "key-id:key-secret\n", "key id:key-secret", "x" * 4097),
)
def test_higgsfield_file_secret_rejects_invalid_or_empty_content(monkeypatch, tmp_path, contents):
    mounted = tmp_path / "higgsfield_api_key"
    mounted.write_text(contents, encoding="ascii")
    monkeypatch.setattr(secret_refs, "HIGGSFIELD_API_KEY_FILE", str(mounted))
    with pytest.raises(secret_refs.SecretUnavailable) as failure:
        secret_refs.resolve_secret("file:HIGGSFIELD_API_KEY")
    assert "key-id" not in str(failure.value)
    assert str(mounted) not in str(failure.value)


def test_higgsfield_provider_rejects_malformed_complete_key(monkeypatch, tmp_path):
    mounted = tmp_path / "higgsfield_api_key"
    mounted.write_text("not-a-complete-key", encoding="ascii")
    monkeypatch.setattr(secret_refs, "HIGGSFIELD_API_KEY_FILE", str(mounted))
    assert provider().health()["readiness"] == "CREDENTIAL_UNAVAILABLE"
