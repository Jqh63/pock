#!/usr/bin/env python3
"""
Épingle la version que l'on VOIT (pied de page `#pockVersion` de chaque app,
marques ✓ `#pockLatest` / ⟳ `#pockNewer` / ✦ `#pockUpdated`, ligne « Version » du panneau État du hub) et le parser
derrière (common.js, `pockVersionLabel`). Même modèle que
plex-jqh-omv/tests/version-footer-e2e.py.

Quatre couches, exprès :

  A. PARSER — `pockVersionLabel(names)` sur des listes de caches synthétiques :
     ce qu'un run réel ne sait pas mettre en scène (ancien et nouveau cache qui
     coexistent à l'update, `pock-v9` vs `pock-v52`, cache étranger, déchets).
  B. RENDU — les 5 pages sur http (un SW exige une vraie origine), SW activé,
     le pied de page dit « Pock <libellé attendu dérivé de sw.js> ». A peut
     être vert pendant que le pied de page reste « Pock — ».
  C. ICÔNE ✦ — la règle `pockVersionState` (1re visite, changement, fenêtre
     de 24 h, valeur brute d'avant le 2026-11-07b), puis le rendu : version
     vue différente ⇒ ✦ + détail au toucher, encore là au lancement suivant,
     partie après 24 h. La clé d'appareil ne part ni dans l'export ni dans la
     sync.
  D. ✓ / ⟳ — la règle `pockLatestState`, puis le rendu face à un serveur simulé
     (fetch de sw.js no-store remplacé dans la page) : identique ⇒ ✓ seul ;
     plus récent ⇒ ⟳ seul ; hors ligne ou serveur en retard ⇒ aucune marque
     (jamais de ✓ sans verdict).
  E. CONTRASTE des marques ✦ et ✓ (AA 4.5:1), 5 pages × clair/sombre :
     contrast.py ne les voit jamais (elles n'apparaissent qu'après une mise à
     jour) ; le ✦ en --accent de hta tombait à 2.3:1.

Lancer : python3 tests/version-label.py
"""

import json
import re
import sys
from pathlib import Path

from browser_guard import ensure as _ensure_browser

_ensure_browser()

from playwright.sync_api import sync_playwright  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke import APPS, serve_repo  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
m = re.search(r"const CACHE_NAME = '(pock-v(\d+)-(\d{4}-\d{2}-\d{2}[a-z]?))'",
              (REPO / "sw.js").read_text())
if not m:
    sys.exit("FAIL sw.js — CACHE_NAME hors format pock-v<gén>-<YYYY-MM-DD>[a-z]")
EXPECTED = f"v{m.group(2)} · {m.group(3)}"

PARSER_CASES = [
    (["pock-v1-2026-11-07a"], "v1 · 2026-11-07a"),
    (["pock-v52", "pock-v1-2026-11-07a"], "v1 · 2026-11-07a"),   # transition
    (["pock-v1-2026-11-07a", "pock-v52"], "v1 · 2026-11-07a"),   # ordre inverse
    (["pock-v9", "pock-v52"], "v52"),                            # tri numérique
    (["pock-v1-2026-11-07a", "pock-v1-2026-11-07b"], "v1 · 2026-11-07b"),
    (["pock-v1-2026-11-07b", "pock-v1-2026-11-08"], "v1 · 2026-11-08"),
    (["autre-cache", "pock-v1-2026-11-07a"], "v1 · 2026-11-07a"),
    (["autre-cache", "pock-vX", "pock-v1-2026-1-7"], None),
    ([], None),
    ([42, None], None),
]

fails = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def footer(page):
    page.wait_for_function(
        "() => (document.getElementById('pockVersionText')||{}).textContent !== 'Pock —'",
        timeout=10000)
    return page.text_content("#pockVersionText")


def shown(page, sel):
    return page.evaluate(
        "s => { const e = document.querySelector(s); return !!e && !e.hidden; }", sel)


# Serveur simulé : remplace la réponse de fetch('./sw.js', {cache:'no-store'})
# (la vérification ✓/⟳) sans toucher à l'enregistrement du SW, qui ne passe
# pas par window.fetch. __srv : nom servi, 'OFFLINE' = rejet réseau.
FAKE_SERVER = """
const realFetch = window.fetch;
window.fetch = function (u, o) {
  if (String(u).indexOf('sw.js') >= 0 && o && o.cache === 'no-store' && window.__srv) {
    if (window.__srv === 'OFFLINE') return Promise.reject(new TypeError('offline'));
    return Promise.resolve(new Response("const CACHE_NAME = '" + window.__srv + "';"));
  }
  return realFetch.apply(this, arguments);
};
"""


with serve_repo() as base, sync_playwright() as p:
    b = p.chromium.launch()

    # A. Parser
    ctx = b.new_context()
    page = ctx.new_page()
    page.goto(f"{base}/index.html")
    for names, want in PARSER_CASES:
        got = page.evaluate("n => pockVersionLabel(n)", names)
        check(got == want, f"parser {names} → {got!r} (attendu {want!r})")
    ctx.close()

    # B. Rendu sur chaque page, contexte neuf = 1re visite (SW pas encore là)
    for fname in APPS:
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto(f"{base}/{fname}")
        got = footer(page)
        check(got == f"Pock {EXPECTED}", f"pied de page {fname} → {got!r}")
        check(not shown(page, "#pockUpdated"), f"{fname} 1re visite : pas de ✦")
        page.wait_for_function("() => !document.getElementById('pockLatest').hidden",
                               timeout=10000)
        check(not shown(page, "#pockNewer"), f"{fname} : ✓ (serveur = local), pas de ⟳")
        if fname == "index.html":
            # Le panneau se recalcule à l'ouverture : l'ouvrir comme un humain
            # (lu au chargement, il peut précéder le cache à la 1re visite).
            page.click("#dataToggle")
            page.wait_for_function(
                "() => document.getElementById('diagVersion').textContent !== 'Version : —'")
            diag = page.text_content("#diagVersion")
            check(diag == f"Version : {EXPECTED}", f"panneau État → {diag!r}")
        ctx.close()

    # C. Icône ✦ — règle pure
    ctx = b.new_context()
    page = ctx.new_page()
    page.goto(f"{base}/index.html")
    H = 3600 * 1000
    L, OLD = "v1 · 2026-11-07b", "v1 · 2026-11-07a"
    fresh = json.dumps({"label": L, "prev": OLD, "at": 0})
    STATE_CASES = [
        ("1re visite", None, 0, {"store": {"label": L}, "updated": None}),
        ("valeur illisible", "{}", 0, {"store": {"label": L}, "updated": None}),
        ("ancienne valeur brute", OLD, 5,
         {"store": {"label": L, "prev": OLD, "at": 5}, "updated": {"prev": OLD, "at": 5}}),
        ("changement", json.dumps({"label": OLD}), 7,
         {"store": {"label": L, "prev": OLD, "at": 7}, "updated": {"prev": OLD, "at": 7}}),
        ("même version, < 24 h", fresh, 23 * H,
         {"store": None, "updated": {"prev": OLD, "at": 0}}),
        ("même version, 24 h passées", fresh, 24 * H, {"store": None, "updated": None}),
        ("même version, jamais mise à jour", json.dumps({"label": L}), 9,
         {"store": None, "updated": None}),
    ]
    for name, raw, now, want in STATE_CASES:
        got = page.evaluate("([r, l, n]) => pockVersionState(r, l, n)", [raw, L, now])
        check(got == want, f"règle {name} → {got}")
    ctx.close()

    # C. Icône ✦ — rendu
    ctx = b.new_context()
    page = ctx.new_page()
    page.goto(f"{base}/suivi-km-loa.html")
    footer(page)
    page.wait_for_function("() => localStorage.getItem('pockVersionSeen')")
    page.evaluate("localStorage.setItem('pockVersionSeen', JSON.stringify({label: 'v52'}))")
    page.reload()
    page.wait_for_selector("#pockUpdated:not([hidden])", timeout=10000)
    check(True, "✦ à côté de la version")
    page.click("#pockUpdated")
    det = page.text_content("#pockVersionDetail")
    check(det.startswith("Mis à jour le ") and det.endswith("— avant : v52"),
          f"détail au toucher → {det!r}")
    exported = page.evaluate("JSON.stringify(pockExportAll())")
    check("pockVersionSeen" not in exported, "clé de version absente de l'export")
    check(page.evaluate("pockSyncAppFor('pockVersionSeen')") is None,
          "clé de version hors sync")
    page.reload()
    footer(page)
    page.wait_for_timeout(500)
    check(shown(page, "#pockUpdated"), "lancement suivant : ✦ toujours là")
    page.evaluate("""() => {
        const s = JSON.parse(localStorage.getItem('pockVersionSeen'));
        s.at -= 24 * 3600 * 1000;
        localStorage.setItem('pockVersionSeen', JSON.stringify(s));
    }""")
    page.reload()
    footer(page)
    page.wait_for_timeout(500)
    check(not shown(page, "#pockUpdated"), "après 24 h : plus de ✦")
    ctx.close()

    # D. ✓ / ⟳ — règle pure
    ctx = b.new_context()
    page = ctx.new_page()
    page.goto(f"{base}/index.html")
    A, B_, LEG = "pock-v1-2026-11-07a", "pock-v1-2026-11-07b", "pock-v52"
    LATEST_CASES = [
        ("identique", A, A, "latest"),
        ("serveur plus récent", A, B_, "newer"),
        ("serveur en retard (CDN)", B_, A, None),
        ("transition pock-vN → daté", LEG, A, "newer"),
        ("serveur illisible", A, None, None),
        ("aucun cache local", None, A, None),
        ("nom étranger", A, "autre", None),
    ]
    for name, cur, srv, want in LATEST_CASES:
        got = page.evaluate("([c, s]) => pockLatestState(c, s)", [cur, srv])
        check(got == want, f"règle ✓/⟳ {name} → {got!r}")
    ctx.close()

    # D. ✓ / ⟳ — rendu face au serveur simulé
    LOCAL = m.group(1)
    for name, srv, want_ok, want_new in [
        ("serveur identique", LOCAL, True, False),
        ("serveur plus récent", "pock-v1-2099-01-01", False, True),
        ("hors ligne", "OFFLINE", False, False),
        ("serveur en retard", "pock-v1-2000-01-01", False, False),
    ]:
        ctx = b.new_context()
        ctx.add_init_script(FAKE_SERVER + f"window.__srv = {json.dumps(srv)};")
        page = ctx.new_page()
        page.goto(f"{base}/suivi-km-loa.html")
        footer(page)
        page.evaluate("() => navigator.serviceWorker.ready")
        page.wait_for_timeout(800)
        ok, new = shown(page, "#pockLatest"), shown(page, "#pockNewer")
        check((ok, new) == (want_ok, want_new), f"{name} → ✓={ok} ⟳={new}")
        if new:
            t = page.get_attribute("#pockNewer", "title")
            check(t == "Version plus récente publiée : v1 · 2099-01-01 — chargement en cours",
                  f"détail ⟳ → {t!r}")
        if ok:
            t = page.get_attribute("#pockLatest", "title")
            check(t.startswith("Dernière version publiée (vérifié à "), f"détail ✓ → {t!r}")
        ctx.close()
    b.close()

    # E. Contraste des marques, ✦ forcé visible
    RATIO = """id => { const P = s => s.match(/[\\d.]+/g).map(Number);
      const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92
                         : ((v + 0.055) / 1.055) ** 2.4; };
                         return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
      let bg = [255, 255, 255];
      for (let x = document.getElementById('pockVersion'); x; x = x.parentElement) {
        const c = P(getComputedStyle(x).backgroundColor);
        if (c.length < 4 || c[3] > 0) { bg = c; break; } }
      const a = lum(P(getComputedStyle(document.getElementById(id)).color)), b = lum(bg);
      return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }"""
    b = p.chromium.launch()
    for scheme in ("light", "dark"):
        for fname in APPS:
            ctx = b.new_context(color_scheme=scheme)
            page = ctx.new_page()
            page.goto(f"{base}/{fname}")
            page.wait_for_function("() => localStorage.getItem('pockVersionSeen')")
            page.evaluate("localStorage.setItem('pockVersionSeen', JSON.stringify({label: 'v0'}))")
            page.reload()
            page.wait_for_selector("#pockUpdated:not([hidden])", timeout=10000)
            for mid in ("pockUpdated", "pockLatest"):
                r = page.evaluate(RATIO, mid)
                check(r >= 4.5, f"contraste {mid} {fname} {scheme} → {r:.2f}")
            ctx.close()
    b.close()

print(f"\n{'FAIL' if fails else 'OK'} — {len(fails)} échec(s) ; version attendue {EXPECTED}")
sys.exit(1 if fails else 0)
