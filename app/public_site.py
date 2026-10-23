"""Static public product content. No runtime configuration or private data enters it."""

from html import escape
import os
from pathlib import Path
from string import Template

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter()
CLIENTS = Path(__file__).resolve().parent.parent / "clients"
PUBLIC = CLIENTS / "public" if (CLIENTS / "public").is_dir() else Path(__file__).with_name("public_static")
SHARED = CLIENTS / "shared" if (CLIENTS / "shared").is_dir() else Path(__file__).with_name("shared_static")
NAV = (
    ("/", "Overview"),
    ("/intelligence", "Intelligence"),
    ("/capabilities", "Capabilities"),
    ("/architecture", "Architecture"),
    ("/trust", "Trust & Governance"),
    ("/access", "Access"),
)
PAGES = {
    "/": (
        "Overview",
        "INTELLIGENCE, WITH INTENTION",
        "Intelligence.<br><em>Under your authority.</em>",
        "A sovereign workspace for grounded reasoning, governed agents and work you can inspect. One continuous experience, from desktop to iPhone.",
    ),
    "/intelligence": (
        "Intelligence",
        "THE SOVEREIGN INTELLIGENCE PLANE",
        "A clear path<br><em>from intent to evidence.</em>",
        "Bring objectives, documents and reasoning into one accountable workflow. Inspect the sources, routing and execution records behind a result.",
    ),
    "/capabilities": (
        "Capabilities",
        "PURPOSEFUL BY DESIGN",
        "Useful work.<br><em>Visible boundaries.</em>",
        "Reason over documents, submit bounded objectives, inspect task progress and retrieve original evidence. Availability and limitations stay explicit.",
    ),
    "/architecture": (
        "Architecture",
        "ONE COHERENT SYSTEM",
        "Connected thinking.<br><em>Preserved authority.</em>",
        "A shared workspace and API connect to existing governance, model routing, orchestration and evidence. The intelligence plane adds coordination within these boundaries.",
    ),
    "/trust": (
        "Trust & Governance",
        "CONFIDENCE MUST BE EARNED",
        "Trust is a practice.<br><em>Evidence is the record.</em>",
        "Authentication, scoped access and existing approval controls define what can happen. Execution evidence defines what actually happened.",
    ),
    "/access": (
        "Access",
        "YOUR PRIVATE WORKSPACE",
        "One workspace.<br><em>Wherever you think.</em>",
        "Enter ORQEVIA on desktop or iPhone. A trusted device restores its valid session. A new or revoked device establishes trust through the existing owner enrollment flow.",
    ),
}
FEATURES = {
    "/": (
        "From a question to accountable work.",
        "A useful intelligence platform makes its reasoning context and operational limits inspectable.",
        (
            (
                "Ground the answer",
                "Work with source-attributed document retrieval and distinguish retrieved evidence from generated interpretation.",
            ),
            (
                "Govern the action",
                "Submit bounded objectives through the existing authenticated execution path, with the same ownership and resource controls.",
            ),
            (
                "Inspect the result",
                "Follow task state and inspect original evidence. Registered agents, recent activity and qualified capability remain distinct.",
            ),
        ),
    ),
    "/intelligence": (
        "Coordination within proven boundaries.",
        "OSIP brings existing components into one authorized view. Provider configuration is separate from live inference qualification.",
        (
            (
                "Model intelligence",
                "Inspect configured roles, locality and model availability. Routing retains the existing classification, cost and resource limits.",
            ),
            (
                "Grounded reasoning",
                "Retrieve provenance-bearing knowledge, plan bounded work and verify outcomes against the original execution record.",
            ),
            (
                "Durable continuity",
                "Task records and trusted sessions persist on the server. Stored memory remains subject to its existing account and retention boundaries.",
            ),
        ),
    ),
    "/capabilities": (
        "A workspace with a purpose for every control.",
        "Connected capabilities share the existing identity and API. Unavailable services report their state explicitly.",
        (
            (
                "Objectives & evidence",
                "Submit work, follow owned task progress and download integrity-bound artifacts from the original execution.",
            ),
            (
                "Document intelligence",
                "Ingest supported documents and retrieve attributed context through the existing owner-scoped knowledge service.",
            ),
            (
                "Read-only observatory",
                "Inspect available operational observations in GOD’S EYE. Observation never grants execution authority.",
            ),
        ),
    ),
    "/architecture": (
        "A continuous chain of accountability.",
        "Product sovereignty is preserved. ORQEVIA does not require the other portfolio products to operate.",
        (
            ("Shared interfaces", "Desktop and iPhone use the same authorized workspace and service contracts."),
            (
                "Stable governance",
                "The existing Stable Spine, capability registry and execution boundaries remain the governing mechanisms.",
            ),
            (
                "Inspectable outcomes",
                "Execution records, provenance and evidence remain attached to their original service and task.",
            ),
        ),
    ),
    "/trust": (
        "Governance is part of the execution path.",
        "A successful page load, registered agent or passing unit test is never a claim of general production certification.",
        (
            (
                "Identity & scope",
                "Server-issued identity and scoped roles protect private functionality. Public content grants no privileged access.",
            ),
            (
                "Consequential decisions",
                "Existing approval requirements remain in force. A recorded approval does not by itself establish successful execution.",
            ),
            (
                "Honest availability",
                "Unknown, stale, offline and unavailable observations remain visible. Metrics and capabilities are never invented.",
            ),
        ),
    ),
    "/access": (
        "Start once. Continue with context.",
        "The public website and private workspace have distinct roles. Private data is loaded only after backend authorization.",
        (
            (
                "Existing device",
                "Open the workspace. Valid trusted-device credentials restore the session in the background.",
            ),
            (
                "New device",
                "Use the enrollment code from your existing owner workflow. Codes and credentials never belong in public links.",
            ),
            (
                "iPhone installation",
                "Open the trusted HTTPS workspace in Safari and use Add to Home Screen. Physical-device acceptance is separate from browser emulation.",
            ),
        ),
    ),
}


def render(path: str) -> str:
    title, eyebrow, heading, intro = PAGES[path]
    section_title, section_intro, features = FEATURES[path]
    cards = "".join(
        f'<article class="capability"><span class="capability-number">0{i}</span><h3>{escape(name)}</h3><p>{escape(text)}</p></article>'
        for i, (name, text) in enumerate(features, 1)
    )
    content = f'<section class="editorial"><div class="editorial-heading"><h2>{escape(section_title)}</h2><p>{escape(section_intro)}</p></div><div class="capability-list">{cards}</div></section>'
    if path in {"/", "/architecture", "/intelligence"}:
        content += '<section class="editorial"><div class="editorial-heading"><h2>Every step leaves<br>a trace.</h2><p>Conceptual workflow. Each service retains its own authority; an unavailable step stays unavailable.</p></div><ol class="flow"><li>Intent</li><li>Governance</li><li>Reasoning</li><li>Evidence</li><li>Observation</li></ol><p class="disclosure">Model-generated output requires verification. ORQEVIA makes no claim of proven AGI or ASI. Capability and certification records are scoped to their actual evidence.</p></section>'
    navigation = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if path == url else "") + f">{escape(label)}</a>"
        for url, label in NAV
    )
    robots = (
        "noindex,nofollow"
        if os.getenv("ORQEVIA_INTERFACE_CANDIDATE_STATUS") == "ISOLATED_CANDIDATE"
        else "index,follow"
    )
    return Template((PUBLIC / "page.html").read_text(encoding="utf-8")).substitute(
        title=escape(title),
        description=escape(intro, quote=True),
        eyebrow=escape(eyebrow),
        heading=heading,
        intro=escape(intro),
        navigation=navigation,
        content=content,
        robots=robots,
    )


@router.get("/robots.txt", include_in_schema=False)
def robots():
    candidate = os.getenv("ORQEVIA_INTERFACE_CANDIDATE_STATUS") == "ISOLATED_CANDIDATE"
    return PlainTextResponse(
        "User-agent: *\nDisallow: /\n"
        if candidate
        else "User-agent: *\nAllow: /\nDisallow: /pwa/\nDisallow: /interface/\nDisallow: /api/\n"
    )


async def public_page(request: Request):
    return HTMLResponse(
        render(request.url.path),
        headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


for _path in PAGES:
    router.add_api_route(_path, public_page, methods=["GET"], include_in_schema=False)
