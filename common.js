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

// Champs que les apps interpolent BRUTS dans du HTML : onclick="f('${x.id}')",
// style="color:${x.color}", value="${e.date}", startEdit(…,${e.km},…). esc()
// n'y est pas appliqué (~30 sites) ; on garde donc la FRONTIÈRE : tout ce qui
// entre depuis l'extérieur (import de fichier, blob de sync partagé) est refusé
// si l'un de ces champs peut sortir de sa chaîne ou de son attribut. Liste
// blanche de caractères, pas de format : les dates de covoiturage sont en
// « 08/10/2026 », celles du km en ISO — seuls guillemets, parenthèses, ; < > &
// \ ` = sont exclus.
const POCK_SAFE_FIELDS = { id: 1, color: 1, bg: 1, date: 1, startDate: 1 };
const POCK_SAFE_RE = /^[A-Za-z0-9 _#.\/:+-]{0,64}$/;
const POCK_NUM_RE = /^-?\d+(\.\d+)?$/;

// Chemin du premier champ dangereux d'une valeur localStorage, ou null si sûre.
function pockUnsafeField(str) {
  let v;
  try { v = JSON.parse(str); } catch (_) { return null; } // scalaire brut : jamais interpolé
  const walk = (o, path) => {
    if (!o || typeof o !== 'object') return null;
    for (const k of Object.keys(o)) {
      const x = o[k], at = path + (Array.isArray(o) ? '[' + k + ']' : '.' + k);
      if (x != null && POCK_SAFE_FIELDS[k] && typeof x !== 'number'
          && !(typeof x === 'string' && POCK_SAFE_RE.test(x))) return at;
      if (x != null && k === 'km' && !(typeof x === 'number' && isFinite(x))
          && !(typeof x === 'string' && (x === '' || POCK_NUM_RE.test(x)))) return at;
      const r = walk(x, at);
      if (r) return r;
    }
    return null;
  };
  return walk(v, '');
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
  pockListKeys().forEach(k => { if (!POCK_DEVICE_LOCAL[k]) data[k] = localStorage.getItem(k); });
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
// pull on load, debounced push on change; conditional writes + 3-way
// merge so two devices never erase each other's entries.
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

// État de sync par app, propre à l'appareil (jamais exporté ni synchronisé) :
//   base  = updatedAt de la dernière version serveur connue (null : pas de blob)
//   snap  = les données de cette version — ancêtre commun de la fusion
//   dirty = modifs locales pas encore poussées
// App absente = jamais synchronisée sur cet appareil (ou état d'avant le
// 2026-10-11) : sa 1ʳᵉ sync FUSIONNE local et serveur, rien n'est effacé.
function pockSyncState() {
  try { return JSON.parse(localStorage.getItem('pock-sync-state')) || {}; }
  catch (_) { return {}; }
}

function pockSyncSaveState(app, st) {
  const all = pockSyncState();
  all[app] = st;
  localStorage.setItem('pock-sync-state', JSON.stringify(all));
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

// Égalité de deux jeux { clé: chaîne } indépendante de l'ordre des clés.
function pockSyncSame(a, b) {
  const ka = Object.keys(a), kb = Object.keys(b);
  return ka.length === kb.length && ka.every(k => a[k] === b[k]);
}

// Fusion à 3 voies (b = version commune) : ce qu'un seul côté a changé est
// gardé ; les deux côtés ont changé ⇒ `both`, ou le serveur par défaut.
function pockSyncMerge3(b, l, r, both) {
  if (l === r) return l;
  if (l === b) return r;
  if (r === b) return l;
  return both ? both(b, l, r) : r;
}

// Même clé changée des deux côtés : si ce sont des listes d'objets à `id`
// (véhicules, relevés km, mesures, cycles, livres…), fusion élément par
// élément — deux saisies concurrentes sont toutes deux gardées, une
// suppression d'un côté s'applique si l'autre n'a pas modifié l'élément.
// Sinon (réglage scalaire) le serveur l'emporte.
function pockSyncMergeLists(b, l, r) {
  const byId = s => {
    let a;
    try { a = JSON.parse(s === undefined ? '[]' : s); } catch (_) { return null; }
    if (!Array.isArray(a) || !a.every(x => x && typeof x === 'object' && 'id' in x)) return null;
    return new Map(a.map(x => [String(x.id), JSON.stringify(x)]));
  };
  const mb = byId(b), ml = byId(l), mr = byId(r);
  if (!mb || !ml || !mr) return r;
  const out = [];
  new Set([...ml.keys(), ...mr.keys()]).forEach(id => {
    const v = pockSyncMerge3(mb.get(id), ml.get(id), mr.get(id));
    if (v !== undefined) out.push(JSON.parse(v));
  });
  return JSON.stringify(out);
}

function pockSyncMerge(base, local, remote) {
  const out = {};
  new Set([...Object.keys(local), ...Object.keys(remote)]).forEach(k => {
    const v = pockSyncMerge3(base[k], local[k], remote[k], pockSyncMergeLists);
    if (v !== undefined) out[k] = v;
  });
  return out;
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

// Écriture conditionnelle : `base` dit au serveur sur quelle version on a
// travaillé ; s'il a bougé entre-temps (autre appareil) → 409 → on relit et
// on fusionne au lieu d'écraser. `depth` borne la boucle 409 → relecture.
function pockSyncPush(app, keepalive, depth) {
  const cfg = pockSyncConfig();
  if (!cfg) return Promise.resolve();
  const st = pockSyncState()[app];
  if (!st || !('base' in st)) return pockSyncRun(app, depth); // jamais synchronisée : fusionner d'abord
  const data = pockSyncCollect(app);
  const updatedAt = Math.max(Date.now(), (st.base || 0) + 1);
  return pockSyncRequest(cfg, 'PUT', app, { version: 2, base: st.base, updatedAt: updatedAt, data: data }, keepalive)
    .then(resp => {
      if (resp.status === 409 && (depth || 0) < 3) {
        return pockSyncRun(app, (depth || 0) + 1).then(changed => { if (changed) pockSyncReload(); });
      }
      if (!resp.ok) return;
      pockSyncSaveState(app, { base: updatedAt, snap: data, dirty: !pockSyncSame(pockSyncCollect(app), data) });
    })
    .catch(() => { /* offline / serveur down : dirty reste, re-push au prochain load */ });
}

function pockSyncMarkDirty(app) {
  if (pockSyncApplying || !pockSyncConfig()) return;
  const st = pockSyncState()[app] || {};
  if (!st.dirty) { st.dirty = true; pockSyncSaveState(app, st); }
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

// Replace the local group keys with `data`. Returns true if anything
// actually changed (drives the reload).
// Blob partagé = entrée externe : un seul champ dangereux et rien n'est
// appliqué (le local reste, et remplace le blob au push qui suit).
function pockSyncUnsafe(app, data) {
  for (const k of Object.keys(data)) {
    const bad = typeof data[k] === 'string' && pockUnsafeField(data[k]);
    if (bad) { console.warn('pock sync: blob ' + app + ' refusé (' + k + bad + ')'); return true; }
  }
  return false;
}

function pockSyncApply(app, data) {
  const current = pockSyncCollect(app);
  if (pockSyncSame(current, data) || pockSyncUnsafe(app, data)) return false;
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

// Un cycle pour une app : relire le serveur, fusionner si un autre appareil
// a écrit depuis notre dernière sync, pousser s'il reste du local. Renvoie
// true si les données locales ont changé (la page doit recharger).
async function pockSyncRun(app, depth) {
  const cfg = pockSyncConfig();
  if (!cfg) return false;
  let remote = null;
  try {
    const resp = await pockSyncRequest(cfg, 'GET', app);
    if (resp.status !== 404) {
      if (!resp.ok) return false;
      remote = await resp.json();
    }
  } catch (_) { return false; } // offline / serveur down : l'app reste 100 % fonctionnelle
  const st = pockSyncState()[app];
  const synced = !!st && 'base' in st;
  const local = pockSyncCollect(app);
  const remoteAt = remote ? remote.updatedAt : null;
  if (synced && st.base === remoteAt) {            // serveur inchangé depuis notre dernière sync
    if (st.dirty) await pockSyncPush(app, false, depth);
    return false;
  }
  if (!remote) {                                    // pas (plus) de blob : pousser le local
    if (Object.keys(local).length) {
      pockSyncSaveState(app, { base: null, snap: {}, dirty: true });
      await pockSyncPush(app, false, depth);
    }
    return false;
  }
  const remoteData = remote.data || {};
  const merged = pockSyncUnsafe(app, remoteData) ? local
    : (synced && !st.dirty) ? remoteData
    : pockSyncMerge((synced && st.snap) || {}, local, remoteData);
  const changed = pockSyncApply(app, merged);
  const dirty = !pockSyncSame(merged, remoteData);
  pockSyncSaveState(app, { base: remoteAt, snap: remoteData, dirty: dirty });
  if (dirty) await pockSyncPush(app, false, depth);
  return changed;
}

// Les apps rendent depuis localStorage au chargement et gardent leurs données
// en mémoire : après une fusion, recharger — sinon la prochaine sauvegarde
// repartirait de la copie en mémoire. Garde anti-boucle : 1 reload / 10 s.
function pockSyncReload() {
  const last = +sessionStorage.getItem('pock-sync-reloaded') || 0;
  if (Date.now() - last < 10000) return;
  sessionStorage.setItem('pock-sync-reloaded', String(Date.now()));
  window.location.reload();
}

async function pockSyncPullAll() {
  if (!pockSyncConfig()) return;
  let changed = false;
  for (const app in POCK_SYNC_APPS) {
    if (await pockSyncRun(app)) changed = true;
  }
  if (changed) pockSyncReload();
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

// État propre à l'appareil, ni exporté ni restauré par un import : un vieil
// état de sync ferait croire l'appareil à jour (la sync écraserait alors les
// données importées), un pock-device importé ferait partager le blob privé
// (hta) entre deux appareils, et le token de sync dans un fichier de
// sauvegarde partagé ouvrirait tous les blobs (audit 2026-10-11).
// pock-sync-meta : état d'avant 2026-10-11.
const POCK_DEVICE_LOCAL = {
  'pock-device': true, 'pock-sync-state': true, 'pock-sync-meta': true,
  'pock-sync-url': true, 'pock-sync-token': true
};

function pockImportFromJSON(json, mode) {
  mode = mode || 'merge'; // 'merge' | 'replace'
  let obj;
  try { obj = typeof json === 'string' ? JSON.parse(json) : json; }
  catch (_) { throw new Error('JSON invalide'); }
  if (!obj || typeof obj !== 'object' || !obj.data || typeof obj.data !== 'object') {
    throw new Error('Format invalide — ce fichier ne ressemble pas à un export Pock');
  }
  // Validé AVANT toute écriture (et avant l'effacement du mode replace).
  for (const [k, v] of Object.entries(obj.data)) {
    const bad = typeof v === 'string' && pockUnsafeField(v);
    if (bad) throw new Error('Import refusé — champ non sûr : ' + k + bad);
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
