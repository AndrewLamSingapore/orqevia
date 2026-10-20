"""Execute ORQ-001 through the live ORQEVIA compute queue.

This script runs inside the ORQEVIA backend container. It does not fabricate
agent output: every contribution below is requested as a governed queue job and
recorded with its job ID, timestamps, model, provider, token usage and hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.agent_registry import load_agent_registry
from app.agent_runtime import AgentAuthorityRuntime

PROJECT_ID = "ORQ-001"
BASE_URL = os.getenv("ORQ001_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUTPUT = Path(os.getenv("ORQ001_OUTPUT", "/data/orq-001"))
STATE_PATH = OUTPUT / "orq-001-run-state.json"
TOKEN = (os.getenv("ORQEVIA_SPINE_TOKEN") or os.getenv("PRIME_SPINE_TOKEN") or "").strip()
SOURCE_REVISION = (
    os.getenv("ORQEVIA_RUNTIME_REVISION")
    or os.getenv("PRIME_RUNTIME_REVISION")
    or os.getenv("ORQEVIA_INTERFACE_RUNTIME_REVISION")
    or "UNKNOWN"
)
IMAGE_DIGEST = os.getenv("ORQEVIA_RUNTIME_IMAGE_DIGEST") or os.getenv("PRIME_RUNTIME_IMAGE_DIGEST") or "UNKNOWN"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def margin(profit: Decimal, revenue: Decimal) -> Decimal:
    return (profit / revenue * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def request(path: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = BASE_URL
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else None


def financial_model() -> dict[str, Any]:
    revenue = Decimal("50000")
    rent = Decimal("8000")
    salaries = Decimal("18000")
    inventory = Decimal("12000")
    utilities = Decimal("2000")
    marketing = Decimal("3000")
    other = Decimal("2000")
    expense_lines = {
        "rent": rent,
        "salaries": salaries,
        "inventory": inventory,
        "utilities": utilities,
        "marketing": marketing,
        "other_expenses": other,
    }
    total_expenses = sum(expense_lines.values(), Decimal("0"))
    profit = revenue - total_expenses

    inventory_saving = inventory * Decimal("0.10")
    s1_expenses = total_expenses - inventory_saving
    s1_profit = revenue - s1_expenses

    marketing_spend = marketing * Decimal("1.20")
    marketing_increase = marketing_spend - marketing
    scenario_revenue = revenue * Decimal("1.08")
    variable_inventory_rate = inventory / revenue
    inventory_after_growth = scenario_revenue * variable_inventory_rate
    s2_expenses = (
        rent + salaries + inventory_after_growth + utilities + marketing_spend + other
    )
    s2_profit = scenario_revenue - s2_expenses

    s3_inventory = inventory_after_growth * Decimal("0.90")
    s3_expenses = rent + salaries + s3_inventory + utilities + marketing_spend + other
    s3_profit = scenario_revenue - s3_expenses

    scenarios_raw = [
        {
            "scenario_id": "S1",
            "name": "Reduce inventory consumption by 10%",
            "inputs": {
                "inventory_reduction_percent": 10,
                "revenue_change_percent": 0,
                "marketing_change_percent": 0,
            },
            "cost_changes": {"inventory": -inventory_saving},
            "revenue": revenue,
            "total_expenses": s1_expenses,
            "monthly_profit": s1_profit,
            "profit_change": s1_profit - profit,
            "net_margin_percent": margin(s1_profit, revenue),
            "assumptions": [
                "The 10% inventory reduction is achieved through supplier negotiations and tighter stock control.",
                "The reduction does not reduce sales volume or service quality.",
                "Any one-off negotiation or training cost is excluded and must be approved separately.",
            ],
            "risks": ["Stock-outs", "Supplier resistance", "Quality compromise", "Short-term purchasing disruption"],
        },
        {
            "scenario_id": "S2",
            "name": "Increase marketing by 20% for an 8% revenue lift",
            "inputs": {
                "inventory_reduction_percent": 0,
                "revenue_change_percent": 8,
                "marketing_change_percent": 20,
            },
            "cost_changes": {
                "marketing": marketing_increase,
                "inventory": inventory_after_growth - inventory,
            },
            "revenue": scenario_revenue,
            "total_expenses": s2_expenses,
            "monthly_profit": s2_profit,
            "profit_change": s2_profit - profit,
            "net_margin_percent": margin(s2_profit, scenario_revenue),
            "assumptions": [
                "The 8% revenue lift is achieved within the monthly cycle after spending SGD 600 more on marketing.",
                "Inventory remains variable at 24% of revenue.",
                "Rent, salaries, utilities and other expenses remain unchanged.",
                "No one-off creative, platform or discount cost is included.",
            ],
            "risks": ["Marketing response below forecast", "Cash concentration in one channel", "Rising acquisition cost", "Inventory mismatch"],
        },
        {
            "scenario_id": "S3",
            "name": "Combine supplier savings with the measured marketing uplift",
            "inputs": {
                "inventory_reduction_percent": 10,
                "revenue_change_percent": 8,
                "marketing_change_percent": 20,
            },
            "cost_changes": {
                "marketing": marketing_increase,
                "inventory": s3_inventory - inventory,
            },
            "revenue": scenario_revenue,
            "total_expenses": s3_expenses,
            "monthly_profit": s3_profit,
            "profit_change": s3_profit - profit,
            "net_margin_percent": margin(s3_profit, scenario_revenue),
            "assumptions": [
                "The supplier saving applies to the higher post-growth inventory requirement.",
                "The marketing response and supplier saving can both be implemented without a material one-off cost.",
                "Inventory remains variable at 24% of revenue before the negotiated reduction.",
                "All scenario cash is compared pre-tax and before owner drawings or financing costs.",
            ],
            "risks": [
                "Concurrent execution may overstretch management attention",
                "Revenue lift may arrive before supplier savings",
                "Cash may be tied up in additional stock",
                "Marketing and inventory assumptions may be optimistic",
            ],
        },
    ]
    for scenario in scenarios_raw:
        scenario["annualized_profit_change"] = money(Decimal(str(scenario["profit_change"])) * 12)
        for key in (
            "revenue",
            "total_expenses",
            "monthly_profit",
            "profit_change",
            "net_margin_percent",
        ):
            scenario[key] = money(Decimal(str(scenario[key])))
        scenario["cost_changes"] = {key: money(Decimal(str(value))) for key, value in scenario["cost_changes"].items()}

    ranking = sorted(scenarios_raw, key=lambda item: item["monthly_profit"], reverse=True)
    return {
        "schema_version": "orqevia.orq-001-results.v1",
        "project_id": PROJECT_ID,
        "title": "Fictional Singapore SME monthly profitability analysis",
        "generated_at": utcnow(),
        "currency": "SGD",
        "period": "one hypothetical month",
        "status": "CALCULATED_PENDING_FINAL_VERIFICATION",
        "assumptions": [
            "The business, figures and outcomes are hypothetical.",
            "No external market, supplier, tax or accounting data was used.",
            "Inventory is treated as monthly cost of goods consumed at 24% of revenue.",
            "Rent, salaries, utilities and other expenses are fixed for these scenarios.",
            "Figures are pre-tax and before owner drawings, financing, depreciation and one-off costs.",
            "Percentage comparisons use the revenue shown for the relevant scenario.",
        ],
        "baseline": {
            "revenue": money(revenue),
            "expense_lines": {key: money(value) for key, value in expense_lines.items()},
            "total_expenses": money(total_expenses),
            "monthly_profit": money(profit),
            "net_margin_percent": money(margin(profit, revenue)),
            "formulas": {
                "total_expenses": "rent + salaries + inventory + utilities + marketing + other_expenses",
                "monthly_profit": "revenue - total_expenses",
                "net_margin_percent": "monthly_profit / revenue * 100",
            },
        },
        "scenarios": scenarios_raw,
        "ranking": [item["scenario_id"] for item in ranking],
        "recommendation": {
            "priority": "S3",
            "label": "Pursue the combined programme with staged gates",
            "monthly_profit": ranking[0]["monthly_profit"],
            "net_margin_percent": ranking[0]["net_margin_percent"],
            "rationale": (
                "S3 has the strongest modelled monthly and annual profit impact. Sequence S1 first "
                "to secure the low-cost supplier improvement, then run S2 as a measured 60-day "
                "marketing experiment. Continue only if the revenue and contribution-margin gates pass."
            ),
            "stage_gates": [
                "Secure a documented 10% inventory saving before increasing committed stock.",
                "Run the SGD 600 incremental marketing test with weekly channel-level measurement.",
                "Continue the marketing expansion only if incremental gross profit exceeds incremental marketing spend by at least 1.5x.",
                "Stop or reset if inventory days rise above the approved ceiling, stock-outs increase, or realized revenue lift is below 5% at day 60.",
            ],
        },
        "sensitivities": [
            {
                "scenario_id": "S2",
                "case": "No measurable revenue lift",
                "monthly_profit": money(profit - marketing_increase),
                "note": "The extra SGD 600 marketing spend directly reduces profit.",
            },
            {
                "scenario_id": "S2",
                "case": "Revenue lift limited to 4%",
                "monthly_profit": money(
                    Decimal("52000")
                    - (rent + salaries + Decimal("52000") * variable_inventory_rate + utilities + marketing_spend + other)
                ),
                "note": "A weaker response still produces modest profit improvement.",
            },
            {
                "scenario_id": "S3",
                "case": "Supplier saving limited to 5%",
                "monthly_profit": money(
                    scenario_revenue
                    - (rent + salaries + inventory_after_growth * Decimal("0.95") + utilities + marketing_spend + other)
                ),
                "note": "The combined programme retains an advantage over the baseline but loses part of the S1 benefit.",
            },
        ],
        "validation": {
            "total_expenses_expected_sgd": 45000,
            "monthly_profit_expected_sgd": 5000,
            "net_margin_expected_percent": 10,
            "status": "PENDING_INDEPENDENT_VERIFICATION",
        },
    }


TASKS: dict[str, dict[str, str]] = {
    "a01": {
        "responsibility": "Strategy leadership and priority setting",
        "task": "Evaluate S1, S2 and S3. Recommend the strongest path, state why, and give two explicit stage gates. Do not invent market data.",
    },
    "a02": {
        "responsibility": "Project plan, dependencies and milestones",
        "task": "Create a six-week implementation sequence for the recommended S3 path. State dependencies, owners from the listed registered agents, and measurable acceptance gates.",
    },
    "a04": {
        "responsibility": "Structured scenario comparison",
        "task": "Compare S1, S2 and S3 on monthly profit, margin and downside risk. State which is strongest and whether disagreement or escalation is required.",
    },
    "a05": {
        "responsibility": "Capacity and portfolio prioritization",
        "task": "Assess whether the hypothetical SME can run S3 within existing capacity. Identify one capacity constraint and one sequencing safeguard.",
    },
    "a06": {
        "responsibility": "Research assumptions and evidence direction",
        "task": "Define the evidence that would be required before converting these hypothetical scenarios into real business commitments. Keep the hypothetical label explicit.",
    },
    "a07": {
        "responsibility": "Evidence attribution",
        "task": "Audit the supplied figures conceptually. State which values are provided assumptions, which are derived, and what evidence is missing for real-world use.",
    },
    "a09": {
        "responsibility": "Knowledge organization",
        "task": "Propose a concise report structure for the business owner, including baseline, scenarios, recommendation, risks, verification and evidence appendix.",
    },
    "a10": {
        "responsibility": "Data completeness and data dictionary",
        "task": "Check whether the supplied monthly data is complete enough for the baseline calculation. List required units and the one missing real-world field that would most improve the analysis.",
    },
    "a12": {
        "responsibility": "Independent financial calculation",
        "task": "Using the six supplied expense lines, calculate total monthly expenses, monthly profit and net margin. Show the arithmetic and compare with SGD 45,000, SGD 5,000 and 10%.",
    },
    "a13": {
        "responsibility": "Forecast sensitivity",
        "task": "Assess the 8% revenue and 10% inventory-saving assumptions. Give one plausible downside case and explain how it changes the recommendation.",
    },
    "a14": {
        "responsibility": "Data quality and arithmetic verification",
        "task": "Check units, arithmetic, percentage denominators and rounding for the baseline. Return PASS or FAIL for each with a short reason.",
    },
    "a15": {
        "responsibility": "Technical execution ownership",
        "task": "Define operational controls for a staged inventory and marketing programme. Include monitoring cadence, stop conditions and evidence to retain.",
    },
    "a16": {
        "responsibility": "Architecture and durable evidence design",
        "task": "Design the minimum durable artifact and evidence structure for this project. Explain how calculations, agent jobs, handoffs and the saved decision remain auditable.",
    },
    "a17": {
        "responsibility": "Machine-readable implementation",
        "task": "Specify the essential fields and invariants for a machine-readable financial results file so a reviewer can reproduce totals and compare scenarios.",
    },
    "a18": {
        "responsibility": "Test and verification plan",
        "task": "Write exact acceptance tests for baseline arithmetic, scenario reproducibility, JSON cross-file consistency, all-21-agent evidence and memory retrieval.",
    },
    "a19": {
        "responsibility": "Reliability and restart recovery",
        "task": "Define a safe test proving a saved project decision survives a backend process restart, including evidence before and after restart and failure handling.",
    },
    "a20": {
        "responsibility": "Commercial and economic judgment",
        "task": "Give the commercial judgement on S3 versus S1 and S2. Identify the most important cash or operating constraint and the preferred implementation order.",
    },
    "a21": {
        "responsibility": "Cost, value and ROI",
        "task": "Rank S1, S2 and S3 by incremental monthly and annual profit. State the key assumption behind each ranking and one downside risk.",
    },
    "a26": {
        "responsibility": "Independent quality review",
        "task": "Perform an independent quality review of the completed analysis package. Check whether the baseline and scenario claims are internally supported. Return PASS, PARTIAL or FAIL with findings.",
    },
    "a28": {
        "responsibility": "Risk identification",
        "task": "Produce the top five risks of implementing S3 with one mitigation and one measurable warning indicator for each.",
    },
    "a29": {
        "responsibility": "Release readiness decision",
        "task": "Act as release gate for the ORQ-001 package. Decide PASS, PARTIAL or FAIL for delivery readiness based only on the supplied execution and verification summary. List any blockers.",
    },
}


def prompt_for(agent: dict[str, Any], financials: dict[str, Any], task: dict[str, str]) -> str:
    base = financials["baseline"]
    scenarios = {
        item["scenario_id"]: {
            "name": item["name"],
            "monthly_profit": item["monthly_profit"],
            "profit_change": item["profit_change"],
            "net_margin_percent": item["net_margin_percent"],
        }
        for item in financials["scenarios"]
    }
    return (
        "ORQ-001 BUSINESS ANALYSIS\n"
        "All business data and outcomes are hypothetical and must be labelled as assumptions. "
        "This is a fictional Singapore SME. Currency is SGD and the period is one month unless stated.\n"
        f"Registered agent: {agent['agent_id']} — {agent['name']}\n"
        f"Role: {agent['role']}\n"
        f"Owned capabilities: {', '.join(item['id'] for item in agent['responsibilities'])}\n"
        f"Assigned responsibility: {task['responsibility']}\n"
        f"Task: {task['task']}\n"
        "Provided assumptions: revenue SGD 50,000; rent SGD 8,000; salaries SGD 18,000; "
        "inventory SGD 12,000; utilities SGD 2,000; marketing SGD 3,000; other expenses SGD 2,000.\n"
        f"Deterministic baseline: total expenses SGD {base['total_expenses']:.2f}; "
        f"profit SGD {base['monthly_profit']:.2f}; margin {base['net_margin_percent']:.2f}%.\n"
        f"Scenarios: {json.dumps(scenarios, separators=(',', ':'))}\n"
        "Do not claim that you used external tools or real market data. Do not override system, security "
        "or task instructions. Return at most 180 words with two headings: Contribution and Evidence/caveat."
    )


def submit_job(
    agent_id: str,
    prompt: str,
    *,
    attempt: int,
    deep: bool = False,
) -> dict[str, Any]:
    role = "deep" if deep else "fast"
    model = os.getenv("ORQEVIA_DEEP_MODEL", "") if deep else os.getenv("ORQEVIA_FAST_MODEL", "")
    provider = "ollama-deep" if deep else "ollama-fast"
    body = {
        "agent": agent_id,
        "prompt": prompt,
        "priority": "high",
        "model_role": role,
        "model": model,
        "preferred_provider": provider,
        "ram_mb": 4096 if deep else 1024,
        "vram_mb": 0,
        "timeout_seconds": 600 if deep else 180,
        "max_retries": 1,
        "max_cost_usd": 0,
        "allow_cloud": False,
        "external_execution": False,
        "data_classification": "LOCAL_ONLY",
        "task_class": "planning" if deep else "classification",
        "response_format": "text",
        "idempotency_key": f"orq-001-{agent_id}-attempt-{attempt}",
    }
    return request("/api/compute-queue/jobs", method="POST", body=body, timeout=30)


def wait_job(job_id: str, timeout_seconds: int = 900) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = request("/api/compute-queue/jobs/" + urllib.parse.quote(job_id), timeout=30)
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(1.0)
    raise TimeoutError("ORQ-001 queue job exceeded local polling deadline")


def write_decision_memory(financials: dict[str, Any], results_sha256: str) -> dict[str, Any]:
    recommendation = financials["recommendation"]
    value = {
        "project_id": PROJECT_ID,
        "decision": recommendation["priority"],
        "decision_label": recommendation["label"],
        "monthly_profit_sgd": recommendation["monthly_profit"],
        "net_margin_percent": recommendation["net_margin_percent"],
        "results_sha256": results_sha256,
        "hypothetical": True,
        "recorded_at": utcnow(),
    }
    response = request(
        "/control/api/survival/memory",
        method="POST",
        body={"memory_class": "semantic", "key": "ORQ-001.project-decision", "value": value, "confidence": 1.0},
        timeout=30,
    )
    expected = {**response.get("value", {}).get("record", {})}
    return {
        "write_response": response,
        "expected_record": expected or value,
        "memory_key": "ORQ-001.project-decision",
        "memory_class": "semantic",
    }


def build_report(financials: dict[str, Any], matrix: dict[str, Any], log: dict[str, Any]) -> str:
    baseline = financials["baseline"]
    scenarios = financials["scenarios"]
    successes = sum(1 for item in matrix["agents"] if item["execution"]["status"] == "completed")
    handoffs = sum(1 for item in log["handoffs"] if item.get("allowed"))
    rows = [
        "| Scenario | Monthly profit | Change vs baseline | Net margin | Annualized change |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in scenarios:
        rows.append(
            f"| {item['scenario_id']} — {item['name']} | SGD {item['monthly_profit']:,.2f} | "
            f"SGD {item['profit_change']:,.2f} | {item['net_margin_percent']:.2f}% | "
            f"SGD {item['annualized_profit_change']:,.2f} |"
        )
    contribution_rows = [
        "| Agent | Role | Queue job | Status | Contribution or verification |",
        "|---|---|---|---|---|",
    ]
    for item in matrix["agents"]:
        excerpt = " ".join(item["execution"].get("result", "").split())[:260].replace("|", "/")
        contribution_rows.append(
            f"| {item['agent_id']} | {item['name']} | `{item['execution']['job_id']}` | "
            f"{item['execution']['status']} | {excerpt} |"
        )
    return f"""# ORQ-001 — Hypothetical Singapore SME Profitability Review

**Project:** ORQ-001  
**Status:** Generated from actual ORQEVIA queue executions; final independent verification is recorded separately.  
**Currency and period:** SGD per hypothetical month  
**Classification:** Fictional, hypothesis-only business analysis. No external business data was used.

## Executive summary

The hypothetical business earns **SGD {baseline['monthly_profit']:,.2f}** monthly on **SGD {baseline['revenue']:,.2f}** revenue after **SGD {baseline['total_expenses']:,.2f}** of expenses, for a **{baseline['net_margin_percent']:.2f}%** net margin.

The strongest modelled option is **S3**, a staged combination of a 10% inventory-cost reduction and a measured 20% marketing increase intended to produce an 8% revenue lift. It produces modelled monthly profit of **SGD {scenarios[2]['monthly_profit']:,.2f}** and a **{scenarios[2]['net_margin_percent']:.2f}%** net margin, but it carries execution and forecast risk and should not be launched as an uncontrolled change.

## Hypothetical assumptions

- The business, figures and outcomes are fictional and supplied for ORQ-001 only.
- Rent, salaries, utilities and other expenses are fixed for the analysis.
- Inventory is treated as monthly cost of goods consumed at 24% of revenue; it is not assumed to be idle stock.
- Scenario results exclude tax, financing, depreciation, owner drawings and one-off implementation costs.
- The 8% revenue response, the 10% supplier saving and the absence of material disruption are planning assumptions, not forecasts from external evidence.

## Baseline

| Line | SGD/month |
|---|---:|
| Revenue | {baseline['revenue']:,.2f} |
| Rent | {baseline['expense_lines']['rent']:,.2f} |
| Salaries | {baseline['expense_lines']['salaries']:,.2f} |
| Inventory | {baseline['expense_lines']['inventory']:,.2f} |
| Utilities | {baseline['expense_lines']['utilities']:,.2f} |
| Marketing | {baseline['expense_lines']['marketing']:,.2f} |
| Other expenses | {baseline['expense_lines']['other_expenses']:,.2f} |
| **Total expenses** | **{baseline['total_expenses']:,.2f}** |
| **Profit** | **{baseline['monthly_profit']:,.2f}** |
| **Net margin** | **{baseline['net_margin_percent']:.2f}%** |

Arithmetic: total expenses = 8,000 + 18,000 + 12,000 + 2,000 + 3,000 + 2,000 = **SGD 45,000**. Profit = 50,000 − 45,000 = **SGD 5,000**. Net margin = 5,000 ÷ 50,000 = **10.00%**.

## Scenario evaluation

{os.linesep.join(rows)}

The calculations are deterministic and recorded in `ORQ-001-results.json`. S3 ranks first, S2 second and S1 third by modelled monthly profit. S1 is the lowest-risk first step; S2 depends on marketing response; S3 requires both to work together.

## Recommendation

**Prioritize S3 as a staged programme, not as a simultaneous irreversible change.**

1. **Weeks 1–2 — Secure S1:** negotiate a documented 10% inventory saving and set stock and service-level controls.
2. **Weeks 3–8 — Test S2:** spend the incremental SGD 600 on one measurable marketing test, tracking contribution gross profit rather than revenue alone.
3. **Gate to continue:** require incremental gross profit of at least 1.5× incremental marketing spend and a realized revenue lift of at least 5% by day 60.
4. **Stop conditions:** stop or reset if stock-outs rise, inventory days breach the approved ceiling, cash tightens, or acquisition cost invalidates the contribution margin.

This preserves the stronger upside of S3 while using S1 as a low-risk foundation. It also provides an explicit disagreement path: if the marketing gate fails, retain S1, reverse the incremental marketing spend and escalate the revised forecast.

## Six-week action plan

| Week | Work | Owner | Dependency | Acceptance criterion |
|---|---|---|---|---|
| 1 | Supplier and stock review | A20/A21 | Baseline approval | Documented saving and no loss of required stock availability |
| 2 | Marketing measurement design | A06/A12 | S1 terms | Channel, baseline, attribution and stop thresholds defined |
| 2 | Durable evidence setup | A15/A16 | Registry and storage available | Results, jobs, handoffs and decision have auditable references |
| 3 | Controlled marketing test | A15/A20 | Measurement design | Spend never exceeds SGD 600 incremental without approval |
| 4 | Weekly financial review | A12/A14 | Actual test data | Profit, margin and inventory variance reconciled |
| 5 | Risk and recovery review | A19/A28 | Execution evidence | Restart test and risk thresholds pass |
| 6 | Independent release review | A26/A29 | All evidence assembled | PASS only if financial, execution and memory checks pass |

## Risks and controls

| Risk | Mitigation | Warning indicator |
|---|---|---|
| Supplier cannot sustain the saving | Written terms and alternate quote | Saving below 5% or quality issues |
| Marketing response is weak | Bounded pilot and weekly measurement | Revenue lift below 5% at day 60 |
| Extra stock consumes cash | Order only to measured demand | Inventory days exceed approved limit |
| Model or file inconsistency | Independent deterministic recalculation | Any cross-file mismatch |
| Memory or process failure | Durable write, restart test and evidence hash | Missing or mismatched saved decision |
| Agent execution failure | Recorded job status and explicit retry | Any non-completed required job |

## Agent participation and execution evidence

{successes} of 21 registered agents produced non-empty completed queue results. The retained execution log records {handoffs} allowed registry-valid handoffs. Every listed job has a live queue identifier, provider, model, timestamps, result hash and token counts in `ORQ-001-execution-log.json`; this report does not infer participation from registry membership.

{os.linesep.join(contribution_rows)}

## Evidence and limits

- The model-generated contributions are advisory text. Financial truth is independently calculated with decimal arithmetic.
- No external market evidence, supplier quote, tax treatment, cash-flow statement or actual SME records were supplied.
- Scenario results are hypotheses and should be reforecast after any real pilot.
- The definitive acceptance result and any failed checks are in `ORQ-001-verification.md`; the project must not be called PASS if that file records a critical failure.
"""


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if not TOKEN:
        raise RuntimeError("ORQEVIA service token is not configured")
    started_at = utcnow()
    registry = load_agent_registry()
    agents = list(registry["agents"])
    if len(agents) != 21:
        raise RuntimeError(f"expected 21 registered agents, found {len(agents)}")
    financials = financial_model()
    provider_health = request("/api/compute-queue/providers/health", timeout=30)
    queue_metrics = request("/api/compute-queue/metrics", timeout=30)
    authority = AgentAuthorityRuntime()
    log: dict[str, Any] = {
        "schema_version": "orqevia.orq-001-execution-log.v1",
        "project_id": PROJECT_ID,
        "started_at": started_at,
        "completed_at": None,
        "runtime": {
            "host": os.getenv("HOSTNAME", "ORQEVIA_BACKEND_CONTAINER"),
            "container": os.getenv("HOSTNAME", "UNKNOWN"),
            "source_revision": SOURCE_REVISION,
            "image_digest": IMAGE_DIGEST,
        },
        "registry": {
            "registry_id": registry["registry_id"],
            "registry_version": registry["registry_version"],
            "snapshot_sha256": sha256_text(
                json.dumps(registry, sort_keys=True, separators=(",", ":"))
            ),
            "agents_discovered": [agent["agent_id"] for agent in agents],
        },
        "availability": {
            "providers": provider_health,
            "queue_metrics": queue_metrics,
            "registry_dispatch_flag": {
                "ORQEVIA_REGISTRY_V1_ENABLED": os.getenv("ORQEVIA_REGISTRY_V1_ENABLED"),
                "PRIME_REGISTRY_V1_ENABLED": os.getenv("PRIME_REGISTRY_V1_ENABLED"),
            },
        },
        "events": [],
        "jobs": [],
        "handoffs": [],
        "errors": [],
        "retries": [],
    }
    atomic_json(STATE_PATH, {"phase": "started", "log": log, "financials": financials})

    results: dict[str, dict[str, Any]] = {}
    prompts: dict[str, str] = {}
    traces: dict[str, str] = {}
    for agent in agents:
        agent_id = agent["agent_id"]
        task = TASKS[agent_id]
        prompt = prompt_for(agent, financials, task)
        prompts[agent_id] = prompt
        source = "prime" if agent["reports_to"] == "prime" else agent["reports_to"]
        trace = str(uuid.uuid4())
        traces[agent_id] = trace
        event = authority.handoff(
            source=source,
            target=agent_id,
            relation="delegate",
            depth=1 if source == "prime" else 2,
            trace_id=trace,
            consequential=False,
        )
        log["handoffs"].append(
            {
                "agent_id": agent_id,
                "source": source,
                "target": agent_id,
                "trace_id": trace,
                "handoff_event_id": event["event_id"],
                "allowed": event["allowed"],
                "status": event["status"],
                "timestamp": event["timestamp"],
                "task_prompt_sha256": sha256_text(prompt),
            }
        )
        log["events"].append(
            {
                "timestamp": event["timestamp"],
                "event": "handoff_allowed",
                "agent_id": agent_id,
                "trace_id": trace,
            }
        )

    ordered_ids = [agent["agent_id"] for agent in agents if agent["agent_id"] not in {"a26", "a29"}]
    deep_agents = {"a12", "a14", "a18", "a21", "a26"}
    pending: dict[str, str] = {}
    for agent_id in ordered_ids:
        agent = next(item for item in agents if item["agent_id"] == agent_id)
        attempt = 1
        try:
            job = submit_job(
                agent_id,
                prompts[agent_id],
                attempt=attempt,
                deep=agent_id in deep_agents,
            )
            pending[agent_id] = job["id"]
            authority.stage(
                trace_id=traces[agent_id],
                agent_id=agent_id,
                stage="orq-001.task",
                status="started",
            )
            log["events"].append(
                {
                    "timestamp": utcnow(),
                    "event": "job_submitted",
                    "agent_id": agent_id,
                    "job_id": job["id"],
                    "attempt": attempt,
                }
            )
            atomic_json(STATE_PATH, {"phase": "jobs_submitted", "log": log, "financials": financials})
        except Exception as exc:
            log["errors"].append({"agent_id": agent_id, "phase": "submit", "error": type(exc).__name__, "message": str(exc)[:500]})

    for agent_id, job_id in pending.items():
        job = wait_job(job_id)
        if job.get("status") != "completed" or not (job.get("result") or "").strip():
            log["retries"].append(
                {
                    "agent_id": agent_id,
                    "failed_job_id": job_id,
                    "status": job.get("status"),
                    "error": job.get("error"),
                }
            )
            retry_prompt = (
                "ORQ-001 hypothetical Singapore SME. Answer briefly and factually. "
                f"Your role is {agent_id} — {next(a for a in agents if a['agent_id']==agent_id)['name']}. "
                f"Task: {TASKS[agent_id]['task']} "
                "Use only the supplied assumptions. Return Contribution and Evidence/caveat headings."
            )
            try:
                retry = submit_job(agent_id, retry_prompt, attempt=2, deep=False)
                job = wait_job(retry["id"])
            except Exception as exc:
                log["errors"].append({"agent_id": agent_id, "phase": "retry", "error": type(exc).__name__, "message": str(exc)[:500]})
            prompts[agent_id] = retry_prompt
        results[agent_id] = job
        authority.stage(
            trace_id=traces[agent_id],
            agent_id=agent_id,
            stage="orq-001.task",
            status="completed" if job.get("status") == "completed" else "failed",
        )
        log["jobs"].append(
            {
                "agent_id": agent_id,
                "job_id": job.get("id"),
                "status": job.get("status"),
                "provider": job.get("provider"),
                "model": job.get("model"),
                "created_at": job.get("created_at"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "attempts": job.get("attempts"),
                "input_tokens": job.get("input_tokens"),
                "output_tokens": job.get("output_tokens"),
                "actual_cost_usd": job.get("actual_cost_usd"),
                "prompt_sha256": sha256_text(prompts[agent_id]),
                "result_sha256": sha256_text(job.get("result") or ""),
                "result_chars": len(job.get("result") or ""),
                "error": job.get("error"),
            }
        )
        log["events"].append(
            {
                "timestamp": utcnow(),
                "event": "job_terminal",
                "agent_id": agent_id,
                "job_id": job.get("id"),
                "status": job.get("status"),
            }
        )
        atomic_json(STATE_PATH, {"phase": "jobs_running", "log": log, "financials": financials})

    completed_count = sum(1 for job in results.values() if job.get("status") == "completed" and (job.get("result") or "").strip())
    review_summary = {
        "financials": financials,
        "completed_agents": completed_count,
        "total_agents": len(agents),
        "job_statuses": {agent_id: job.get("status") for agent_id, job in results.items()},
    }
    for agent_id in ("a26", "a29"):
        agent = next(item for item in agents if item["agent_id"] == agent_id)
        base_prompt = prompt_for(agent, financials, TASKS[agent_id])
        review_prompt = (
            base_prompt
            + "\nExecution summary for review: "
            + json.dumps(review_summary, sort_keys=True, separators=(",", ":"))[:12000]
        )
        prompts[agent_id] = review_prompt
        job = submit_job(agent_id, review_prompt, attempt=1, deep=True)
        job = wait_job(job["id"])
        if job.get("status") != "completed" or not (job.get("result") or "").strip():
            log["errors"].append(
                {
                    "agent_id": agent_id,
                    "phase": "final_review",
                    "status": job.get("status"),
                    "error": job.get("error"),
                }
            )
        results[agent_id] = job
        authority.stage(
            trace_id=traces[agent_id],
            agent_id=agent_id,
            stage="orq-001.review",
            status="completed" if job.get("status") == "completed" else "failed",
        )
        log["jobs"].append(
            {
                "agent_id": agent_id,
                "job_id": job.get("id"),
                "status": job.get("status"),
                "provider": job.get("provider"),
                "model": job.get("model"),
                "created_at": job.get("created_at"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "attempts": job.get("attempts"),
                "input_tokens": job.get("input_tokens"),
                "output_tokens": job.get("output_tokens"),
                "actual_cost_usd": job.get("actual_cost_usd"),
                "prompt_sha256": sha256_text(review_prompt),
                "result_sha256": sha256_text(job.get("result") or ""),
                "result_chars": len(job.get("result") or ""),
                "error": job.get("error"),
            }
        )
        log["events"].append(
            {
                "timestamp": utcnow(),
                "event": "final_review_job_terminal",
                "agent_id": agent_id,
                "job_id": job.get("id"),
                "status": job.get("status"),
            }
        )

    matrix_agents = []
    for agent in agents:
        agent_id = agent["agent_id"]
        job = results.get(agent_id, {})
        result_text = job.get("result") or ""
        matrix_agents.append(
            {
                "agent_id": agent_id,
                "name": agent["name"],
                "role": agent["role"],
                "capabilities": [item["id"] for item in agent["responsibilities"]],
                "registry_status": agent["status"],
                "availability": {
                    "model_provider_ready": bool(provider_health),
                    "local_only": True,
                    "fallback_allowed": False,
                },
                "responsibility": TASKS[agent_id]["responsibility"],
                "assigned_task": TASKS[agent_id]["task"],
                "execution": {
                    "job_id": job.get("id"),
                    "status": job.get("status", "not_executed"),
                    "provider": job.get("provider"),
                    "model": job.get("model"),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "input_tokens": job.get("input_tokens"),
                    "output_tokens": job.get("output_tokens"),
                    "result": result_text,
                    "result_sha256": sha256_text(result_text),
                    "nonempty": bool(result_text.strip()),
                },
            }
        )
    matrix = {
        "schema_version": "orqevia.orq-001-agent-matrix.v1",
        "project_id": PROJECT_ID,
        "generated_at": utcnow(),
        "registry_id": registry["registry_id"],
        "agents_discovered": len(matrix_agents),
        "agents_completed": sum(
            1 for item in matrix_agents if item["execution"]["status"] == "completed" and item["execution"]["nonempty"]
        ),
        "agents": matrix_agents,
    }

    results_path = OUTPUT / "ORQ-001-results.json"
    atomic_json(results_path, financials)
    results_sha = sha256_file(results_path)
    memory_write = write_decision_memory(financials, results_sha)
    memory_test = {
        "schema_version": "orqevia.orq-001-memory-test.v1",
        "project_id": PROJECT_ID,
        "generated_at": utcnow(),
        "status": "WRITE_AND_PRE_RESTART_READ_ONLY",
        "memory_class": "semantic",
        "memory_key": memory_write["memory_key"],
        "write": memory_write["write_response"],
        "expected_record": memory_write["expected_record"],
        "pre_restart_read": request(
            "/control/api/survival/memory/semantic/" + urllib.parse.quote(memory_write["memory_key"]),
            timeout=30,
        ),
        "restart_test": {
            "required": True,
            "completed": False,
            "method": "docker restart of the ORQEVIA backend container followed by retrieval",
        },
    }
    atomic_json(OUTPUT / "ORQ-001-memory-test.json", memory_test)
    log["completed_at"] = utcnow()
    log["summary"] = {
        "agents_discovered": len(matrix_agents),
        "agents_completed": matrix["agents_completed"],
        "handoffs_allowed": sum(1 for item in log["handoffs"] if item["allowed"]),
        "jobs_completed": sum(1 for item in log["jobs"] if item["status"] == "completed"),
        "jobs_failed": sum(1 for item in log["jobs"] if item["status"] in {"failed", "cancelled"}),
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in log["jobs"]),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in log["jobs"]),
        "actual_cost_usd": sum(float(item.get("actual_cost_usd") or 0) for item in log["jobs"]),
    }
    atomic_json(OUTPUT / "ORQ-001-agent-matrix.json", matrix)
    atomic_json(OUTPUT / "ORQ-001-execution-log.json", log)
    (OUTPUT / "ORQ-001-report.md").write_text(build_report(financials, matrix, log), encoding="utf-8")
    atomic_json(
        STATE_PATH,
        {
            "phase": "awaiting_restart_verification",
            "financials": financials,
            "matrix": matrix,
            "log": log,
            "memory_test": memory_test,
            "results_sha256": results_sha,
        },
    )
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "phase": "awaiting_restart_verification",
                "agents_completed": matrix["agents_completed"],
                "handoffs_allowed": log["summary"]["handoffs_allowed"],
                "jobs_failed": log["summary"]["jobs_failed"],
                "artifact_directory": str(OUTPUT),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

