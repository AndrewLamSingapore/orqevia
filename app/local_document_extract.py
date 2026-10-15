"""Short-lived parser worker. No document content is written to operational logs."""
import json
from pathlib import Path
import sys
from .local_knowledge import extract_document,MAX_UPLOAD

if __name__=='__main__':
    path=Path(sys.argv[1])
    if not path.is_file() or not 0<path.stat().st_size<=MAX_UPLOAD:sys.exit(2)
    try:print(json.dumps(extract_document(path),ensure_ascii=False))
    except Exception:sys.exit(3)
