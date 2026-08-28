"""PRIME runtime entrypoint.

Keeps the large legacy application untouched while composing versioned
integration routers around its existing FastAPI app.
"""
from .main import app
from .portal_api import router as portal_router
from .velyqua_api import router as velyqua_router

app.include_router(portal_router)
app.include_router(velyqua_router)
