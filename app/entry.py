"""PRIME runtime entrypoint with the JARVIS Control Surface."""
from .main import app
from .portal_api import router as portal_router
from .velyqua_api import router as velyqua_router
from .spine_api import router as spine_router
from .harness_api import router as harness_router
from .cognitive_api import router as cognitive_router
from .public_agent_api import router as public_agent_router
from .control_surface import router as control_surface_router
from .portfolio_relay import PortfolioRelayPoller
from .public_trace_publisher import PublicTracePublisher
from .runtime import events, authority
from .compute_queue_api import router as compute_queue_router, start_compute_queue, stop_compute_queue

portfolio_relay = PortfolioRelayPoller(events)
public_trace_publisher = PublicTracePublisher(authority)

app.include_router(portal_router)
app.include_router(velyqua_router)
app.include_router(spine_router)
app.include_router(harness_router)
app.include_router(cognitive_router)
app.include_router(public_agent_router)
app.include_router(control_surface_router)
app.include_router(compute_queue_router)


@app.on_event("startup")
def start_runtime_services() -> None:
    portfolio_relay.start()
    public_trace_publisher.start()
    start_compute_queue()


@app.on_event("shutdown")
def stop_runtime_services() -> None:
    stop_compute_queue()
    public_trace_publisher.stop()
    portfolio_relay.stop()
