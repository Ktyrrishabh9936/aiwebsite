const CACHE = "arevei-pwa-test-v1";
const testPage = new URL("pwa-test.html", self.registration.scope).href;
const offlinePage = new URL("offline.html", self.registration.scope).href;
const assets = [testPage, offlinePage, "pwa-icon-192.png", "pwa-icon-512.png", "manifest.json"]
  .map((path) => new URL(path, self.registration.scope).href);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(assets)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("arevei-pwa-test-") && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || /\/api(?:\/|$)/.test(url.pathname)) return;
  const isTestPage = url.pathname === new URL(testPage).pathname;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(async () => {
      const cache = await caches.open(CACHE);
      return await cache.match(isTestPage ? testPage : offlinePage);
    }));
  } else if (assets.includes(url.href)) {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
  }
});
