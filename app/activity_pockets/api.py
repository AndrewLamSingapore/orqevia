"""Authenticated standalone management API and reusable ORQEVIA route composition."""

from functools import lru_cache
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .contracts import PocketManifest
from .factory import Factory, Principal
from .store import Store
from .web import Source


def session_principal(request: Request):
    from .. import pwa_sessions

    if request.url.scheme != "https":
        raise HTTPException(426, "HTTPS required")
    # Authenticate the existing persisted session, including when the wider estate is open-access.
    current = pwa_sessions.session(request)
    if current is None:
        raise HTTPException(401, "Existing trusted session required")
    cookies = {request.cookies.get(key) for key in (pwa_sessions.COOKIE, pwa_sessions.ORQEVIA_COOKIE)} - {None, ""}
    if len(cookies) > 1:
        raise HTTPException(401, "Ambiguous session identity")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.getlist("origin")
        expected = urlsplit(str(request.url))
        if len(origin) != 1:
            raise HTTPException(403, "Same-origin mutation required")
        supplied = urlsplit(origin[0])
        if (
            (supplied.scheme, supplied.netloc) != (expected.scheme, expected.netloc)
            or supplied.path
            or supplied.query
            or supplied.fragment
            or supplied.username
        ):
            raise HTTPException(403, "Same-origin mutation required")
    return Principal(current.get("ownerAccountId") or current["clientId"], current["clientId"], current["role"])


@lru_cache(maxsize=1)
def default_factory():
    from ..agent_certification import AgentCertificationRegistry
    from ..agent_cert_azure_es256 import verifier_from_azure_es256_pin_file

    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
    revision = os.getenv("ORQEVIA_RUNTIME_REVISION", "")
    store = Store(root / "activity-pockets.db", revision)
    verifier = None
    if os.getenv("ORQEVIA_AGENT_CERT_AZURE_ES256_ENABLED") == "1":
        pin = Path(
            os.getenv(
                "ORQEVIA_AGENT_CERT_AZURE_ES256_PIN_FILE",
                str(Path(__file__).resolve().parents[2] / "governance" / "agent-cert-verifier-azure-pins.json"),
            )
        )
        pin_hash = os.getenv(
            "ORQEVIA_AGENT_CERT_AZURE_ES256_PIN_SHA256",
            "6cc238c7da9152519410a4cd731abd6e0e584d2cbd84c3c0863ca55b4e771bb0",
        )
        verifier = verifier_from_azure_es256_pin_file(
            pin,
            pin_hash,
            untrusted_roots=(root,),
            normalize_crlf="ORQEVIA_AGENT_CERT_AZURE_ES256_PIN_FILE" not in os.environ,
        )
    qualifications = AgentCertificationRegistry(
        root / "agent-certification", source_revision=revision, verify_record=verifier
    )
    config_path = os.getenv("ORQEVIA_POCKET_SOURCES_FILE")
    config = (
        json.loads(Path(config_path).read_text(encoding="utf-8"))
        if config_path
        else {"schema_version": "1.0", "sources": []}
    )
    if set(config) != {"schema_version", "sources"} or config["schema_version"] != "1.0":
        raise ValueError("unsupported trusted source configuration")
    sources = tuple(
        Source(**{**item, "urls": tuple(item["urls"]), "owners": tuple(item["owners"])}) for item in config["sources"]
    )
    return Factory(store, qualifications, sources)


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    evaluation_id: str
    reason: str = Field(min_length=5, max_length=1000)


class Rollback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: str
    reason: str = Field(min_length=5, max_length=1000)


class Emergency(BaseModel):
    stopped: bool


def build_router(provider=default_factory, authenticate=session_principal):
    def privacy_headers(response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"

    router = APIRouter(
        prefix="/api/activity-pockets", tags=["Activity Pocket Factory"], dependencies=[Depends(privacy_headers)]
    )

    def factory():
        try:
            return provider()
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            raise HTTPException(503, "Factory configuration or persistent storage unavailable") from None

    def invoke(operation):
        try:
            return operation()
        except PermissionError:
            raise HTTPException(403, "Operation outside authenticated pocket authority") from None
        except KeyError:
            raise HTTPException(404, "Owned pocket or evidence unavailable") from None
        except ValueError:
            raise HTTPException(409, "Pocket contract or state conflict") from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, "Factory persistent dependency unavailable") from None

    @router.get("/status")
    def status(principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.health(principal))

    @router.get("/coverage")
    def coverage(principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.coverage(principal))

    @router.get("/tools")
    def tools(principal=Depends(authenticate), service=Depends(factory)):
        return service.tool_manifest(principal)

    @router.get("")
    def pockets(principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.list(principal))

    @router.post("", status_code=201)
    def create(body: PocketManifest, request: Request, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.create(body, principal, request.headers.get("idempotency-key", "")))

    @router.post("/emergency")
    def emergency(body: Emergency, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.emergency_stop(principal, body.stopped))

    @router.get("/{pocket_id}")
    def pocket(pocket_id: str, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.get(pocket_id, principal))

    @router.get("/{pocket_id}/events")
    def events(pocket_id: str, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.events(pocket_id, principal))

    @router.post("/{pocket_id}/execute")
    def run(pocket_id: str, body: Mutation, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.run_one(pocket_id, principal, body.idempotency_key))

    @router.post("/{pocket_id}/promote")
    def promote(pocket_id: str, body: Decision, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.promote(pocket_id, principal, body.proposal_id, body.evaluation_id, body.reason))

    @router.post("/{pocket_id}/rollback")
    def rollback(pocket_id: str, body: Rollback, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.rollback(pocket_id, principal, body.decision_id, body.reason))

    @router.post("/{pocket_id}/revalidate")
    def revalidate(pocket_id: str, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.revalidate(pocket_id, principal))

    @router.post("/{pocket_id}/{action}")
    def transition(pocket_id: str, action: str, principal=Depends(authenticate), service=Depends(factory)):
        return invoke(lambda: service.transition(pocket_id, principal, action))

    return router


def console_router(authenticate=session_principal):
    router = APIRouter()
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    }

    @router.get("/activity-pockets", response_class=HTMLResponse)
    def console(principal=Depends(authenticate)):
        return HTMLResponse(Path(__file__).with_name("console.html").read_text(encoding="utf-8"), headers=headers)

    @router.get("/activity-pockets/app.js")
    def script(principal=Depends(authenticate)):
        return Response(
            Path(__file__).with_name("console.js").read_text(encoding="utf-8"),
            media_type="text/javascript",
            headers=headers,
        )

    return router


def create_app(factory=None, *, authenticate=session_principal, start_worker=True):
    from contextlib import asynccontextmanager
    from .worker import Worker

    provider = (lambda: factory) if factory is not None else default_factory

    @asynccontextmanager
    async def lifespan(application):
        worker = Worker(provider()).start() if start_worker else None
        try:
            yield
        finally:
            if worker:
                worker.stop()

    application = FastAPI(title="Activity Pocket Factory", version="1.0", lifespan=lifespan)
    application.include_router(build_router(provider, authenticate))
    application.include_router(console_router(authenticate))
    from .orqevia import build_router as objective_router

    application.include_router(objective_router(provider, authenticate))
    return application


app = create_app()
