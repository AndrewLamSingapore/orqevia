"""Build-time additive extension of the preserved installed Interface image."""

from pathlib import Path


def extend_interface(text):
    if "orqevia_bridge" in text:
        raise RuntimeError("Interface already extended")
    # Specific routes must precede the retained /api/orqevia/{path:path}.
    return (
        text
        + "\nfrom .local_knowledge_bridge import router as knowledge_bridge_router"
        + "\napp.include_router(knowledge_bridge_router)"
        + "\nfrom .orqevia_bridge import router as intelligence_bridge_router"
        + "\napp.include_router(intelligence_bridge_router)\n"
    )


def main():
    path = Path("/app/app/interface_server.py")
    path.write_text(extend_interface(path.read_text(encoding="utf-8")), encoding="utf-8")
    path = Path("/app/app/pwa_static/index.html")
    text = path.read_text(encoding="utf-8")
    if 'class="intelligence-link"' not in text:
        needle = '<div class="function-grid">'
        if text.count(needle) != 1:
            raise RuntimeError("Known PWA function grid is required")
        link = '<a href="/pwa/?view=gods-eye" class="intelligence-link">God\'s Eye - Geospatial Intelligence</a>'
        text = text.replace(needle, needle + link, 1)
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
