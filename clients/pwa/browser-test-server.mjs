/** Minimal static server for loopback-only Playwright verification. */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PORT = Number(process.env.PWA_TEST_PORT || 4173);
const HOST = "127.0.0.1";
const TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".webmanifest", "application/manifest+json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".ico", "image/x-icon"],
  [".geojson", "application/geo+json; charset=utf-8"],
]);

function targetFor(requestUrl) {
  const url = new URL(requestUrl, `http://${HOST}:${PORT}`);
  if (url.pathname === "/") return null;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/interface/")) {
    return null;
  }
  if (!url.pathname.startsWith("/pwa/")) return null;
  const relative = decodeURIComponent(url.pathname.slice(5)) || "index.html";
  const normalized = normalize(relative);
  const target = resolve(join(ROOT, normalized));
  if (!(target === ROOT || target.startsWith(ROOT + sep))) return null;
  return target;
}

const server = createServer(async (request, response) => {
  const target = targetFor(request.url || "/");
  if (!target) {
    const path = new URL(request.url || "/", `http://${HOST}:${PORT}`).pathname;
    if (path !== "/") {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not found");
      return;
    }
    response.writeHead(302, { Location: "/pwa/" }).end();
    return;
  }
  try {
    const info = await stat(target);
    const file = info.isDirectory() ? join(target, "index.html") : target;
    const body = await readFile(file);
    response.writeHead(200, {
      "Content-Type": TYPES.get(extname(file).toLowerCase()) || "application/octet-stream",
      "Content-Length": body.length,
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Service-Worker-Allowed": "/pwa/",
    });
    response.end(body);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not found");
  }
});

server.listen(PORT, HOST, () => {
  console.log(`PWA browser test server listening on http://${HOST}:${PORT}/pwa/`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
