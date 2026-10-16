
"""ORQEVIA application package.

Env-var aliasing round: normalize PRIME_* <-> ORQEVIA_* names once at import
time so old readers, new readers and either compose generation interoperate.
See governance/BRAND-AND-NAMING-BOUNDARY.md.
"""

from .env_compat import alias_environment

alias_environment()
