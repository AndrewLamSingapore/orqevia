"""Secret identifiers in configuration; resolve values only at the transport boundary."""
import os
import re


class SecretUnavailable(RuntimeError):
    pass


def resolve_secret(reference):
    if not isinstance(reference,str):raise SecretUnavailable('Invalid secret reference')
    if reference.startswith('env:'):
        name=reference[4:]
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',name):raise SecretUnavailable('Invalid environment secret reference')
        value=os.environ.get(name)
        if not value:raise SecretUnavailable('Configured secret is unavailable')
        return value
    # Other stores can be supplied through the same resolver interface; never
    # silently treat an unresolved reference as an API credential.
    raise SecretUnavailable('Secret store adapter is unavailable')
