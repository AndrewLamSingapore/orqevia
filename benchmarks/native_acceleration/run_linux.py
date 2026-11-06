"""Run the pinned baseline in an existing Linux Python child, with temporary state.

No container/image creation, restart, application import in PID1, production
database access, model call or persistent deployment change is performed.
"""

import argparse
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = r"""
import io,json,os,pathlib,runpy,sys,tempfile,zipfile
package=sys.stdin.buffer.read()
candidate=sys.argv[1]=='candidate'
with tempfile.TemporaryDirectory(prefix='abex-pif-baseline-') as folder:
 root=pathlib.Path(folder).resolve()
 with zipfile.ZipFile(io.BytesIO(package)) as archive:
  for name in archive.namelist():
   if not (root/name).resolve().is_relative_to(root):raise ValueError('Invalid fixture path')
  archive.extractall(root)
 sys.path.insert(0,str(root))
 output=root/'result/compare.json' if candidate else root/'result'
 sys.argv=[str(root/('benchmarks/native_acceleration/compare.py' if candidate else 'benchmarks/native_acceleration/baseline.py')),'--output',str(output)]
 try:runpy.run_path(sys.argv[0],run_name='__main__')
 except SystemExit as result:
  if result.code not in (0,None):raise
 print('FULL_REPORT='+ (root/'result/compare.json' if candidate else root/'result/python-numpy-baseline.json').read_text())
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", action="store_true")
    args = parser.parse_args()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("app/__init__.py", "")
        for path in (ROOT / "app/pif").glob("*.py"):
            relative = path.relative_to(ROOT).as_posix()
            # Baseline remains pinned even after local optimization work.
            source = (
                path.read_bytes()
                if args.candidate or path.name == "numpy_backend.py"
                else subprocess.check_output(["git", "show", "f37673b4:" + relative], cwd=ROOT)
            )
            archive.writestr(relative, source)
        for path in (ROOT / "benchmarks/native_acceleration").glob("*.py"):
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr(
            "benchmarks/native_acceleration/reference_core.py",
            subprocess.check_output(["git", "show", "f37673b4:app/pif/core.py"], cwd=ROOT),
        )
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "orqevia-epoch-20261016-backend-1",
            "python",
            "-B",
            "-c",
            PROGRAM,
            "candidate" if args.candidate else "baseline",
        ],
        input=buffer.getvalue(),
        capture_output=True,
        timeout=60,
    )
    if result.returncode:
        raise SystemExit("Isolated Linux baseline failed; private diagnostics withheld")
    text = result.stdout.decode()
    report = json.loads(text.split("FULL_REPORT=", 1)[1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if args.candidate:
        print(
            json.dumps(
                {
                    "python": report["python"],
                    "cases": {
                        name: {
                            variant: data["median_seconds"] for variant, data in case.items() if isinstance(data, dict)
                        }
                        for name, case in report["cases"].items()
                    },
                    "production_mutated": False,
                }
            )
        )
        return
    print(
        json.dumps(
            {
                "python": report["python"],
                "numpy": report["numpy"],
                "cases": [
                    {
                        "states": c["states"],
                        "python_service": c["python_service"]["median_seconds"],
                        "numpy_service": c["numpy_service"]["median_seconds"],
                        "numpy_kernel_fraction_of_service": c["numpy_method"]["median_seconds"]
                        / c["numpy_service"]["median_seconds"],
                    }
                    for c in report["cases"]
                ],
                "production_mutated": False,
            }
        )
    )


if __name__ == "__main__":
    main()
