/*
 * Haven service worker — deliberately MINIMAL and SAFE.
 *
 * Haven is a realtime chat app, so the cardinal rule is: NEVER serve a stale
 * app shell. This worker does NOT cache the app, its JS/CSS, the API, or the
 * WebSocket. It exists only to (a) satisfy PWA installability (a fetch handler
 * must exist) and (b) show a friendly offline page for failed *navigations*.
 *
 * Everything else goes straight to the network, untouched. WebSocket upgrades
 * are not `fetch` events and are never intercepted.
 *
 * Bumping VERSION invalidates the old cache on activate — the built-in
 * kill-switch if this ever needs to be superseded.
 */
const VERSION = 'haven-sw-v1';
const OFFLINE_URL = '/static/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.add(OFFLINE_URL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Only intervene on top-level navigations, and only to provide an offline
  // fallback. Never touch API calls, static assets, or anything dynamic —
  // that's what keeps a live chat from ever showing stale content.
  if (req.mode !== 'navigate') {
    return; // default: straight to network
  }
  event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
});
