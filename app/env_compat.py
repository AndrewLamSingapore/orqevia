"""Transitional PRIME_* <-> ORQEVIA_* environment aliasing.

The env-var aliasing round from governance/BRAND-AND-NAMING-BOUNDARY.md:
readers keep whatever name they know while the deployment flips names in
stages (alias -> compose flip -> removal). This module mirrors every
ORQEVIA_* variable onto its legacy PRIME_* spelling and vice versa whenever
the counterpart is absent. When both spellings are set, nothing is
overridden, so an explicit value always wins.

Removal round: delete this module, the call in app/__init__.py and
tests/test_env_compat.py once the compose flip and the literal renames land.
"""

import os


def alias_environment(environ=None):
    """Mirror ORQEVIA_*/PRIME_* variables onto each other in *environ*.

    Accepts a plain dict for tests and returns it; defaults to ``os.environ``.
    Existing values always win - a set counterpart is never overwritten.
    """
    env = os.environ if environ is None else environ
    for key in [k for k in env if k.startswith("ORQEVIA_") or k.startswith("PRIME_")]:
        if key.startswith("ORQEVIA_"):
            counterpart = "PRIME_" + key[len("ORQEVIA_"):]
        else:
            counterpart = "ORQEVIA_" + key[len("PRIME_"):]
        if counterpart not in env:
            env[counterpart] = env[key]
    return env
