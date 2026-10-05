"""Secret identifiers in configuration; resolve values only at the transport boundary."""
import os
import re
import stat


HF_TOKEN_FILE = '/run/secrets/hf_token'


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
    if reference == 'file:HF_TOKEN':
        # The only file-backed reference is a fixed Compose secret mount. Never
        # accept a catalog-supplied path or expose filesystem errors to callers.
        try:
            if not stat.S_ISREG(os.lstat(HF_TOKEN_FILE).st_mode):
                raise SecretUnavailable('Configured secret is unavailable')
            flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            descriptor = os.open(HF_TOKEN_FILE, flags)
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
    # Other stores can be supplied through the same resolver interface; never
    # silently treat an unresolved reference as an API credential.
    raise SecretUnavailable('Secret store adapter is unavailable')
