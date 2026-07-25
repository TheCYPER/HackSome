const CACHE = "relay-rehearsal-production-20260725-v7";
const ASSETS = [
  "./index.html",
  "./index.html?deployment=static-review",
  "./styles.css?v=20260725-production-v7",
  "./safety-policy.js?v=20260725-policy-v1",
  "./outcome-model.js?v=20260725-outcomes-v1",
  "./recovery.js?v=20260725-recovery-v1",
  "./app.js?v=20260725-production-v7",
  "./join.html",
  "./companion.css?v=20260725-production-v7",
  "./join.js?v=20260725-production-v7",
  "./assets/favicon.svg",
  "./assets/social-preview.jpg",
  "./manifest.webmanifest",
];
const OPTIONAL_ASSETS = ["./"];
const SECURITY_HEADERS = {
  "Content-Security-Policy": "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self'; manifest-src 'self'; worker-src 'self'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
};

async function withSecurityHeaders(response) {
  if (!response || response.type === "opaque" || response.status === 0) return response;
  const headers = new Headers(response.headers);
  Object.entries(SECURITY_HEADERS).forEach(([name, value]) => headers.set(name, value));
  return new Response(await response.arrayBuffer(), {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then(async (cache) => {
    await Promise.all(ASSETS.map(async (url) => {
      const response = await fetch(url, { cache: "reload" });
      if (!response.ok) throw new Error(`Unable to cache ${url}`);
      await cache.put(url, await withSecurityHeaders(response));
    }));
    await Promise.all(OPTIONAL_ASSETS.map(async (url) => {
      try {
        const response = await fetch(url, { cache: "reload" });
        if (response.ok) await cache.put(url, await withSecurityHeaders(response));
      } catch { /* Subpath CDNs may not expose a directory response. */ }
    }));
  }));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(event.request, { cache: "no-store" }).catch(() => new Response(JSON.stringify({
      error: { code: "offline", message: "companion service is offline" },
    }), { status: 503, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } })));
    return;
  }
  event.respondWith((async () => {
    try {
      const response = await fetch(event.request, { cache: "no-store" });
      if (response.ok) {
        const secured = await withSecurityHeaders(response);
        const cache = await caches.open(CACHE);
        await cache.put(event.request, secured.clone());
        return secured;
      }
      return withSecurityHeaders(response);
    } catch {
      const cached = await caches.match(event.request, { ignoreSearch: false });
      if (cached) return withSecurityHeaders(cached);
      if (event.request.mode === "navigate") {
        return url.pathname.endsWith("/join.html") ? caches.match("./join.html") : caches.match("./index.html");
      }
      return new Response("Offline asset unavailable", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
  })());
});
