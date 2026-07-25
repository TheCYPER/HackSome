const CACHE = "relay-rehearsal-production-20260725-v3";
const ASSETS = [
  "./index.html",
  "./index.html?deployment=static-review",
  "./styles.css?v=20260725-production-v3",
  "./safety-policy.js?v=20260725-policy-v1",
  "./outcome-model.js?v=20260725-outcomes-v1",
  "./app.js?v=20260725-production-v3",
  "./join.html",
  "./companion.css?v=20260725-production-v3",
  "./join.js?v=20260725-production-v3",
  "./assets/favicon.svg",
  "./assets/social-preview.jpg",
  "./manifest.webmanifest",
];
const OPTIONAL_ASSETS = ["./"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then(async (cache) => {
    await Promise.all(ASSETS.map(async (url) => {
      const response = await fetch(url, { cache: "reload" });
      if (!response.ok) throw new Error(`Unable to cache ${url}`);
      await cache.put(url, response);
    }));
    await Promise.all(OPTIONAL_ASSETS.map(async (url) => {
      try {
        const response = await fetch(url, { cache: "reload" });
        if (response.ok) await cache.put(url, response);
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
        const cache = await caches.open(CACHE);
        await cache.put(event.request, response.clone());
      }
      return response;
    } catch {
      const cached = await caches.match(event.request, { ignoreSearch: false });
      if (cached) return cached;
      if (event.request.mode === "navigate") {
        return url.pathname.endsWith("/join.html") ? caches.match("./join.html") : caches.match("./index.html");
      }
      return new Response("Offline asset unavailable", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
  })());
});
