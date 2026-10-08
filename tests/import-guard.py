#!/usr/bin/env python3
"""Garde d'entrée de common.js : un import ou un blob de sync dont un champ
interpolé brut (id, color, bg, date, startDate, km) peut sortir de sa chaîne
JS ou de son attribut est refusé AVANT toute écriture.

Contrôle positif : les formats réels des apps passent (ids « vehicule-1 » et
genId, couleurs #rrggbb, dates ISO du km ET « 08/10/2026 » de covoiturage).
Contre l'ancien common.js, les cas « refusé » échouent (rien ne bloquait).
Usage: python3 tests/import-guard.py [repo_dir]
"""
import json, os, sys
from playwright.sync_api import sync_playwright
from browser_guard import ensure as _ensure_browser

_ensure_browser()
ENGINE = os.environ.get("PWA_ENGINES", "chromium").split(",")[0].strip()
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def blob(**data):
    return json.dumps({"version": 1, "data": {k: json.dumps(v) for k, v in data.items()}})

LEGIT = blob(**{
    "pock-km-vehicles": [{"id": "vehicule-1", "name": "Clio \"rouge\" (2024)", "color": "#3563e9",
                          "startDate": "2024-01-01", "durationMonths": 37}],
    "pock-km-vehicule-1": [{"id": "mgk1x2abcde", "date": "2026-10-01", "km": 12345}],
    "pock-covoit-history": [{"date": "08/10/2026", "total": 42}],
    "pock-biblio-books": [{"id": "lq3abcd12", "title": "L'été <i>", "status": "read", "addedAt": 1}],
})
EVIL = {
    "id quote":   blob(**{"pock-km-vehicles": [{"id": "x');alert(1);('", "color": "#fff"}]}),
    "color css":  blob(**{"pock-km-vehicles": [{"id": "v", "color": "red;background:url(//e)"}]}),
    "date attr":  blob(**{"pock-km-v": [{"id": "e", "date": "2026-01-01\" onfocus=\"alert(1)", "km": 1}]}),
    "km code":    blob(**{"pock-km-v": [{"id": "e", "date": "2026-01-01", "km": "1);alert(1);//"}]}),
    "nested id":  blob(**{"pock-hta-measures": [{"id": "ok", "cycles": [{"id": "<img src=x>"}]}]}),
}

fail = 0
def check(cond, msg):
    global fail
    print(("ok   " if cond else "FAIL ") + msg)
    fail |= not cond

with sync_playwright() as p:
    b = getattr(p, ENGINE).launch()
    pg = b.new_page()
    pg.goto(f"file://{repo}/index.html")
    imp = """(t) => { localStorage.clear();
        try { return {n: pockImportFromJSON(t, 'merge'), keys: localStorage.length}; }
        catch (e) { return {err: e.message, keys: localStorage.length}; } }"""
    r = pg.evaluate(imp, LEGIT)
    check(r.get("n") == 4, f"A import légitime accepté (formats réels des apps) : {r}")
    for name, t in EVIL.items():
        r = pg.evaluate(imp, t)
        check("err" in r and r["keys"] == 0, f"B import refusé sans rien écrire — {name} : {r}")
    # replace : un fichier refusé n'efface pas les données en place
    r = pg.evaluate("""(t) => { localStorage.clear(); localStorage.setItem('pock-km-keep', '[]');
        try { pockImportFromJSON(t, 'replace'); } catch (_) {}
        return localStorage.getItem('pock-km-keep'); }""", EVIL["id quote"])
    check(r == "[]", "C replace refusé : données locales intactes")
    # sync : blob partagé dangereux non appliqué
    r = pg.evaluate("""(d) => { localStorage.clear(); localStorage.setItem('pock-km-vehicles', '[]');
        const changed = pockSyncApply('km', d);
        return {changed, v: localStorage.getItem('pock-km-vehicles')}; }""",
                    json.loads(EVIL["id quote"])["data"])
    check(r["changed"] is False and r["v"] == "[]", f"D blob de sync dangereux ignoré : {r}")
    b.close()

print("import-guard : OK" if not fail else "import-guard : ECHEC")
sys.exit(fail)
