// Minimal offline-shell service worker for Kyoto Food Finder.
// Caches the app shell so the page loads offline; the actual restaurant
// data is too large to cache fully and requires network on first visit.
const SHELL = 'kyoto-food-shell-v1';
const SHELL_FILES = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  // For navigation requests: network-first, fallback to cached shell.
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('./index.html'))
    );
    return;
  }
  // For everything else (tiles, css, js from CDN): network-first, no caching.
  // Tile data is huge; let it refetch fresh.
});
