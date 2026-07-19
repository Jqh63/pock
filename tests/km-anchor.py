#!/usr/bin/env python3
"""Test différentiel : le delta 'Écart vs prévu' doit être ancré sur la date du
dernier relevé, pas sur aujourd'hui.

Scénario : contrat démarré il y a 100 j, kmPerDay ~27.4 (10000 km/an, 37 mois),
un seul relevé daté d'il y a 30 j, pile au km attendu à cette date-là.
- Code corrigé : delta = 0 (relevé conforme au prévu à SA date).
- Code buggé   : delta ≈ -30 j × kmPerDay ≈ -820 km ('en dessous du prévu',
  artificiellement favorable) → le test DOIT échouer dessus.
Usage: python3 km-anchor-test.py <repo_dir>
"""
import sys, json, datetime, re
from playwright.sync_api import sync_playwright

repo = sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
today = datetime.date.today()
start = today - datetime.timedelta(days=100)
entry_date = today - datetime.timedelta(days=30)
# kmPerDay = totalKm/totalDays calculé par la page ; on reproduit le calcul
dur_months = 37
km_per_year = 10000
total_km = round(km_per_year * dur_months / 12)
# end = start + 37 mois — approx suffisante via dateutil-free : la page fait setMonth
def add_months(d, m):
    y, mo = d.year + (d.month - 1 + m) // 12, (d.month - 1 + m) % 12 + 1
    try: return d.replace(year=y, month=mo)
    except ValueError: return d.replace(year=y, month=mo, day=28)
end = add_months(start, dur_months)
total_days = (end - start).days
km_per_day = total_km / total_days
entry_km = round(km_per_day * 70)  # jour 70 = il y a 30 j

vehicle = [{"id": "t1", "name": "Test", "color": "#3563e9",
            "startDate": start.isoformat(), "durationMonths": dur_months,
            "kmPerYear": km_per_year, "excessCostPerKm": 0.15}]
entries = [{"date": entry_date.isoformat(), "km": entry_km}]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(f"file://{repo}/suivi-km-loa.html")
    pg.evaluate("""([v, e]) => {
        localStorage.setItem('pock-km-vehicles', JSON.stringify(v));
        localStorage.setItem('pock-km-active', 't1');
        localStorage.setItem('pock-km-t1', JSON.stringify(e));
    }""", [vehicle, entries])
    pg.reload()
    hero = pg.locator(".hero-delta-value").inner_text()
    detail = pg.locator(".hero-delta-detail").inner_text()
    b.close()

delta = int(re.sub(r"[^\d-]", "", hero.replace("−", "-").replace(" ", "")))
print(f"hero='{hero}' delta={delta} | detail='{detail}'")
ok = abs(delta) <= 1  # tolérance d'arrondi jour
anchored = "relevé du" in detail and "il y a 30 j" in detail
print("PASS" if (ok and anchored) else f"FAIL (delta ancré attendu ~0, détail ancré={anchored})")
sys.exit(0 if (ok and anchored) else 1)
