// common.js — utilitaires partagés entre les apps Pock

// Escape user-generated content before injecting into innerHTML
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  // innerHTML n'échappe que & < > : les guillemets doivent l'être aussi, sinon
  // une valeur injectée dans value="${esc(x)}" ferme l'attribut (troncature
  // d'un titre contenant ", ou injection d'attributs depuis un blob partagé).
  return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Unique id: timestamp base36 + random suffix (no collision even in same ms)
function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// Service worker registration with reload-loop guard
if ('serviceWorker' in navigator) {
  // hadController : skip the very first install (no prior controller) — sinon
  // clients.claim() au premier chargement émet controllerchange et déclenche
  // un reload en plein démarrage. updateViaCache:'none' : ne pas servir un
  // sw.js périmé depuis le cache HTTP (sinon le bump CACHE peut tarder).
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register('./sw.js', { updateViaCache: 'none' })
    .then(reg => { if (reg && reg.update) reg.update(); })
    .catch(() => {});
  // Détection d'update active (portée de la PWA WoL) — aucun déclencheur seul
  // n'est fiable sur Android PWA standalone : le focus ne se déclenche souvent
  // pas au retour depuis le sélecteur d'apps, les events de navigation sont
  // rares. On empile donc plusieurs sondes pour forcer reg.update().
  const forceSwCheck = () => {
    navigator.serviceWorker.getRegistration()
      .then(reg => { if (reg && reg.update) reg.update(); })
      .catch(() => {});
  };
  window.addEventListener('focus', forceSwCheck);                       // desktop, parfois Android
  document.addEventListener('visibilitychange', () => {                 // plus fiable sur Android PWA
    if (!document.hidden) forceSwCheck();
  });
  setInterval(() => { if (!document.hidden) forceSwCheck(); }, 5 * 60 * 1000); // filet si l'app reste ouverte des heures
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing || !hadController) return;
    refreshing = true;
    window.location.reload();
  });
}

// ---------- Export / Import of all Pock data ----------

const POCK_PREFIX = 'pock-';

function pockListKeys() {
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(POCK_PREFIX)) keys.push(k);
  }
  return keys;
}

function pockExportAll() {
  const data = {};
  pockListKeys().forEach(k => { data[k] = localStorage.getItem(k); });
  return { version: 1, exportedAt: new Date().toISOString(), data };
}

function pockExportToFile() {
  const exp = pockExportAll();
  const blob = new Blob([JSON.stringify(exp, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const date = new Date().toISOString().split('T')[0];
  a.href = url;
  a.download = `pock-backup-${date}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- Sync (opt-in) — cf. sync/README.md ----------
// One JSON blob per app on a personal server (Bearer token, configured
// from the hub). localStorage stays the source for the UI and offline:
// pull on load, debounced push on change, last-write-wins per app.
// Without pock-sync-url + pock-sync-token configured, nothing runs.

const POCK_SYNC_APPS = { km: 'pock-km-', covoit: 'pock-covoit-', biblio: 'pock-biblio-', hta: 'pock-hta-' };
// Apps PRIVÉES (par-appareil) : leur blob serveur est suffixé d'un id d'appareil
// aléatoire stable → chaque appareil a son propre blob, jamais partagé entre
// users/devices, mais toujours sauvegardé (le dump serveur ramasse tout). Les
// apps absentes d'ici sont PARTAGÉES : un seul blob commun à tous (km/covoit/
// biblio). HTA = santé, propre à l'appareil de saisie. Un seul token suffit :
// le cloisonnement vient du nom de blob, pas du scope du token.
const POCK_SYNC_PRIVATE = { hta: true };
const POCK_SYNC_DEBOUNCE_MS = 1500;

// Id d'appareil aléatoire stable (local, jamais synchronisé : la clé
// 'pock-device' ne matche aucun préfixe d'app donc n'est ni collectée ni
// écrasée par la sync).
function pockDeviceId() {
  let id = localStorage.getItem('pock-device');
  if (!id) {
    const a = new Uint8Array(6);
    (self.crypto || window.crypto).getRandomValues(a);
    id = Array.from(a, b => b.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('pock-device', id);
  }
  return id;
}

// Nom du blob serveur : suffixé de l'id d'appareil pour les apps privées.
function pockSyncBlob(app) {
  return POCK_SYNC_PRIVATE[app] ? app + '-' + pockDeviceId() : app;
}
let pockSyncApplying = false;
const pockSyncTimers = {};

function pockSyncConfig() {
  const url = localStorage.getItem('pock-sync-url');
  const token = localStorage.getItem('pock-sync-token');
  if (!url || !token) return null;
  return { url: url.replace(/\/+$/, ''), token: token };
}

function pockSyncMeta() {
  try { return JSON.parse(localStorage.getItem('pock-sync-meta')) || {}; }
  catch (_) { return {}; }
}

function pockSyncAppFor(key) {
  for (const app in POCK_SYNC_APPS) {
    if (key.indexOf(POCK_SYNC_APPS[app]) === 0) return app;
  }
  return null;
}

function pockSyncCollect(app) {
  const prefix = POCK_SYNC_APPS[app];
  const data = {};
  pockListKeys().forEach(k => {
    if (k.indexOf(prefix) === 0) data[k] = localStorage.getItem(k);
  });
  return data;
}

function pockSyncRequest(cfg, method, app, body, keepalive) {
  const opts = {
    method: method,
    headers: { 'Authorization': 'Bearer ' + cfg.token },
    keepalive: !!keepalive
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch(cfg.url + '/pock/' + pockSyncBlob(app), opts);
}

function pockSyncPush(app, keepalive) {
  const cfg = pockSyncConfig();
  if (!cfg) return Promise.resolve();
  const blob = { version: 1, updatedAt: pockSyncMeta()[app] || Date.now(), data: pockSyncCollect(app) };
  return pockSyncRequest(cfg, 'PUT', app, blob, keepalive)
    .catch(() => { /* offline / serveur down : sync différée, re-push au prochain load */ });
}

function pockSyncMarkDirty(app) {
  if (pockSyncApplying || !pockSyncConfig()) return;
  const meta = pockSyncMeta();
  meta[app] = Date.now();
  localStorage.setItem('pock-sync-meta', JSON.stringify(meta));
  clearTimeout(pockSyncTimers[app]);
  pockSyncTimers[app] = setTimeout(() => {
    pockSyncTimers[app] = null;
    pockSyncPush(app);
  }, POCK_SYNC_DEBOUNCE_MS);
}

// Hook every localStorage write so any save path in any app marks its
// group dirty — no per-app wiring, new save sites are covered for free.
// Guard on `this` so sessionStorage is untouched.
(function () {
  const origSet = Storage.prototype.setItem;
  const origRemove = Storage.prototype.removeItem;
  Storage.prototype.setItem = function (k, v) {
    origSet.call(this, k, v);
    if (this === window.localStorage) {
      const app = pockSyncAppFor(String(k));
      if (app) pockSyncMarkDirty(app);
    }
  };
  Storage.prototype.removeItem = function (k) {
    origRemove.call(this, k);
    if (this === window.localStorage) {
      const app = pockSyncAppFor(String(k));
      if (app) pockSyncMarkDirty(app);
    }
  };
})();

// Replace the local group keys with the remote ones. Returns true if
// anything actually changed (drives the one-shot reload).
function pockSyncApply(app, data) {
  const current = pockSyncCollect(app);
  if (JSON.stringify(current) === JSON.stringify(data)) return false;
  pockSyncApplying = true;
  try {
    Object.keys(current).forEach(k => localStorage.removeItem(k));
    Object.keys(data).forEach(k => {
      if (typeof data[k] === 'string' && pockSyncAppFor(k) === app) localStorage.setItem(k, data[k]);
    });
  } finally {
    pockSyncApplying = false;
  }
  return true;
}

async function pockSyncPullAll() {
  const cfg = pockSyncConfig();
  if (!cfg) return;
  let changed = false;
  for (const app in POCK_SYNC_APPS) {
    try {
      const resp = await pockSyncRequest(cfg, 'GET', app);
      if (resp.status === 404) {
        // Pas encore de blob serveur : pousser l'état local s'il existe
        if (Object.keys(pockSyncCollect(app)).length) pockSyncMarkDirty(app);
        continue;
      }
      if (!resp.ok) continue;
      const blob = await resp.json();
      const remoteAt = blob.updatedAt || 0;
      const localAt = pockSyncMeta()[app] || 0;
      if (remoteAt > localAt) {
        if (pockSyncApply(app, blob.data || {})) changed = true;
        const meta = pockSyncMeta();
        meta[app] = remoteAt;
        localStorage.setItem('pock-sync-meta', JSON.stringify(meta));
      } else if (localAt > remoteAt) {
        pockSyncMarkDirty(app);
      }
    } catch (_) { /* offline / serveur down : l'app reste 100 % fonctionnelle */ }
  }
  // Les apps rendent depuis localStorage au chargement : si le pull a
  // appliqué des données plus récentes, un reload unique les affiche.
  // Garde sessionStorage contre toute boucle.
  if (changed && !sessionStorage.getItem('pock-sync-reloaded')) {
    sessionStorage.setItem('pock-sync-reloaded', '1');
    window.location.reload();
  } else if (!changed) {
    sessionStorage.removeItem('pock-sync-reloaded');
  }
}

// Mobile usage = open, add an entry, close: flush pending pushes when
// the tab goes hidden so the debounce can't swallow the last write.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'hidden') return;
  for (const app in pockSyncTimers) {
    if (pockSyncTimers[app]) {
      clearTimeout(pockSyncTimers[app]);
      pockSyncTimers[app] = null;
      pockSyncPush(app, true);
    }
  }
});

pockSyncPullAll();

// État propre à l'appareil, jamais restauré depuis un export : un vieux
// pock-sync-meta écraserait les timestamps posés par l'import (la sync
// ré-écraserait alors les données importées), et un pock-device importé
// ferait partager le blob privé (hta) entre deux appareils.
const POCK_DEVICE_LOCAL = { 'pock-device': true, 'pock-sync-meta': true };

function pockImportFromJSON(json, mode) {
  mode = mode || 'merge'; // 'merge' | 'replace'
  let obj;
  try { obj = typeof json === 'string' ? JSON.parse(json) : json; }
  catch (_) { throw new Error('JSON invalide'); }
  if (!obj || typeof obj !== 'object' || !obj.data || typeof obj.data !== 'object') {
    throw new Error('Format invalide — ce fichier ne ressemble pas à un export Pock');
  }
  if (mode === 'replace') {
    pockListKeys().forEach(k => { if (!POCK_DEVICE_LOCAL[k]) localStorage.removeItem(k); });
  }
  let count = 0;
  Object.entries(obj.data).forEach(([k, v]) => {
    if (typeof k === 'string' && k.startsWith(POCK_PREFIX) && !POCK_DEVICE_LOCAL[k] && typeof v === 'string') {
      localStorage.setItem(k, v);
      count++;
    }
  });
  return count;
}
