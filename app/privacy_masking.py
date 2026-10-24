"""Deterministic masking for report export: emails, phones and tokens."""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{6,}\d)(?!\d)")
_BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9._-]{8,})")


def mask_email(value: str) -> str:
    user, _, domain = value.rpartition("@")
    masked = user[:1] + "***" + user[-1:] if len(user) > 2 else "***"
    return masked + "@" + domain


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    return "***-***-" + digits[-4:] if len(digits) >= 4 else "***"


def mask_token(value: str) -> str:
    return value[:4] + "***" if len(value) > 8 else "***"


def mask_text(text: str) -> str:
    """Mask emails, phone numbers and bearer tokens in free text."""
    masked = _EMAIL.sub(lambda m: mask_email(m.group(0)), text)
    masked = _PHONE.sub(lambda m: mask_phone(m.group(0)), masked)
    return _BEARER.sub(lambda m: m.group(1) + mask_token(m.group(2)), masked)
