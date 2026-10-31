#!/usr/bin/env python3
"""Sync en arrière-plan : une PWA restée ouverte voit la saisie de l'autre appareil.

Deux appareils partagent le blob `km` du vrai serveur `sync/app.py` (en
process via TestClient, routé par Playwright), comme sync-conflict.py.
- Retour au premier plan : B, resté ouvert, relit le serveur et affiche la
  saisie de A — sans recharger la page à la main.
- Borne : deux retours rapprochés (< 30 s) ne relisent qu'une fois.
- Saisie en cours : pas de relecture (la fusion recharge la page et perdrait
  le champ).
- Envoi raté (hors ligne) : bandeau « pas encore synchronisé » ; au retour du
  réseau, l'envoi repart et le bandeau disparaît.
Code d'avant (relecture au seul chargement, échec muet) : scénarios 1 et 4
rouges.
Usage: python3 tests/sync-foreground.py [repo_dir]
"""
import functools
import json
import os
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from browser_guard import ensure as _ensure_browser

_ensure_browser()
ENGINE = os.environ.get("PWA_ENGINES", "chromium").split(",")[0].strip()
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ["POCK_SYNC_TOKEN"] = "test-token"
os.environ["POCK_SYNC_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(repo, "sync"))
import app as sync  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sync.RATE_LIMIT_MAX_REQ = 10**6
api = TestClient(sync.app)
AUTH = {"Authorization": "Bearer test-token"}
SYNC_URL = "https://sync.test"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Allow-Methods": "GET, PUT, OPTIONS"}


def route_to_api(route):
    req = route.request
    if req.method == "OPTIONS":
        return route.fulfill(status=204, headers=CORS)
    path = req.url[len(SYNC_URL):]
    r = api.request(req.method, path, headers={k: v for k, v in req.headers.items() if k.lower() in ("authorization", "content-type")},
                    content=req.post_data_buffer)
    route.fulfill(status=r.status_code, body=r.content, headers={**CORS, "Content-Type": "application/json"})


def server_km():
    r = api.get("/pock/km", headers=AUTH)
    return r.json()["data"] if r.status_code == 200 else {}


def ids(raw):
    return sorted(x["id"] for x in json.loads(raw or "[]"))


handler = functools.partial(SimpleHTTPRequestHandler, directory=repo)
handler.log_message = lambda *a: None
httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{httpd.server_port}"

V1 = {"id": "v1", "name": "Auto", "color": "#3563e9", "startDate": "2026-01-01",
      "durationMonths": 37, "kmPerYear": 10000, "excessCostPerKm": 0.15}
entry = lambda i, km: {"id": i, "date": f"2026-0{km}-01", "km": km * 100}

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait_for(page, pred, ms=8000):
    for _ in range(ms // 100):
        try:
            if pred():
                return True
        except Exception:  # page en cours de rechargement
            pass
        page.wait_for_timeout(100)
    try:
        return pred()
    except Exception:
        return False


with sync_playwright() as p:
    browser = getattr(p, ENGINE).launch()

    def device():
        ctx = browser.new_context(service_workers="block")
        ctx.route(SYNC_URL + "/**", route_to_api)
        pg = ctx.new_page()
        pg.goto(BASE + "/suivi-km-loa.html")
        pg.evaluate("u => { localStorage.setItem('pock-sync-url', u); localStorage.setItem('pock-sync-token', 'test-token'); }", SYNC_URL)
        return ctx, pg

    def append(pg, e):
        pg.evaluate("""e => { const k = 'pock-km-v1';
            const a = JSON.parse(localStorage.getItem(k) || '[]'); a.push(e);
            localStorage.setItem(k, JSON.stringify(a)); }""", e)

    def foreground(pg, later_s=0):
        # `later_s` avance l'horloge de la page (borne de 30 s) ; puis retour au premier plan.
        pg.evaluate("""s => { if (s) { const n = Date.now; Date.now = () => n() + s * 1000; }
            document.dispatchEvent(new Event('visibilitychange')); }""", later_s)

    local_b = lambda: B.evaluate("localStorage.getItem('pock-km-v1')")
    badge = lambda pg: pg.evaluate("(() => { const b = document.getElementById('pockSyncPending'); return !!b && !b.hidden; })()")

    ctxA, A = device()
    A.evaluate("""([v, e]) => { localStorage.setItem('pock-km-vehicles', JSON.stringify([v]));
        localStorage.setItem('pock-km-v1', JSON.stringify([e])); }""", [V1, entry("e1", 1)])
    check(wait_for(A, lambda: ids(server_km().get("pock-km-v1")) == ["e1"]), "A pousse e1")
    ctxB, B = device()
    B.reload()
    check(wait_for(B, lambda: ids(local_b()) == ["e1"]), "B récupère e1 au chargement")

    # --- 1 : retour au premier plan ------------------------------------
    append(A, entry("e2", 2))
    check(wait_for(A, lambda: ids(server_km().get("pock-km-v1")) == ["e1", "e2"]), "A pousse e2")
    foreground(B, later_s=60)
    check(wait_for(B, lambda: ids(local_b()) == ["e1", "e2"]),
          "B, resté ouvert, voit e2 au retour au premier plan")

    # --- 2 : borne de 30 s ---------------------------------------------
    append(A, entry("e3", 3))
    check(wait_for(A, lambda: ids(server_km().get("pock-km-v1")) == ["e1", "e2", "e3"]), "A pousse e3")
    B.wait_for_load_state()
    foreground(B)  # juste après le rechargement : dans la borne
    B.wait_for_timeout(2000)
    check(ids(local_b()) == ["e1", "e2"], "2ᵉ retour < 30 s : pas de relecture (obtenu : %s)" % ids(local_b()))

    # --- 3 : saisie en cours -------------------------------------------
    B.evaluate("""() => { const f = document.createElement('input'); f.type = 'text'; f.id = 'typing';
        document.body.appendChild(f); f.value = '12345'; }""")
    foreground(B, later_s=60)
    B.wait_for_timeout(2000)
    check(ids(local_b()) == ["e1", "e2"] and B.evaluate("!!document.getElementById('typing')"),
          "champ en cours de saisie : ni relecture ni rechargement")
    B.evaluate("document.getElementById('typing').remove()")
    foreground(B, later_s=60)
    check(wait_for(B, lambda: ids(local_b()) == ["e1", "e2", "e3"]), "saisie finie : B relit et voit e3")

    # --- 4 : envoi raté puis retour du réseau --------------------------
    B.wait_for_load_state()
    ctxB.unroute(SYNC_URL + "/**")
    ctxB.route(SYNC_URL + "/**", lambda r: r.abort())
    check(not badge(B), "pas de bandeau quand tout est synchronisé")
    append(B, entry("e4", 4))
    B.wait_for_timeout(300)
    check(not badge(B), "pas de bandeau pendant l'attente normale de l'envoi")
    check(wait_for(B, lambda: badge(B)), "envoi raté : bandeau « pas encore synchronisé »")
    ctxB.unroute(SYNC_URL + "/**")
    ctxB.route(SYNC_URL + "/**", route_to_api)
    B.evaluate("window.dispatchEvent(new Event('online'))")
    check(wait_for(B, lambda: ids(server_km().get("pock-km-v1")) == ["e1", "e2", "e3", "e4"]),
          "réseau revenu : e4 part au serveur (obtenu : %s)" % ids(server_km().get("pock-km-v1")))
    check(wait_for(B, lambda: not badge(B)), "bandeau retiré une fois synchronisé")
    browser.close()

httpd.shutdown()
print("\n%s" % ("FAIL: %d" % len(failures) if failures else "OK"))
sys.exit(1 if failures else 0)
