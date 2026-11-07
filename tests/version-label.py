#!/usr/bin/env python3
"""
Épingle la version que l'on VOIT (pied de page `#pockVersion` de chaque app,
bandeau `#pockUpdated`, ligne « Version » du panneau État du hub) et le parser
derrière (common.js, `pockVersionLabel`). Même modèle que
plex-jqh-omv/tests/version-footer-e2e.py.

Trois couches, exprès :

  A. PARSER — `pockVersionLabel(names)` sur des listes de caches synthétiques :
     ce qu'un run réel ne sait pas mettre en scène (ancien et nouveau cache qui
     coexistent à l'update, `pock-v9` vs `pock-v52`, cache étranger, déchets).
  B. RENDU — les 5 pages sur http (un SW exige une vraie origine), SW activé,
     le pied de page dit « Pock <libellé attendu dérivé de sw.js> ». A peut
     être vert pendant que le pied de page reste « Pock — ».
  C. BANDEAU — 1re visite : aucun bandeau ; version vue différente : bandeau
     « mis à jour … (avant : …) » ; visite suivante : plus de bandeau. Et la
     clé d'appareil ne part ni dans l'export ni dans la sync.

Lancer : python3 tests/version-label.py
"""

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
        "() => (document.getElementById('pockVersion')||{}).textContent !== 'Pock —'",
        timeout=10000)
    return page.text_content("#pockVersion")


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
        check(page.query_selector("#pockUpdated") is None,
              f"{fname} 1re visite : pas de bandeau")
        if fname == "index.html":
            diag = page.text_content("#diagVersion")
            check(diag == f"Version : {EXPECTED}", f"panneau État → {diag!r}")
        ctx.close()

    # C. Bandeau de mise à jour
    ctx = b.new_context()
    page = ctx.new_page()
    page.goto(f"{base}/suivi-km-loa.html")
    footer(page)
    page.wait_for_function("() => localStorage.getItem('pockVersionSeen')")
    page.evaluate("localStorage.setItem('pockVersionSeen', 'v52')")
    page.reload()
    page.wait_for_selector("#pockUpdated", timeout=10000)
    txt = page.text_content("#pockUpdated")
    check(txt == f"Pock mis à jour : {EXPECTED} (avant : v52)", f"bandeau → {txt!r}")
    exported = page.evaluate("JSON.stringify(pockExportAll())")
    check("pockVersionSeen" not in exported, "clé de version absente de l'export")
    check(page.evaluate("pockSyncAppFor('pockVersionSeen')") is None,
          "clé de version hors sync")
    page.reload()
    footer(page)
    page.wait_for_timeout(500)
    check(page.query_selector("#pockUpdated") is None, "visite suivante : plus de bandeau")
    ctx.close()
    b.close()

print(f"\n{'FAIL' if fails else 'OK'} — {len(fails)} échec(s) ; version attendue {EXPECTED}")
sys.exit(1 if fails else 0)
