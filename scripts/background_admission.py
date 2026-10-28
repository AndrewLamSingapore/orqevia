"""Owner CLI for durable background pause; Docker services are never restarted.

Resume is never automatic. Use only on an explicit Owner resume instruction.
Existing private application transport is untouched; this uses Docker stdin.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "pause", "resume", "verify"])
    parser.add_argument("--reason")
    parser.add_argument("--expected-generation", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action in ("pause", "resume") and not args.reason:
        parser.error("State changes require an explicit reason")
    if args.action == "resume" and args.expected_generation is None:
        parser.error("Explicit resume requires the current observed generation")
    source = (Path(__file__).resolve().parents[1] / "app/background_admission.py").read_text(encoding="utf-8")
    # Isolate module globals so diagnostic imports cannot shadow its types.
    program = "namespace={};exec(compile(" + repr(source) + ",'background_admission.py','exec'),namespace)\n"
    program += "import json,pathlib\ncontrol=namespace['BackgroundAdmission']('/data/compute-queue.db')\n"
    if args.action == "pause":
        program += 'control.install_paused(actor="OWNER_CLI",reason=' + repr(args.reason) + ")\n"
        program += 'marker=pathlib.Path("/data/coaching.pause")\nif not marker.exists():marker.write_text("Owner-authorized background admission pause. Explicit authorized resume required.\\n")\n'
    elif args.action == "resume":
        program += (
            "control.set_paused(False,expected_generation="
            + str(args.expected_generation)
            + ',actor="OWNER_CLI",reason='
            + repr(args.reason)
            + ")\n"
        )
        # Preserve unknown preexisting manual pauses. Only our compatibility
        # marker can be removed as part of the authorized resume operation.
        program += 'marker=pathlib.Path("/data/coaching.pause")\nif marker.exists() and marker.read_text().startswith("Owner-authorized background admission pause"):\n marker.unlink()\n'
    if args.action == "verify":
        program += "result=control.verify_transaction()\n"
    else:
        program += 'result=control.state()\nresult["coaching_compatibility_marker"]=pathlib.Path("/data/coaching.pause").exists()\n'
    program += "print(json.dumps(result))\n"
    done = subprocess.run(
        ["docker", "exec", "-i", "orqevia-epoch-20261016-backend-1", "python", "-B", "-"],
        input=program,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if done.returncode:
        raise SystemExit("Background admission operation failed; no automatic resume attempted")
    value = json.loads(done.stdout)
    if args.output:
        args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value))


if __name__ == "__main__":
    main()
