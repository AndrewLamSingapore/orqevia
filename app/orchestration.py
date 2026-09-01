import re
from dataclasses import dataclass

SPECIALISTS = {
    "strategy": {
        "name": "Strategy Specialist",
        "purpose": "Turns objectives into bounded internal strategy, priorities and decision-ready plans.",
        "departments": {"strategy"},
        "keywords": {"strategy", "priority", "objective", "plan", "roadmap", "portfolio", "decision"},
    },
    "research": {
        "name": "Research Specialist",
        "purpose": "Synthesizes supplied evidence and frames research gaps without inventing external evidence.",
        "departments": {"research", "knowledge"},
        "keywords": {"research", "evidence", "source", "market", "compare", "knowledge", "benchmark"},
    },
    "data": {
        "name": "Data Specialist",
        "purpose": "Analyzes only real local datasets explicitly available to PRIME; never invents rows, databases, measurements, users, percentages, locations or behavioral observations.",
        "departments": {"data"},
        "keywords": {"data", "metric", "baseline", "measure", "analysis", "cash flow", "forecast"},
    },
    "engineering": {
        "name": "Engineering Specialist",
        "purpose": "Designs, validates and improves internal technical artifacts within PRIME's existing safety boundary.",
        "departments": {"engineering"},
        "keywords": {"code", "build", "test", "system", "architecture", "engineering", "implement"},
    },
    "quality": {
        "name": "Quality Specialist",
        "purpose": "Critiques, verifies and audits internal outputs for completeness, consistency and unsupported claims.",
        "departments": {"quality"},
        "keywords": {"verify", "audit", "review", "quality", "risk", "contradiction", "validate"},
    },
    "economic": {
        "name": "Economic Specialist",
        "purpose": "Connects objectives to income, cash flow, assets, liabilities, career capital and long-term wealth.",
        "departments": set(),
        "keywords": {"economic", "income", "wealth", "cash flow", "asset", "liability", "monetize", "revenue", "job", "career"},
    },
}

FORBIDDEN_EFFECT_WORDS = {
    "purchase", "buy", "pay", "payment", "transfer", "send email", "send message",
    "publish", "post publicly", "delete", "remove external", "change password", "change account",
    "login", "credential", "withdraw", "trade", "execute transaction",
}

# Phrase variants for consequential actions must not be bypassable by harmless
# filler words (for example, "send an external message" vs "send message").
CONSEQUENTIAL_PATTERNS = (
    re.compile(r"\b(?:send|approve|deploy|execute)\b(?:\s+[a-z0-9_-]+){0,5}\s+\b(?:external|remote|production|public)\b"),
    re.compile(r"\bsend\b(?:\s+[a-z0-9_-]+){0,4}\s+\b(?:email|message)\b"),
    re.compile(r"\b(?:publish|post)\b(?:\s+[a-z0-9_-]+){0,4}\s+\b(?:publicly|online|externally)\b"),
    re.compile(r"\b(?:purchase|buy|pay|transfer|withdraw|trade)\b"),
    re.compile(r"\b(?:delete|remove)\b(?:\s+[a-z0-9_-]+){0,4}\s+\b(?:external|remote|account|data|file|record)\b"),
    re.compile(r"\bchange\b(?:\s+[a-z0-9_-]+){0,3}\s+\b(?:password|account|credential|permissions?)\b"),
    re.compile(r"\b(?:login|log in|sign in)\b"),
    re.compile(r"\bexecute\b(?:\s+[a-z0-9_-]+){0,3}\s+\btransaction\b"),
)

@dataclass(frozen=True)
class RouteDecision:
    specialist: str
    reason: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def choose_specialist(department: str, title: str, description: str) -> RouteDecision:
    dep = _norm(department)
    text = _norm(f"{title} {description}")
    best_key = "strategy"
    best_score = -1
    best_reason = "default bounded strategy routing"
    for key, cfg in SPECIALISTS.items():
        score = 0
        reasons = []
        if dep and dep in cfg["departments"]:
            score += 8
            reasons.append(f"department={department}")
        for kw in cfg["keywords"]:
            if kw in text:
                score += 2 if " " in kw else 1
                reasons.append(kw)
        if score > best_score:
            best_key = key
            best_score = score
            best_reason = ", ".join(reasons[:4]) or "best bounded fit"
    return RouteDecision(best_key, best_reason)


def has_consequential_intent(title: str, description: str) -> bool:
    text = _norm(f"{title} {description}")
    if any(word in text for word in FORBIDDEN_EFFECT_WORDS):
        return True
    return any(pattern.search(text) for pattern in CONSEQUENTIAL_PATTERNS)


def build_task_brief(*, objective_title: str, objective_description: str, project_title: str,
                     department: str, task_title: str, task_description: str,
                     specialist: str, context_summary: str = "", evidence_context: str = "") -> str:
    cfg = SPECIALISTS.get(specialist, SPECIALISTS["strategy"])
    context_block = context_summary.strip()[:5000] if context_summary else "No prior compacted mission context."
    evidence_block = evidence_context.strip()[:14000] if evidence_context else "NO VERIFIED EVIDENCE IS ATTACHED TO THIS MISSION."
    return f"""PRIME INTERNAL MISSION BRIEF

OBJECTIVE
{objective_title}
{objective_description}

PROJECT
{project_title}

MISSION
Department: {department}
Task: {task_title}
Description: {task_description}

SPECIALIST
{cfg['name']}: {cfg['purpose']}

PRIOR COMPACTED CONTEXT
{context_block}

VERIFIED EVIDENCE AVAILABLE TO THIS MISSION
{evidence_block}

EVIDENCE CONTRACT
- Every factual/source-specific claim must be supported by the VERIFIED EVIDENCE block above.
- Never invent a database, file, dataset, user, transaction, percentage, amount, timestamp, location, log, browsing history, tracking signal, observation, source, or tool result.
- If evidence is absent or insufficient, say DATA_REQUIRED or EVIDENCE_REQUIRED and list the exact inputs needed.
- Do not describe analysis as completed if the required underlying data is not present.
- Quantitative conclusions may be calculated only from attached evidence; identify the source dataset by exact name and ID.
- Uncertainty language does NOT make fabricated evidence acceptable.

REQUIRED OUTCOME
Produce a self-contained internal deliverable that directly advances the mission.
Structure it as:
1. Result
2. Evidence actually used (name/ID where applicable)
3. Assumptions and uncertainties
4. Recommended INTERNAL next step

BOUNDARIES
- State WHAT was concluded, not fictional tool use.
- Do not claim external research unless evidence was explicitly supplied to PRIME.
- Do not send, publish, purchase, pay, trade, delete external data, alter accounts, or expand authority.
- If the mission appears to require a consequential external action, stop at an internal recommendation for user approval.
""".strip()


_SOURCE_CLAIM_PATTERNS = [
    r"\bextracted from\b", r"\breview of .*logs?\b", r"\bdatabase\b",
    r"\blocation tracking\b", r"\bbrowsing history\b", r"\btransaction history\b",
    r"\brevealed\b", r"\baccording to\b", r"\bthe data shows\b",
    r"\bthe logs show\b", r"\bwe observed\b", r"\bI observed\b",
]

def grounding_guard(content: str, specialist: str, evidence_context: str) -> tuple[bool, str]:
    """Deterministic first-line defense against unsupported evidence claims."""
    body = (content or "").strip()
    evidence = (evidence_context or "").strip()
    low = body.lower()
    evlow = evidence.lower()

    if not body:
        return False, "Empty deliverable."

    if specialist == "data" and not evidence:
        return False, "DATA_REQUIRED: no verified local dataset was attached to this mission."

    if specialist == "data" and evidence and "source dataset:" not in low:
        return False, "Grounding requirement: identify the source as 'SOURCE DATASET: <name> [<id>]' in the deliverable."

    if not evidence:
        for pat in _SOURCE_CLAIM_PATTERNS:
            if re.search(pat, low):
                return False, "Unsupported source claim detected while no verified evidence was attached."

        # Numbers can be plans/thresholds, so only block explicit empirical phrasing.
        empirical = re.search(
            r"(?:approximately|average|averaged|increased|decreased|reaches|spend|spent|expenses?|transactions?).{0,50}"
            r"(?:[$€£]\s*\d|\b\d+(?:\.\d+)?\s*%)",
            low,
        )
        if empirical:
            return False, "Unsupported quantitative observation detected while no verified evidence was attached."

    # If a named fake source is asserted, it must at least appear in the evidence packet.
    for quoted in re.findall(r"['\"]([^'\"]{3,80})['\"]", body):
        q = quoted.strip().lower()
        if any(k in q for k in ("database", "history", "dataset", "log")) and q not in evlow:
            return False, f"Unsupported named source: {quoted}"

    return True, "Deterministic grounding guard passed."

def compact_context(task_title: str, result: str, score: float, feedback: str) -> str:
    body = re.sub(r"\s+", " ", (result or "").strip())
    fb = re.sub(r"\s+", " ", (feedback or "").strip())
    if len(body) > 1800:
        body = body[:1800].rstrip() + "…"
    if len(fb) > 500:
        fb = fb[:500].rstrip() + "…"
    return f"Mission: {task_title}\nVerified score: {score:.1f}\nOutcome: {body}\nVerifier: {fb}".strip()


def supervisor_status(*, elapsed_seconds: float, attempts: int, max_attempts: int,
                      score: float | None = None, verdict: str | None = None,
                      error: str | None = None) -> tuple[str, str]:
    if error:
        if attempts < max_attempts:
            return "retry", "execution error; retry remains within bounded attempt limit"
        return "failed", "execution error and retry budget exhausted"
    if elapsed_seconds > 900:
        return "failed", "job exceeded 15-minute safety horizon"
    if score is not None and verdict is not None:
        if verdict == "pass":
            return "complete", f"verifier passed at {score:.1f}"
        if attempts < max_attempts:
            return "retry", f"verifier requested revision at {score:.1f}"
        return "needs_review", f"verification remained below threshold after {attempts} attempt(s)"
    return "running", "job remains within bounded execution envelope"
