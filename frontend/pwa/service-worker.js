const CACHE_NAME = 'sovushka-shell-v614';
const OFFLINE_URL = '/pwa/offline.html';
const PRECACHE_URLS = [OFFLINE_URL, '/pwa-icons/icon.png'];
const NEVER_CACHE_PREFIXES = [
  '/api/',
  '/lite-api/',
  '/stream',
  '/events',
  '/documents',
  '/files',
  '/verify-image',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

function isRuntimeContent(request, url) {
  return request.method !== 'GET'
    || url.origin !== self.location.origin
    || NEVER_CACHE_PREFIXES.some(prefix => url.pathname.startsWith(prefix))
    || (request.headers.get('accept') || '').includes('text/event-stream');
}

self.addEventListener('fetch', event => {
  const {request} = event;
  const url = new URL(request.url);
  if (isRuntimeContent(request, url)) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (PRECACHE_URLS.includes(url.pathname)) {
    event.respondWith(caches.match(request).then(response => response || fetch(request)));
  }
});
