const SHELL_CACHE = "patitas-shell-v4";
const EXTERNAL_CACHE = "patitas-external-v1";
const APP_FILES = [
  "./",
  "./index.html",
  "./styles.css",
  "./cuaderno/Clasificador_de_perros_y_gatos.html",
  "./assets/mascotas.svg",
  "./assets/icon-pwa.svg",
  "./manifest.webmanifest",
  "./modelo/model.json",
  "./modelo/group1-shard1of2.bin",
  "./modelo/group1-shard2of2.bin",
  "./assets/favicon-16x16.png",
  "./assets/favicon-32x32.png",
  "./assets/favicon.ico"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(APP_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((key) => key.startsWith("patitas-") && key !== SHELL_CACHE && key !== EXTERNAL_CACHE)
        .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const requestUrl = new URL(request.url);
  if (requestUrl.origin !== self.location.origin) {
    event.respondWith((async () => {
      const cache = await caches.open(EXTERNAL_CACHE);
      const cached = await cache.match(request);
      const fresh = fetch(request).then((response) => {
        if (response.ok || response.type === "opaque") {
          cache.put(request, response.clone()).catch((error) => {
            console.warn("No se pudo guardar un recurso externo para uso sin conexión:", error);
          });
        }
        return response;
      });
      if (cached) {
        fresh.catch(() => {});
        return cached;
      }
      return fresh;
    })());
    return;
  }

  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached && request.mode !== "navigate") return cached;
    try {
      const response = await fetch(request);
      if (response.ok && requestUrl.pathname.endsWith(".html")) {
        const cache = await caches.open(SHELL_CACHE);
        cache.put(request, response.clone()).catch((error) => {
          console.warn("No se pudo actualizar la página guardada:", error);
        });
      }
      return response;
    } catch (error) {
      if (cached) return cached;
      if (request.mode === "navigate") {
        const offlinePage = await caches.match("./index.html");
        if (offlinePage) return offlinePage;
      }
      throw error;
    }
  })());
});
