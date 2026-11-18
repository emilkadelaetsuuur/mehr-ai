// The offline cache contains only the public interface.
const CACHE = "mehr-shell-v10";
const SHELL = ["/", "/cabinet/", "/brand/type.css", "/brand/clinic.css", "/styles.css", "/home.css",
  "/home.js", "/app.js", "/care-work.js", "/i18n.js", "/brand/mehr-wave-blue.svg", "/brand/physician.webp", "/brand/home-visit.webp", "/brand/home-visit-mobile.webp", "/brand/studio.css", "/voice-studio.js", "/brand/language.css", "/brand/language.js", "/brand/navigation.svg", "/brand/flag-ru.png", "/brand/flag-uz.png", "/manifest.json"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key =>
    (key.startsWith("mehr-shell-") || key === "nigoh-v2") && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  // Browsers seek in the short voice samples using byte ranges. CacheStorage only accepts full responses.
  if (url.pathname.endsWith(".mp3") && event.request.headers.has("range")) return;
  if (event.request.method !== "GET" || url.origin !== self.location.origin ||
      !(SHELL.includes(url.pathname) || url.pathname.startsWith("/brand/"))) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(event.request);
      if (response.ok) await cache.put(url.pathname, response.clone());
      return response;
    } catch {
      return (await cache.match(url.pathname)) || Response.error();
    }
  })());
});
