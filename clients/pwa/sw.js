const CACHE='jarvis-shell-v11';
const SHELL=['/pwa/','/pwa/index.html','/pwa/style.css','/pwa/recovery.js','/pwa/release.mjs','/pwa/app.mjs','/pwa/core.mjs','/pwa/storage.mjs','/pwa/voice.mjs','/pwa/manifest.webmanifest','/pwa/icons/icon.svg','/pwa/icons/jarvis-prime-v1-192.png','/pwa/icons/jarvis-prime-v1-512.png','/pwa/icons/jarvis-prime-v1-apple-touch.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('jarvis-shell-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==self.location.origin||url.search||!SHELL.includes(url.pathname))return;event.respondWith(fetch(event.request).catch(()=>caches.match(url.pathname)));});
