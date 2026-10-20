import pytest

from mbti_in_thoughts import (
    DISTRIBUTION_NAME,
    MBTI_TYPES,
    PROFILE_DATA_SHA256,
    RUNTIME_WHEEL_SHA256,
    SOURCE_REVISION,
    UPSTREAM_WHEEL_SHA256,
    health,
    load_profiles,
    profile_names,
    profile_prompt,
    upstream_installation,
)


def test_upstream_priming_profiles_are_complete_and_verifiable():
    profiles = load_profiles()
    assert len(profiles) >= 18
    assert all(name in profiles for name in MBTI_TYPES)
    assert all(len(profiles[name]) > 100 for name in MBTI_TYPES)
    assert profile_names() == tuple(profiles)
    assert profile_prompt("intj") == profiles["INTJ"]
    assert health()["profile_data_sha256"] == PROFILE_DATA_SHA256
    assert health()["upstream_wheel_sha256"] == UPSTREAM_WHEEL_SHA256
    assert health()["runtime_wheel_sha256"] == RUNTIME_WHEEL_SHA256
    assert health()["activation"] == "disabled_until_explicit_per_agent_profile"


def test_unknown_upstream_profile_is_rejected():
    with pytest.raises(KeyError, match="unknown MBTI-in-Thoughts profile"):
        profile_prompt("XXXX")


def test_installation_report_preserves_upstream_provenance():
    report = upstream_installation()
    assert report["distribution"] == DISTRIBUTION_NAME
    assert report["source_revision"] == SOURCE_REVISION
    assert report["profiles_available"] is True
    if report["installed"]:
        assert report["version"] == "1.0.0"
        assert report["src_package_available"] is True
