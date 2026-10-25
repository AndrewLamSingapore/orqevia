const CACHE='orqevia-shell-v40';
const SHELL=['/pwa/intelligence-capabilities.mjs','/pwa/operations.mjs','/pwa/integration-panels.mjs','/pwa/design/tokens.css','/pwa/design/theme.mjs','/pwa/sovereign.css','/pwa/sovereign.mjs','/pwa/vendor/natural-earth-land.geojson','/pwa/command-map.mjs','/pwa/command-map.css','/pwa/vendor/maplibre-gl.mjs','/pwa/vendor/maplibre-gl-shared.mjs','/pwa/vendor/maplibre-gl-worker.mjs','/pwa/vendor/maplibre-gl.css','/pwa/','/pwa/index.html','/pwa/style.css','/pwa/recovery.js','/pwa/release.mjs','/pwa/app.mjs','/pwa/dashboard.mjs','/pwa/intelligence.mjs','/pwa/intelligence.css','/pwa/knowledge.mjs','/pwa/knowledge.css','/pwa/workspace-tools.mjs','/pwa/dashboard.css','/pwa/command-center.css','/pwa/core.mjs','/pwa/storage.mjs','/pwa/voice.mjs','/pwa/manifest.webmanifest','/pwa/icons/orqevia-command-v1-192.png','/pwa/icons/orqevia-command-v1-512.png','/pwa/icons/orqevia-command-v1-apple-touch.png','/pwa/icons/orqevia-command-v1-favicon-16.png','/pwa/icons/orqevia-command-v1-favicon-32.png','/pwa/icons/orqevia-command-v1-favicon-48.png','/pwa/icons/orqevia-official-v1-192.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>(key.startsWith('jarvis-shell-')||key.startsWith('orqevia-shell-'))&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('message',event=>{
  if(event.data?.type!=='ORQEVIA_SHELL_RELEASE')return;
  const port=event.ports?.[0];
  port?.postMessage({type:'ORQEVIA_SHELL_RELEASE',release:CACHE});
  port?.close?.();
});
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||url.search||!SHELL.includes(url.pathname))return;
  event.respondWith(fetch(event.request).catch(async()=>{
    // A global caches.match may mix a partial or unrelated generation into it.
    const cached=await (await caches.open(CACHE)).match(url.pathname);
    const id=event.clientId||event.resultingClientId;
    if(cached&&id&&self.clients.get){
      try{
        const client=await self.clients.get(id);
        client?.postMessage({type:'ORQEVIA_SHELL_OFFLINE',release:CACHE});
      }catch{/* A disappearing client must not break the cached shell. */}
    }
    return cached||Response.error();
  }));
});
