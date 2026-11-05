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
    ("/trust", "Security"),
    ("/access", "Access"),
)
PAGES = {
    "/": (
        "Overview",
        "THE ORQEVIA WORKSPACE",
        "Useful intelligence.<br><em>Work you can inspect.</em>",
        "Bring reasoning, tools, knowledge and recoverable missions into one workspace. Continue your work on desktop and mobile.",
    ),
    "/intelligence": (
        "Intelligence",
        "REASONING, TOOLS AND KNOWLEDGE",
        "A clear path<br><em>from intent to evidence.</em>",
        "Start with an objective. Use available models and tools, retrieve relevant knowledge and inspect the evidence behind a result.",
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
        "One workspace.<br><em>Direct execution.</em>",
        "One logical coordination path selects relevant capabilities, tools and models. Durable task records preserve progress while measured resource limits protect useful work.",
    ),
    "/trust": (
        "Security",
        "PRIVATE BY DEFAULT",
        "Private work.<br><em>Clear permissions.</em>",
        "Authenticated sessions, scoped permissions and isolated credentials protect private work. Spending and consequential external actions keep their own technical authorization boundaries.",
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
        "From an objective to useful work.",
        "Choose an outcome, use the capabilities you need and keep the resulting work and evidence together.",
        (
            (
                "Ground the answer",
                "Work with source-attributed document retrieval and distinguish retrieved evidence from generated interpretation.",
            ),
            (
                "Run the mission",
                "Submit authorized objectives directly. The runtime selects available models and tools within the task permissions and measured resource capacity.",
            ),
            (
                "Inspect the result",
                "Follow task state and inspect original evidence. Registered agents, recent activity and qualified capability remain distinct.",
            ),
        ),
    ),
    "/intelligence": (
        "Choose the right capability for the task.",
        "Explore available capabilities in one workspace. Installed models, configured providers and demonstrated execution are shown separately.",
        (
            (
                "Model intelligence",
                "Inspect model locality and availability. Routing respects task privacy, cost and measured resource capacity.",
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
                "Live systems",
                "Inspect operational observations, model activity and resource usage. Read access never grants control of a system.",
            ),
        ),
    ),
    "/architecture": (
        "Fewer steps between intent and results.",
        "Local models, task state and knowledge stay with their owning services. External integrations report their own availability.",
        (
            ("Shared interfaces", "Desktop and iPhone use the same authorized workspace and service contracts."),
            (
                "One execution path",
                "Capabilities share direct task dispatch, recoverable execution records and narrowly scoped permission checks. No agent hierarchy is needed for ordinary work.",
            ),
            (
                "Inspectable outcomes",
                "Execution records, provenance and evidence remain attached to their original service and task.",
            ),
        ),
    ),
    "/trust": (
        "Technical boundaries that protect your work.",
        "A successful page load, registered agent or passing unit test is never a claim of general production certification.",
        (
            (
                "Identity & scope",
                "Server-issued identity and scoped roles protect private functionality. Public content grants no privileged access.",
            ),
            (
                "Consequential decisions",
                "Financial transfers, credential changes and consequential external actions require the permissions for that exact operation. Routine authorized work runs directly.",
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
        content += '<section class="editorial"><div class="editorial-heading"><h2>Every step leaves<br>a trace.</h2><p>Conceptual workflow. Available tools and models execute authorized tasks; unavailable capabilities remain explicit.</p></div><ol class="flow"><li>Objective</li><li>Tools &amp; models</li><li>Execution</li><li>Evidence</li><li>Result</li></ol><p class="disclosure">Model-generated output requires verification. ORQEVIA makes no claim of proven AGI or ASI. Capability and certification records are scoped to their actual evidence.</p></section>'
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
