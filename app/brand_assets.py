"""Public original-logo derivatives for existing local HTML surfaces."""
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse

OFFICIAL_LOGO_FILES = frozenset({
    'orqevia-official-v1-192.png','orqevia-official-v1-512.png','orqevia-official-v1-apple-touch.png',
    'orqevia-official-v1-favicon-16.png','orqevia-official-v1-favicon-32.png','orqevia-official-v1-favicon-48.png',
})


def official_logo_response(name: str):
    if name not in OFFICIAL_LOGO_FILES:
        raise HTTPException(404,'Logo asset unavailable')
    packaged=Path(__file__).with_name('pwa_static')/'icons'
    source=Path(__file__).resolve().parents[1]/'clients/pwa/icons'
    root=packaged if packaged.is_dir() else source
    path=root/name
    if not path.is_file():raise HTTPException(404,'Logo asset unavailable')
    return FileResponse(path,media_type='image/png',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
