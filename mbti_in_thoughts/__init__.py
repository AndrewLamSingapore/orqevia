"""Import facade for the pinned upstream MBTI-in-Thoughts distribution.

The upstream project publishes a distribution named ``MBTI-in-Thoughts`` but
ships its research code under the ``src`` directory rather than a module named
after the distribution. ORQEVIA installs the upstream wheel without its
research dependency lock set and exposes a stable import plus the upstream
priming profiles here.

Importing a profile does not activate conditioning. ORQEVIA continues to require
an explicitly enabled per-agent profile, and behavioral style remains
subordinate to system, security, permission, evidence and task instructions.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, distribution
from importlib.resources import files
from typing import Any, Mapping

DISTRIBUTION_NAME = "MBTI-in-Thoughts"
DISTRIBUTION_VERSION = "1.0.0"
SOURCE_REVISION = "ba760ed73b9592798c964ad64db11a1ca4c7ce8f"
SOURCE_URL = "https://github.com/spcl/MBTI-in-Thoughts"
UPSTREAM_WHEEL_SHA256 = "b833d4f8f9529d7d84d869ce6394a9ab260332d8248f1bf5fa6798c05954c5e6"
RUNTIME_WHEEL_SHA256 = "d44559e35f720cb3295b5dcc13ca95c33343da5e3c81a1743a234ce1617d2af8"
WHEEL_SHA256 = RUNTIME_WHEEL_SHA256
PROFILE_DATA_SHA256 = "bcc7338677d5295259e2041b8e7e8fed7c2d7349a356aa06bf0e49ad82838258"
PROFILE_DATA_FILE = "priming_without_mention_of_mbti.json"

MBTI_TYPES = (
    "ESTJ",
    "ESTP",
    "ESFJ",
    "ESFP",
    "ENTJ",
    "ENTP",
    "ENFJ",
    "ENFP",
    "ISTJ",
    "ISTP",
    "ISFJ",
    "ISFP",
    "INTJ",
    "INTP",
    "INFJ",
    "INFP",
)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def upstream_installation() -> dict[str, Any]:
    """Return the observed state of the upstream distribution."""

    try:
        dist = distribution(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return {
            "distribution": DISTRIBUTION_NAME,
            "expected_version": DISTRIBUTION_VERSION,
            "source_revision": SOURCE_REVISION,
            "source_url": SOURCE_URL,
            "installed": False,
            "version": None,
            "location": None,
            "src_package_available": _module_available("src"),
            "profiles_available": _profile_data_path().is_file(),
        }
    return {
        "distribution": DISTRIBUTION_NAME,
        "expected_version": DISTRIBUTION_VERSION,
        "source_revision": SOURCE_REVISION,
        "source_url": SOURCE_URL,
        "installed": True,
        "version": dist.version,
        "location": str(dist.locate_file("")),
        "src_package_available": _module_available("src"),
        "profiles_available": _profile_data_path().is_file(),
    }


def _profile_data_path():
    return files(__package__).joinpath("data", PROFILE_DATA_FILE)


@lru_cache(maxsize=1)
def load_profiles() -> Mapping[str, str]:
    """Load the upstream priming prompts without activating them."""

    raw = _profile_data_path().read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != PROFILE_DATA_SHA256:
        raise RuntimeError(
            f"MBTI-in-Thoughts profile data hash mismatch: expected {PROFILE_DATA_SHA256}, observed {observed}"
        )
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
    ):
        raise RuntimeError("MBTI-in-Thoughts profile data must map names to prompts")
    return parsed


def profile_names() -> tuple[str, ...]:
    """Return the profile names supplied by upstream, including its controls."""

    return tuple(load_profiles())


def profile_prompt(mbti_type: str) -> str:
    """Return one upstream priming prompt by case-insensitive profile name."""

    normalized = mbti_type.strip().upper()
    profiles = load_profiles()
    if normalized not in profiles:
        raise KeyError(f"unknown MBTI-in-Thoughts profile: {mbti_type}")
    return profiles[normalized]


def health() -> dict[str, Any]:
    """Return a compact readiness report suitable for runtime verification."""

    profiles = load_profiles()
    return {
        **upstream_installation(),
        "profile_count": len(profiles),
        "mbti_profile_count": sum(name in profiles for name in MBTI_TYPES),
        "profile_data_sha256": PROFILE_DATA_SHA256,
        "upstream_wheel_sha256": UPSTREAM_WHEEL_SHA256,
        "runtime_wheel_sha256": RUNTIME_WHEEL_SHA256,
        "wheel_sha256": WHEEL_SHA256,
        "activation": "disabled_until_explicit_per_agent_profile",
    }


__all__ = [
    "DISTRIBUTION_NAME",
    "DISTRIBUTION_VERSION",
    "MBTI_TYPES",
    "PROFILE_DATA_SHA256",
    "RUNTIME_WHEEL_SHA256",
    "SOURCE_REVISION",
    "SOURCE_URL",
    "UPSTREAM_WHEEL_SHA256",
    "WHEEL_SHA256",
    "health",
    "load_profiles",
    "profile_names",
    "profile_prompt",
    "upstream_installation",
]
