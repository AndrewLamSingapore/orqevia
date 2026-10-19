"""Secret identifiers in configuration; resolve values only at the transport boundary."""
import os
import re
import stat


HF_TOKEN_FILE = '/run/secrets/hf_token'
HIGGSFIELD_API_KEY_FILE = '/run/secrets/higgsfield_api_key'


class SecretUnavailable(RuntimeError):
    pass


def _fixed_secret_file(name):
    if name == 'HF_TOKEN':
        return HF_TOKEN_FILE
    if name == 'HIGGSFIELD_API_KEY':
        return HIGGSFIELD_API_KEY_FILE
    raise SecretUnavailable('Secret store adapter is unavailable')


def _read_secret_file(path):
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise SecretUnavailable('Configured secret is unavailable')
        flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 4096:
                raise SecretUnavailable('Configured secret is unavailable')
            raw = os.read(descriptor, 4097)
        finally:
            os.close(descriptor)
        if len(raw) != info.st_size:
            raise SecretUnavailable('Configured secret is unavailable')
        value = raw.decode('ascii')
        if any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in value):
            raise SecretUnavailable('Configured secret is unavailable')
        return value
    except (OSError, UnicodeError):
        raise SecretUnavailable('Configured secret is unavailable') from None


def resolve_secret(reference):
    if not isinstance(reference,str):raise SecretUnavailable('Invalid secret reference')
    if reference.startswith('env:'):
        name=reference[4:]
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',name):raise SecretUnavailable('Invalid environment secret reference')
        value=os.environ.get(name)
        if not value:raise SecretUnavailable('Configured secret is unavailable')
        return value
    if reference.startswith('file:'):
        # File references resolve only to fixed Compose secret mounts. Never
        # accept a caller-supplied path or expose filesystem errors to callers.
        return _read_secret_file(_fixed_secret_file(reference[5:]))
    # Other stores can be supplied through the same resolver interface; never
    # silently treat an unresolved reference as an API credential.
    raise SecretUnavailable('Secret store adapter is unavailable')
