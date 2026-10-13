"""Replay existing pinned normal jobs read-only, with zero new inference."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.normal_latest_observation import main


if __name__ == '__main__':
    raise SystemExit(main())
