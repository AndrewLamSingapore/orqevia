"""Replace a complete JSON state file only after a durable temporary write."""
import json
import os
from pathlib import Path
import tempfile

def write_json(path, payload, **options):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix='.'+target.name+'.',suffix='.pending',dir=target.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump(payload,stream,**options)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,target)
    finally:
        if os.path.exists(name):os.unlink(name)
