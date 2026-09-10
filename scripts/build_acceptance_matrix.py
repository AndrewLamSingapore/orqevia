"""Build an honest acceptance matrix from actual JUnit evidence.

This is a reporting tool, never an authority or production promotion mechanism.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"PASS", "PASS_WITH_NON_BLOCKING_LIMITATION", "BLOCKED", "NOT_APPLICABLE"}


def build(inventory, junit_path, repo=ROOT):
    root = ET.parse(junit_path).getroot()
    cases = root.findall(".//testcase")
    if not cases:
        raise ValueError("JUnit contains no cases")
    names = [c.get("classname", "") + "::" + c.get("name", "") for c in cases]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate JUnit case identities")
    suites = root.findall(".//testsuite") if root.tag != "testsuite" else [root]
    declared = sum(int(s.get("tests", "0")) for s in suites if s.findall("testcase"))
    if declared != len(cases):
        raise ValueError("JUnit count does not match evidence")
    rows = []
    for spec in inventory["items"]:
        if spec["status"] not in STATUSES:
            raise ValueError("Unrecognized phase status")
        # This inventory has known unresolved requirements. It may not elevate a
        # fixture pass to phase acceptance, including by relabeling the status.
        if spec["status"] in {"PASS", "PASS_WITH_NON_BLOCKING_LIMITATION"}:
            raise ValueError("Unresolved inventory cannot declare phase acceptance")
        def belongs(case, module):
            name = case.get("classname", "")
            return name == module or name.startswith(module + ".")
        selected = [c for c in cases if any(belongs(c, t) for t in spec["tests"])]
        missing = [t for t in spec["tests"] if not any(belongs(c, t) for c in cases)]
        failed = [c.get("classname") + "::" + c.get("name") for c in selected
                  if c.find("failure") is not None or c.find("error") is not None or c.find("skipped") is not None]
        for module in spec["tests"]:
            if not (repo / (module.replace(".", "/") + ".py")).is_file():
                raise ValueError("Referenced test source missing: " + module)
        checked = bool(selected) and not missing and not failed
        rows.append({**spec, "evidence_level": ["IMPLEMENTED", "FIXTURE_TESTED"] if checked else ["BLOCKED"],
                     "development_checks": "PASS" if checked else "BLOCKED",
                     "passing_cases": [c.get("classname") + "::" + c.get("name") for c in selected
                                       if not any(c.find(tag) is not None for tag in ("failure", "error", "skipped"))],
                     "missing_test_modules": missing, "nonpassing_cases": failed})
    phases = [{"phase": phase, "status": "BLOCKED",
               "reason": "Required scope remains unresolved; development fixtures do not qualify the full phase.",
               "items": [r["item"] for r in rows if r["phase"] == phase]} for phase in range(13)]
    phases[0]["reason"] = "Source discovery recorded; current immutable Dell runtime provenance remains unverified."
    all_failed = [n for n,c in zip(names,cases) if any(c.find(t) is not None for t in ("failure", "error", "skipped"))]
    return {"schema_version": "acceptance-evidence.v1", "overall_status": "BLOCKED",
            "full_mandate_complete": False, "production_verified": False,
            "evidence_scope": "JUnit fixtures only; real provider and hardware not qualified",
            "junit_sha256": hashlib.sha256(Path(junit_path).read_bytes()).hexdigest(),
            "tests": len(cases), "nonpassing_cases": all_failed, "phases": phases, "items": rows}


def render(report):
    lines = ["# PRIME acceptance matrix", "",
             "Overall: **BLOCKED**. Development fixture results are separate from phase acceptance.",
             "No production verification or implementation-complete claim is made.", "",
             "| Item | Status | Evidence level | Development checks | Remaining limitation | Lam action now |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in report["items"]:
        lines.append("| " + " | ".join([row["item"], row["status"], ", ".join(row["evidence_level"]),
                                      row["development_checks"], row["remaining_limitation"], "No"]) + " |")
    lines += ["", "The JSON companion contains exact passing/nonpassing case identities and all 13 phase gates.",
              "Cloud execution is NOT_APPLICABLE only within the frozen disabled-cloud Harness v0 scope.",
              "BLOCKED capability work does not stop independent work. No repeated request for the unavailable ABEX or external specifications is required.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads((ROOT / "governance/acceptance_inventory.v1.json").read_text(encoding="utf-8"))
    report = build(inventory, args.junit)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "acceptance-matrix.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output / "acceptance-matrix.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"report_generated": True, "overall_status": report["overall_status"],
                      "tests": report["tests"], "items": len(report["items"])}))
    # Success means evidence was generated, never that a phase passed.
    return 1 if report["nonpassing_cases"] or any(r["missing_test_modules"] for r in report["items"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
