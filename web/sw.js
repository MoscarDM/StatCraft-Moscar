/* Service worker: caché para uso sin conexión.
   - App shell: precargado al instalar.
   - Pyodide (CDN) y engine.zip: se guardan en caché la primera vez que se usan. */
const VERSION = 'sc-web-v1';
const SHELL = ['./', 'index.html', 'style.css', 'app.js', 'charts.js', 'samples.js', 'worker.js',
  'manifest.webmanifest', 'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const heavy = url.hostname.includes('jsdelivr.net') || url.pathname.endsWith('engine.zip') || url.pathname.endsWith('manifest.json');
  if (heavy) {
    // Cache-first para Pyodide (versión fija); red primero para el motor propio.
    const cacheFirst = url.hostname.includes('jsdelivr.net');
    e.respondWith(caches.open(VERSION).then(async (c) => {
      const hit = await c.match(req);
      if (cacheFirst && hit) return hit;
      try { const r = await fetch(req); if (r.ok) c.put(req, r.clone()); return r; }
      catch (err) { if (hit) return hit; throw err; }
    }));
    return;
  }
  if (url.origin !== location.origin) return;
  // Red primero (para recibir actualizaciones), caché si no hay conexión.
  e.respondWith(fetch(req).then((r) => {
    if (r.ok) caches.open(VERSION).then((c) => c.put(req, r.clone()));
    return r;
  }).catch(() => caches.match(req).then((h) => h || caches.match('index.html'))));
});
