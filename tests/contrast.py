#!/usr/bin/env python3
"""
Contrast audit of every Pock app, light AND dark (prefers-color-scheme).

Why: dark mode shipped with native controls (date picker icon, select arrow,
checkbox) drawn in the LIGHT theme — no `color-scheme` declared — and with
white text on accents that the dark palette had made light (1.9:1). Nothing
looked at contrast, so it went unnoticed until read on a phone at night.

For each app, each state (empty + populated with FICTITIOUS fixtures) and
each scheme:
  - asserts `color-scheme` on :root lets the UA follow the theme;
  - computes WCAG contrast of every visible text node against its effective
    background (alpha layers + ancestor opacity composited) and fails under
    AA: 4.5:1, or 3:1 for large text (>= 24px, or >= 18.66px bold).
Not covered (by construction): text over gradients/images, disabled
controls (WCAG-exempt), placeholders, SVG text.

Run from the repo root:  python3 tests/contrast.py   (exit 0 = AA holds)
Single engine (chromium): computed colours don't depend on the engine.
"""

import sys
import threading
from contextlib import contextmanager
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from playwright.sync_api import sync_playwright

from browser_guard import ensure as _ensure_browser

_ensure_browser()

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

DAY = 86_400_000
# Fixtures: fictitious values only (public repo). Seeded before the app loads.
SEED = r"""(() => {
  const now = Date.now(), D = 86400000;
  localStorage.setItem('pock-biblio-books', JSON.stringify([
    {id:'b1', title:'Livre A', author:'Auteur A', note:'note', status:'to_read',  addedAt: now-5*D},
    {id:'b2', title:'Livre B', author:'Auteur B', note:'',     status:'reading',  addedAt: now-4*D},
    {id:'b3', title:'Livre C', author:'Auteur C', note:'',     status:'read',     addedAt: now-3*D},
    {id:'b4', title:'Livre D', author:'Auteur D', note:'',     status:'reserved', addedAt: now-2*D},
    {id:'b5', title:'Livre E', author:'Auteur E', note:'',     status:'borrowed', addedAt: now-1*D}]));
  const iso = d => new Date(now - d*D).toISOString().slice(0,10);
  localStorage.setItem('pock-km-vehicule-1', JSON.stringify([
    {id:'k1', date: iso(400), km: 9000}, {id:'k2', date: iso(200), km: 16000},
    {id:'k3', date: iso(30),  km: 26000}, {id:'k4', date: iso(2), km: 27500}]));
  const m = (d, h, s, di, p, c) => ({id:'m'+d+h, ts: now - d*D + h*3600000, sys:s, dia:di, pulse:p, campaignId:c});
  localStorage.setItem('pock-hta-campaigns', JSON.stringify([{id:'c1', startedAt: now-10*D, endedAt: now-7*D}]));
  localStorage.setItem('pock-hta-measures', JSON.stringify([
    m(10,8,128,82,66,'c1'), m(10,20,141,88,70,'c1'), m(9,8,119,76,62,'c1'),
    m(9,20,152,95,74,'c1'), m(8,8,124,80,64,'c1'), m(8,20,133,84,68,'c1'),
    m(1,9,165,102,80,null)]));
})()"""

COVOIT_RESULT = """() => {
  document.getElementById('inKm').value = '120';
  document.getElementById('inPart').value = '4';
  document.getElementById('inDriv').value = '2';
  doCalc(); doSave(); toggleTiers();
}"""

# app -> list of (state name, JS run after load or None)
STATES = {
    "index.html":             [("hub", None)],
    "suivi-km-loa.html":      [("populated", None)],
    "bibliotheque.html":      [("populated", None),
                               ("filtered", "() => setFilter('read')"),
                               ("add-form", "() => openAdd()")],
    "covoiturage-rando.html": [("empty", None), ("result", COVOIT_RESULT)],
    "hta.html":               [("populated", None)],
}

SCAN = r"""() => {
  const P = s => (s.match(/[\d.]+/g) || []).map(Number);
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v/12.92 : ((v+0.055)/1.055)**2.4; };
                     return 0.2126*f(c[0]) + 0.7152*f(c[1]) + 0.0722*f(c[2]); };
  const alpha = c => c.length > 3 ? c[3] : 1;
  const root = P(getComputedStyle(document.documentElement).backgroundColor);
  const body = P(getComputedStyle(document.body).backgroundColor);
  const canvas = alpha(body) > 0 ? body.slice(0,3) : alpha(root) > 0 ? root.slice(0,3) : [255,255,255];
  const bgOf = el => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = P(getComputedStyle(e).backgroundColor);
      if (c.length && alpha(c) > 0) { layers.push(c); if (alpha(c) >= 1) break; }
    }
    let base = (layers.length && alpha(layers.at(-1)) >= 1) ? layers.pop().slice(0,3) : canvas;
    for (let i = layers.length - 1; i >= 0; i--) { const c = layers[i], a = alpha(c);
      base = base.map((v,k) => v*(1-a) + c[k]*a); }
    return base;
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('svg') || el.disabled) continue;
    let text = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim())
                                 .map(n => n.textContent.trim()).join(' ');
    if (!text && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') &&
        !['checkbox','radio','range','color'].includes(el.type)) text = el.value;
    if (!text && el.tagName === 'SELECT') text = el.selectedOptions[0]?.text || '';
    if (!text) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden') continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= parseFloat(getComputedStyle(e).opacity);
    if (op < 0.05) continue;
    const fg = P(cs.color), bg = bgOf(el), a = alpha(fg) * op;
    const mixed = fg.slice(0,3).map((v,k) => v*a + bg[k]*(1-a));
    const l1 = lum(mixed), l2 = lum(bg), ratio = (Math.max(l1,l2)+0.05) / (Math.min(l1,l2)+0.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (size >= 24 || (bold && size >= 18.66)) ? 3 : 4.5;
    if (ratio < need) out.push(`${ratio.toFixed(2)} < ${need}  <${el.tagName.toLowerCase()} class="${el.className}"> "${text.slice(0,40)}" ${cs.color}`);
  }
  return {scheme: getComputedStyle(document.documentElement).colorScheme, low: out};
}"""


@contextmanager
def serve_repo():
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = partial(Quiet, directory=str(REPO_ROOT))
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def main():
    failures = 0
    with serve_repo() as base, sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("light", "dark"):
            for app, states in STATES.items():
                for state, action in states:
                    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                              color_scheme=scheme)
                    ctx.add_init_script(f"if (!sessionStorage.seeded) {{ {SEED}; sessionStorage.seeded = 1; }}")
                    page = ctx.new_page()
                    page.goto(f"{base}/{app}", wait_until="load")
                    page.wait_for_timeout(300)
                    if action:
                        page.evaluate(action)
                        page.wait_for_timeout(300)
                    res = page.evaluate(SCAN)
                    name = f"{app.removesuffix('.html')}-{state}-{scheme}"
                    page.screenshot(path=str(SCREENSHOT_DIR / f"contrast-{name}.png"), full_page=True)
                    problems = list(res["low"])
                    if scheme not in res["scheme"]:
                        problems.insert(0, f"color-scheme is '{res['scheme']}' — native controls won't follow {scheme}")
                    status = "OK  " if not problems else "FAIL"
                    print(f"{status} {name}" + (f" ({len(problems)})" if problems else ""))
                    for line in problems:
                        print(f"       {line}")
                    failures += bool(problems)
                    ctx.close()
        browser.close()
    print(f"\n{failures} failing view(s)" if failures else "\nall views pass WCAG AA")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
