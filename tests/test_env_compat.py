"""Env-var aliasing round tests (PRIME_* <-> ORQEVIA_*)."""

from app.env_compat import alias_environment


def test_legacy_prime_names_mirror_to_orqevia():
    env = {"PRIME_DATA_DIR": "/data"}
    alias_environment(env)
    assert env["ORQEVIA_DATA_DIR"] == "/data"


def test_new_orqevia_names_mirror_to_legacy_prime():
    env = {"ORQEVIA_SPINE_TOKEN": "x"}
    alias_environment(env)
    assert env["PRIME_SPINE_TOKEN"] == "x"


def test_existing_values_are_never_overwritten():
    env = {"PRIME_DATA_DIR": "/old", "ORQEVIA_DATA_DIR": "/new"}
    alias_environment(env)
    assert env == {"PRIME_DATA_DIR": "/old", "ORQEVIA_DATA_DIR": "/new"}


def test_unrelated_variables_are_untouched():
    env = {"HOME": "/root", "PRIMEISH": "x", "ORQEVIAISH": "y"}
    alias_environment(env)
    assert env == {"HOME": "/root", "PRIMEISH": "x", "ORQEVIAISH": "y"}


def test_repeated_aliasing_is_idempotent():
    env = {"PRIME_COMPUTE_QUEUE_DB": "/tmp/q.db"}
    alias_environment(env)
    alias_environment(env)
    assert env["ORQEVIA_COMPUTE_QUEUE_DB"] == "/tmp/q.db"
    assert len(env) == 2
