#!/usr/bin/env python3
"""Sync multi-appareils : aucune saisie ne doit être perdue.

Deux appareils (contextes navigateur isolés) partagent le blob `km` du vrai
serveur `sync/app.py` (en process via TestClient, routé par Playwright).
- Saisie concurrente : A ajoute e2 pendant que B, resté sur l'ancienne
  version, ajoute e3 → le serveur doit finir avec e1, e2 ET e3.
- Suppression sur un appareil en retard : appliquée, sans perdre ni
  ressusciter d'entrée.
- Première sync d'un appareil qui a déjà des données : elles s'ajoutent à
  celles du serveur au lieu d'être effacées.
Code d'avant le correctif (last-write-wins sur le blob entier) : les deux
scénarios perdent des données → le test échoue.
Usage: python3 tests/sync-conflict.py [repo_dir]
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

sync.RATE_LIMIT_MAX_REQ = 10**6  # les sondes du banc ne doivent pas déclencher le 429
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
V2 = {**V1, "id": "v2", "name": "Moto"}
entry = lambda i, km: {"id": i, "date": f"2026-0{km}-01", "km": km * 100}

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait_for(page, pred, ms=8000):
    for _ in range(ms // 100):
        if pred():
            return True
        page.wait_for_timeout(100)
    return pred()


with sync_playwright() as p:
    browser = getattr(p, ENGINE).launch()

    def device(with_sync=True):
        ctx = browser.new_context(service_workers="block")
        ctx.route(SYNC_URL + "/**", route_to_api)
        pg = ctx.new_page()
        pg.goto(BASE + "/suivi-km-loa.html")
        if with_sync:
            pg.evaluate("u => { localStorage.setItem('pock-sync-url', u); localStorage.setItem('pock-sync-token', 'test-token'); }", SYNC_URL)
        return pg

    def append(pg, e):
        pg.evaluate("""e => { const k = 'pock-km-v1';
            const a = JSON.parse(localStorage.getItem(k) || '[]'); a.push(e);
            localStorage.setItem(k, JSON.stringify(a)); }""", e)

    # --- Scénario 1 : saisies concurrentes sur deux appareils -------------
    A = device()
    A.evaluate("""([v, e]) => { localStorage.setItem('pock-km-vehicles', JSON.stringify([v]));
        localStorage.setItem('pock-km-v1', JSON.stringify([e])); }""", [V1, entry("e1", 1)])
    check(wait_for(A, lambda: ids(server_km().get("pock-km-v1")) == ["e1"]), "A pousse e1")
    B = device()
    B.reload()
    check(wait_for(B, lambda: ids(B.evaluate("localStorage.getItem('pock-km-v1')")) == ["e1"]), "B récupère e1")
    append(A, entry("e2", 2))
    check(wait_for(A, lambda: ids(server_km().get("pock-km-v1")) == ["e1", "e2"]), "A pousse e2")
    append(B, entry("e3", 3))  # B n'a pas rechargé : il travaille sur [e1]
    check(wait_for(B, lambda: ids(server_km().get("pock-km-v1")) == ["e1", "e2", "e3"]),
          "serveur garde e1, e2 et e3 (obtenu : %s)" % ids(server_km().get("pock-km-v1")))
    check(wait_for(B, lambda: ids(B.evaluate("localStorage.getItem('pock-km-v1')")) == ["e1", "e2", "e3"]),
          "B voit e2 après fusion")

    # --- Scénario 1 bis : suppression sur un appareil en retard -----------
    # A n'a pas vu e3 ; il supprime e1 → le serveur doit garder e2 et e3,
    # sans faire revenir e1.
    A.evaluate("""() => { const k = 'pock-km-v1';
        const a = JSON.parse(localStorage.getItem(k)).filter(e => e.id !== 'e1');
        localStorage.setItem(k, JSON.stringify(a)); }""")
    check(wait_for(A, lambda: ids(server_km().get("pock-km-v1")) == ["e2", "e3"]),
          "suppression de e1 appliquée sans perdre e3 (obtenu : %s)" % ids(server_km().get("pock-km-v1")))

    # --- Scénario 2 : première sync d'un appareil qui a déjà des données --
    C = device(with_sync=False)
    C.evaluate("""([v, e]) => { localStorage.setItem('pock-km-vehicles', JSON.stringify([v]));
        localStorage.setItem('pock-km-v2', JSON.stringify([e])); }""", [V2, entry("x1", 4)])
    C.evaluate("u => { localStorage.setItem('pock-sync-url', u); localStorage.setItem('pock-sync-token', 'test-token'); }", SYNC_URL)
    C.reload()
    local_c = lambda k: C.evaluate(f"localStorage.getItem('{k}')")
    check(wait_for(C, lambda: ids(local_c("pock-km-vehicles")) == ["v1", "v2"]),
          "C garde son véhicule et reçoit celui du serveur (obtenu : %s)" % ids(local_c("pock-km-vehicles")))
    check(ids(local_c("pock-km-v2")) == ["x1"], "C garde son relevé x1")
    check(wait_for(C, lambda: ids(server_km().get("pock-km-vehicles")) == ["v1", "v2"]
                   and ids(server_km().get("pock-km-v2")) == ["x1"]), "serveur reçoit les données de C")
    check(ids(server_km().get("pock-km-v1")) == ["e2", "e3"], "serveur garde les relevés du véhicule v1")
    browser.close()

httpd.shutdown()
print("\n%s" % ("FAIL: %d" % len(failures) if failures else "OK"))
sys.exit(1 if failures else 0)
