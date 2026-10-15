"""Production entry for the isolated intelligence companion, behind Interface."""
import os
from pathlib import Path

raw=os.getenv('ORQEVIA_DATA_DIR','').strip()
if not raw or not Path(raw).is_absolute():
    raise RuntimeError('An explicit external ORQEVIA_DATA_DIR is required')
root=Path(raw).resolve()
source=Path(__file__).resolve().parents[2]
if root==source or source in root.parents:
    raise RuntimeError('Intelligence data must be outside the source repository')
root.mkdir(parents=True,exist_ok=True)
from .ui import app
from .security import install
install(app)
