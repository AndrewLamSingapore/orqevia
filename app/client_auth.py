"""Network authentication only; does not authorize individual agent actions."""
import hmac
import os
from fastapi import HTTPException


def authenticate_owner(authorization: str | None):
    expected=os.getenv('ORQEVIA_SPINE_TOKEN','').strip()
    supplied=authorization[7:].strip() if authorization and authorization.lower().startswith('bearer ') else ''
    if not expected:raise HTTPException(503,'Owner authentication is not configured')
    if not supplied or not hmac.compare_digest(supplied,expected):raise HTTPException(401,'Client authentication required')
