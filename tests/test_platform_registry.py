from app.platform_registry import load_platforms, public_platforms


def test_registry_loads_and_is_public_safe():
    platforms = load_platforms()
    assert len(platforms) >= 4
    assert all(entry["source_url"].startswith("https://") for entry in platforms)
    public = public_platforms()
    assert {entry["id"] for entry in public} == {entry["id"] for entry in platforms}
