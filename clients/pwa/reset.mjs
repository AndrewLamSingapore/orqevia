const status = document.getElementById('reset-status');
const appCachePrefixes = ['jarvis-shell-', 'orqevia-shell-'];

async function repair() {
  let serviceWorkersCleared = 0;
  let cachesCleared = 0;

  try {
    const registrations = await navigator.serviceWorker?.getRegistrations?.() || [];
    for (const registration of registrations) {
      if (new URL(registration.scope).pathname.startsWith('/pwa/') && await registration.unregister()) {
        serviceWorkersCleared += 1;
      }
    }
  } catch {
    // The navigation still refreshes if service-worker management is unavailable.
  }

  try {
    const names = await caches?.keys?.() || [];
    for (const name of names) {
      if (appCachePrefixes.some((prefix) => name.startsWith(prefix)) && await caches.delete(name)) {
        cachesCleared += 1;
      }
    }
  } catch {
    // A fresh navigation remains safe when Cache Storage is unavailable.
  }

  if (status) {
    status.textContent = `Cleared ${serviceWorkersCleared} ORQEVIA worker(s) and ${cachesCleared} app cache(s). Reopening the current workspace…`;
  }
  location.replace(`/pwa/?recovered=${Date.now()}`);
}

void repair();
