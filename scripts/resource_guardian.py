"""Owner CLI for the optional existing-coordinator resource policy.

Use a disposable database for qualification. Production Linux SQLite must stay
inside its owning service: do not open it from Windows via WSL/UNC or create a
second production database to control the same capacity.
"""

from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.resource_guardian import MODES, Profile, ResourceGuardian, Workload  # noqa: E402
from app.resource_process import connect, run_guarded  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--db", type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("observe")
    commands.add_parser("status")
    mode = commands.add_parser("mode")
    mode.add_argument("value", choices=sorted(MODES))
    run = commands.add_parser("run")
    run.add_argument("--work-key", required=True)
    run.add_argument("--lane", choices=["tools", "build"], default="tools")
    run.add_argument("--memory-mib", type=int, required=True)
    run.add_argument("--cpu-threads", type=int, default=1)
    run.add_argument("--timeout", type=float, required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    guardian = ResourceGuardian(Profile.read(args.profile))
    if args.action == "observe":
        print(json.dumps(asdict(guardian.observe())))
        return 0
    if args.db is None:
        parser.error("--db is required for persistent operations")
    if args.action == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        result = run_guarded(
            guardian,
            args.db,
            command,
            work_key=args.work_key,
            workload=Workload(args.lane, args.memory_mib * 1048576, args.cpu_threads),
            timeout_seconds=args.timeout,
        )
    else:
        with connect(args.db) as db:
            guardian.install(db)
            result = guardian.set_mode(db, args.value) if args.action == "mode" else guardian.status(db)
    print(json.dumps(result))
    return 0 if result.get("status") in (None, "COMPLETED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
