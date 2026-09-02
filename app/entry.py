"""PRIME runtime entrypoint with the JARVIS Control Surface."""
from .main import app
from .portal_api import router as portal_router
from .velyqua_api import router as velyqua_router
from .spine_api import router as spine_router
from .cognitive_api import router as cognitive_router
from .control_surface import router as control_surface_router
from .portfolio_relay import PortfolioRelayPoller
from .runtime import events

portfolio_relay = PortfolioRelayPoller(events)

app.include_router(portal_router)
app.include_router(velyqua_router)
app.include_router(spine_router)
app.include_router(cognitive_router)
app.include_router(control_surface_router)


@app.on_event("startup")
def start_portfolio_relay() -> None:
    portfolio_relay.start()


@app.on_event("shutdown")
def stop_portfolio_relay() -> None:
    portfolio_relay.stop()
