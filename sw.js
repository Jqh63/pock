const CACHE_NAME = 'pock-v42';
const ASSETS = [
  './',
  './index.html',
  './suivi-km-loa.html',
  './covoiturage-rando.html',
  './bibliotheque.html',
  './hta.html',
  './common.css',
  './common.js',
  './manifest.json',
  './icon-192-v2.png',
  './icon-512-v2.png',
  './apple-touch-icon-v2.png',
  './icon-maskable-v2.png',
  './icon-monochrome-v2.png'
];

// Précache par fichier (pas addAll) : un seul 404/timeout ne doit pas
// faire échouer toute l'install. Request{cache:'reload'} force une
// lecture réseau fraîche — sinon le cache HTTP du navigateur peut
// servir une copie périmée d'un asset et la précacher dans le nouveau
// CACHE, annulant l'effet du bump (acquis de la PWA WoL).
function precache(c) {
  return Promise.all(ASSETS.map(f =>
    c.add(new Request(f, { cache: 'reload' })).catch(() => {})
  ));
}

self.addEventListener('install', e => {
  // skipWaiting() appelé tout de suite (hors waitUntil), PAS enchaîné après le
  // précache : sinon le nouveau SW reste en 'waiting' tant que le fetch réseau
  // de tous les assets n'est pas fini → controllerchange tardif → l'utilisateur
  // doit forcer un refresh. Le précache continue dans waitUntil ; les miss
  // retombent sur le réseau via le handler fetch (acquis de la PWA WoL).
  e.waitUntil(caches.open(CACHE_NAME).then(precache));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      // Self-heal : le navigateur peut évincer CacheStorage (pression
      // stockage, nettoyage partiel) en gardant la registration — re-précache
      // si le cache est vide. Le refill sur miss (fetch ci-dessous) couvre le
      // reste de la vie du SW.
      .then(() => caches.open(CACHE_NAME))
      .then(c => c.keys().then(keys => keys.length ? null : precache(c)))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      // cache:'reload' : sur miss, bypass du cache HTTP navigateur (copie
      // potentiellement périmée) — on veut le réseau réel avant de re-cacher.
      return fetch(e.request, { cache: 'reload' }).then(resp => {
        // Ne cacher que les réponses same-origin OK (évite les opaques cross-origin)
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return resp;
      });
    }).catch(() => e.request.mode === 'navigate' ? caches.match('./index.html') : undefined)
  );
});
