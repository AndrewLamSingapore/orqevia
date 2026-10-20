"""Fail-closed verification for the pinned upstream MBTI-in-Thoughts install."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mbti_in_thoughts


def main() -> int:
    report = mbti_in_thoughts.health()
    print(json.dumps(report, indent=2, sort_keys=True))
    failures = []
    if not report["installed"]:
        failures.append("distribution is not installed")
    if report["version"] != mbti_in_thoughts.DISTRIBUTION_VERSION:
        failures.append(f"unexpected version: {report['version']}")
    if not report["src_package_available"]:
        failures.append("upstream src package is not importable")
    if report["mbti_profile_count"] != len(mbti_in_thoughts.MBTI_TYPES):
        failures.append("not all 16 MBTI profiles are available")
    if failures:
        print("FAIL: " + "; ".join(failures))
        return 1
    print("PASS: pinned upstream MBTI-in-Thoughts is installed and inactive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
