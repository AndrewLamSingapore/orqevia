"""One-way environment lookup bridge for byte-pinned signed-closure modules.

The named modules are pinned to a reviewed revision and still read their
historical environment keys. This bridge reads current ORQEVIA_* values when a
pinned module requests the legacy name and no explicit legacy value exists. It
can be removed when a new signed closure is issued.
"""

from __future__ import annotations

import os


def install_signed_closure_env_lookup() -> None:
    if getattr(os.getenv, "_orqevia_legacy_bridge", False):
        return
    original = os.getenv

    def bridged_getenv(key, default=None):
        if key.startswith("PRIME_") and key not in os.environ:
            current = "ORQEVIA_" + key[len("PRIME_") :]
            if current in os.environ:
                return os.environ[current]
        return original(key, default)

    bridged_getenv._orqevia_legacy_bridge = True
    os.getenv = bridged_getenv
