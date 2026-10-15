"""Build-time additive extension of the preserved installed Interface image."""
from pathlib import Path
p=Path('/app/app/interface_server.py')
text=p.read_text(encoding='utf-8')
if 'orqevia_bridge' in text:raise RuntimeError('Interface already extended')
p.write_text(text+'\nfrom .orqevia_bridge import router as intelligence_bridge_router\napp.include_router(intelligence_bridge_router)\n',encoding='utf-8')
p=Path('/app/app/pwa_static/index.html')
text=p.read_text(encoding='utf-8')
needle='<div class="function-grid">'
if text.count(needle)!=1:raise RuntimeError('Known PWA function grid is required')
text=text.replace(needle,needle+'<a href="/orqevia/" class="intelligence-link">God\'s Eye · Geospatial Intelligence</a>',1)
p.write_text(text,encoding='utf-8')
