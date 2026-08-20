/*
 * Haven service worker — deliberately MINIMAL and SAFE.
 *
 * Haven is a realtime chat app, so the cardinal rule is: NEVER serve a stale
 * app shell. This worker does NOT cache the app, its JS/CSS, the API, or the
 * WebSocket. It exists only to:
 *   (a) satisfy PWA installability (a fetch handler must exist)
 *   (b) show a friendly offline page for failed *navigations*
 *   (c) display web push notifications when the app is in the background
 *
 * Everything else goes straight to the network, untouched. WebSocket upgrades
 * are not `fetch` events and are never intercepted.
 *
 * Bumping VERSION invalidates the old cache on activate — the built-in
 * kill-switch if this ever needs to be superseded.
 */
const VERSION = 'haven-sw-v2';
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

// --- Web push ---

self.addEventListener('push', (event) => {
  // The server always sends a JSON payload; guard against empty pushes.
  if (!event.data) return;

  let payload;
  try {
    payload = event.data.json();
  } catch (_) {
    // Malformed payload — show a generic notification rather than silently fail.
    payload = { title: 'Haven', body: 'New message' };
  }

  const title = payload.title || 'Haven';
  const options = {
    body: payload.body || '',
    icon: payload.icon || '/static/icons/icon-192.png',
    badge: payload.badge || '/static/icons/icon-192.png',
    data: payload.data || {},
    // Keep notification visible until the user interacts with it on mobile.
    requireInteraction: false,
    // Tag reuses/replaces an existing notification from the same sender,
    // preventing a flood of individual banners when multiple messages arrive.
    tag: 'haven-message',
    // Renotify (vibrate/sound again) even if the tag matches — so new messages
    // still buzz the phone when the previous notification is still showing.
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const data = event.notification.data || {};
  const roomId = data.room_id || null;
  const url = data.url || '/';

  event.waitUntil(
    clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((windowClients) => {
        // If a Haven window is already open, focus it AND tell it which room to
        // show (the page can't read this URL — it's already loaded — so we hand
        // it the room_id over postMessage and let it switch rooms in place).
        for (const client of windowClients) {
          if (client.url.startsWith(self.location.origin)) {
            if (roomId) client.postMessage({ type: 'navigate', room_id: roomId });
            if ('focus' in client) return client.focus();
          }
        }
        // No existing window — open one scoped to the room via the URL param,
        // which the client reads on load.
        if (clients.openWindow) {
          return clients.openWindow(url);
        }
      })
  );
});
