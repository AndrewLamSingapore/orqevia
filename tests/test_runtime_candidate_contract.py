"""Static fail-closed deployment contract for the isolated runtime candidate."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_optional_runtime_features_and_profile_default_off():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "PRIME_QUEUE_CONCURRENCY: ${PRIME_QUEUE_CONCURRENCY:-1}" in compose
    assert "PRIME_LOCAL_ADMISSION_MODE: ${PRIME_LOCAL_ADMISSION_MODE:-golden_n1}" in compose
    assert "OLLAMA_NUM_PARALLEL: ${OLLAMA_NUM_PARALLEL:-1}" in compose
    assert "PRIME_CONTEXT_PACKS_ENABLED: ${PRIME_CONTEXT_PACKS_ENABLED:-0}" in compose
    assert "PRIME_SKILL_PACKS_ENABLED: ${PRIME_SKILL_PACKS_ENABLED:-0}" in compose
    assert "PRIME_MEASURED_COMPUTE_PROFILE: ${PRIME_MEASURED_COMPUTE_PROFILE:-}" in compose
    assert "PRIME_MEASURED_COMPUTE_PROFILE_SHA256: ${PRIME_MEASURED_COMPUTE_PROFILE_SHA256:-}" in compose


def test_explicit_admission_guards_reach_prime_container():
    prime_service = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").split("  interface:", 1)[0]
    for name in (
        "PRIME_BACKEND_MEMORY_RECEIPT",
        "PRIME_SSD_THERMAL_ENFORCE",
        "PRIME_SSD_THERMAL_POLICY",
        "PRIME_SSD_THERMAL_POLICY_SHA256",
        "PRIME_SSD_THERMAL_RECEIPT",
    ):
        assert f"      {name}: ${{{name}:-}}" in prime_service
