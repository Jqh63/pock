#!/usr/bin/env python3
"""Cas d'usage réels du suivi km (voiture neuve en LOA), horloge figée.

Chaque cas reproduit un geste réel et vérifie que tous les écrans disent la même
chose. Cas 1-7 rouges avant fix/km-coherence, 8-11 avant feat/km-ux (2026-11-07).
Données fictives. Single-engine comme km-anchor.py.
Usage: python3 tests/km-cases.py [repo_dir]
"""
import os, re, sys
from playwright.sync_api import sync_playwright
from browser_guard import ensure as _ensure_browser

_ensure_browser()
ENGINE = os.environ.get("PWA_ENGINES", "chromium").split(",")[0].strip()
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = "2026-11-07T10:00:00+01:00"
fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f" — obtenu : {got}"))
    if not cond:
        fails.append(name)


def vehicle(start, months=37, km_year=10000, rate=0.15):
    return [{"id": "t1", "name": "Voiture", "color": "#3563e9", "startDate": start,
             "durationMonths": months, "kmPerYear": km_year, "excessCostPerKm": rate}]


def num(txt):
    t = txt.replace(" ", "").replace(" ", "").replace(" ", "").replace("−", "-")
    m = re.search(r"[+-]?\d+", t)
    return int(m.group()) if m else None


def open_app(browser, veh, entries, now=NOW):
    ctx = browser.new_context(timezone_id="Europe/Paris", locale="fr-FR")
    pg = ctx.new_page()
    pg.clock.set_fixed_time(now)
    dialogs = []
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    pg.goto(f"file://{repo}/suivi-km-loa.html")
    pg.evaluate("""([v, e]) => {
        localStorage.setItem('pock-km-vehicles', JSON.stringify(v));
        localStorage.setItem('pock-km-active', 't1');
        localStorage.setItem('pock-km-t1', JSON.stringify(e));
    }""", [veh, entries])
    pg.reload()
    return pg, dialogs


def stored(pg):
    return pg.evaluate("JSON.parse(localStorage.getItem('pock-km-t1'))")


with sync_playwright() as p:
    b = getattr(p, ENGINE).launch()

    # 1. Saisie au clavier d'ordinateur avec séparateur de milliers.
    pg, _ = open_app(b, vehicle("2025-03-15"), [])
    pg.fill("#inputKm", "12 345"); pg.click(".qa-btn")
    s = stored(pg)
    check("1a « 12 345 » enregistré 12345", len(s) == 1 and s[0]["km"] == 12345, s)
    pg2, dialogs = open_app(b, vehicle("2025-03-15"), [])
    pg2.fill("#inputKm", "12a45"); pg2.click(".qa-btn")
    check("1b saisie invalide : message, rien d'enregistré",
          stored(pg2) == [] and any("invalide" in d for d in dialogs), (stored(pg2), dialogs))
    pg2.click(".sel-add")
    pg2.fill("#vName", "Neuve"); pg2.fill("#vStart", "2026-10-01")
    pg2.fill("#vMonths", "37"); pg2.fill("#vKmYear", "15 000"); pg2.fill("#vExcessCost", "0,12")
    pg2.click(".btn-dark")
    vs = pg2.evaluate("JSON.parse(localStorage.getItem('pock-km-vehicles'))")
    check("1c véhicule « 15 000 » km/an enregistré 15000", vs[-1]["kmPerYear"] == 15000, vs[-1])

    # 2. Relevé saisi juste après minuit : la date proposée est celle du jour.
    pg, _ = open_app(b, vehicle("2025-03-15"), [], now="2026-11-07T00:30:00+01:00")
    check("2 date par défaut à 00:30 = 2026-11-07", pg.input_value("#inputDate") == "2026-11-07",
          pg.input_value("#inputDate"))

    # 3. Voiture livrée, aucun relevé encore : pas de « marge » inventée.
    pg, _ = open_app(b, vehicle("2025-03-15"), [])
    hero = pg.locator(".hero-delta").inner_text()
    check("3 sans relevé : pas de marge affichée", "marge" not in hero and "aucun relevé" in hero.lower(), hero)

    # 4. Relevé de restitution 3 jours après la fin du contrat (24 mois, 20 000 km).
    pg, _ = open_app(b, vehicle("2023-01-01", months=24), [
        {"id": "a", "date": "2024-12-20", "km": 19500},
        {"id": "b", "date": "2025-01-03", "km": 20100}])
    hero_d = num(pg.locator(".hero-delta-value").inner_text())
    list_d = num(pg.locator(".entry-delta").first.inner_text())
    check("4a restitution : écart liste = écart principal", hero_d == list_d == 100, (hero_d, list_d))
    cx = max(float(c.get_attribute("cx")) for c in pg.locator(".chart-wrap circle").all())
    check("4b restitution : point dans le graphique", cx <= 670.5, cx)

    # 5. Forfait déjà dépassé avant la fin : les deux tuiles disent 0.
    pg, _ = open_app(b, vehicle("2025-01-01"), [{"id": "a", "date": "2026-11-01", "km": 32000}])
    kpis = [num(k.inner_text()) for k in pg.locator(".kpi-value").all()]
    check("5 forfait dépassé : 0 km/jour et 0 km/mois", kpis == [0, 0], kpis)

    # 6. Relevé vieux de 16 mois : tout est daté du relevé, pas d'aujourd'hui.
    pg, _ = open_app(b, vehicle("2025-01-01", rate=0), [{"id": "a", "date": "2025-07-01", "km": 8000}])
    allowed = num(pg.locator(".kpi-value").first.inner_text())
    total_days = (1126)  # 2025-01-01 → 2028-02-01
    exp_allowed = round((30833 - 8000) / (total_days - 181))
    check("6a « Tu peux rouler » calculé depuis le relevé", allowed == exp_allowed, (allowed, exp_allowed))
    # 7. … et l'alerte de relevé ancien s'affiche même sans coût au km.
    body = pg.locator("#app").inner_text()
    check("7 alerte relevé ancien sans coût au km", "il y a 494 j" in body and "mettre à jour" in body, body[:300])

    # 6b. Léger dépassement (+300 km) : barre km rouge comme l'écart principal.
    kpd = 30833 / 1126
    pg, _ = open_app(b, vehicle("2025-01-01"), [{"id": "a", "date": "2026-01-01", "km": round(kpd * 365) + 300}])
    hero_cls = pg.locator(".hero-delta").get_attribute("class")
    bar = pg.locator(".progress-bar").nth(1).get_attribute("style")
    check("6b écart rouge ⇔ barre km rouge", "danger" in hero_cls and "#e5393f" in bar, (hero_cls, bar))

    # 8. Suppression d'un relevé : confirmation, et « Annuler » ne supprime rien.
    ctx = b.new_context(timezone_id="Europe/Paris"); pg = ctx.new_page(); pg.clock.set_fixed_time(NOW)
    asked = []
    pg.on("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    pg.goto(f"file://{repo}/suivi-km-loa.html")
    pg.evaluate("""() => { localStorage.setItem('pock-km-vehicles', JSON.stringify([{id:'t1',name:'V',color:'#3563e9',startDate:'2025-03-15',durationMonths:37,kmPerYear:10000,excessCostPerKm:0.15}]));
        localStorage.setItem('pock-km-active','t1'); localStorage.setItem('pock-km-t1', JSON.stringify([{id:'a',date:'2026-10-01',km:15000}])); }""")
    pg.reload(); pg.click(".entry-actions .del")
    check("8 suppression : confirmation demandée, Annuler garde le relevé",
          len(asked) == 1 and len(stored(pg)) == 1, (asked, stored(pg)))

    # 9. Correction d'un relevé avec une faute de frappe (15000 → 1500).
    pg.evaluate("""() => localStorage.setItem('pock-km-t1', JSON.stringify([{id:'a',date:'2026-09-01',km:14000},{id:'b',date:'2026-10-01',km:15000}]))""")
    pg.reload(); asked.clear()
    pg.locator(".entry").first.locator("button").first.click()  # le plus récent (b)
    pg.fill("#editInput", "1500"); pg.locator(".entry").first.locator("button").first.click()
    check("9 édition : compteur qui baisse ⇒ confirmation, Annuler ne modifie rien",
          len(asked) == 1 and "baisse" in asked[0] and stored(pg)[1]["km"] == 15000, (asked, stored(pg)))

    # 10. Relevé oublié saisi après coup, avec un compteur supérieur au relevé suivant.
    asked.clear()
    pg.fill("#inputDate", "2026-08-01"); pg.fill("#inputKm", "16000"); pg.click(".qa-btn")
    check("10 ajout dans le passé au-dessus du relevé suivant ⇒ confirmation",
          len(asked) == 1 and len(stored(pg)) == 2, (asked, stored(pg)))

    # 11. Mode sombre : la zone de dépassement du graphique n'est pas un aplat clair.
    ctx = b.new_context(color_scheme="dark", timezone_id="Europe/Paris"); pg = ctx.new_page(); pg.clock.set_fixed_time(NOW)
    pg.goto(f"file://{repo}/suivi-km-loa.html")
    pg.evaluate("""() => { localStorage.setItem('pock-km-vehicles', JSON.stringify([{id:'t1',name:'V',color:'#3563e9',startDate:'2025-01-01',durationMonths:37,kmPerYear:10000,excessCostPerKm:0.15}]));
        localStorage.setItem('pock-km-active','t1'); localStorage.setItem('pock-km-t1', JSON.stringify([{id:'a',date:'2025-06-01',km:6000},{id:'b',date:'2026-10-01',km:21000}])); }""")
    pg.reload()
    lum = pg.evaluate(r"""() => { const f = getComputedStyle(document.querySelector('.chart-wrap svg rect')).fill;
        const [r,g,b] = f.match(/\d+/g).map(Number); return (r+g+b)/3; }""")
    check("11 mode sombre : zone de dépassement sombre", lum < 80, lum)

    b.close()

print("PASS" if not fails else f"FAIL ({len(fails)}) : {', '.join(fails)}")
sys.exit(0 if not fails else 1)
