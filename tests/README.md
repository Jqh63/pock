# Pock tests

Lightweight Playwright smoke test suite. Validates that every Pock app
loads cleanly (no uncaught JS errors, no console errors), has its
expected title, and renders something paintable. Designed to be run
manually before a PR or as a pre-push hook — not in CI (no GitHub
Actions yet, repo is small enough that local-only is fine).

## Layout

- `smoke.py` — entry point. Iterates over the 4 apps, loads each via
  `file://`, captures errors, screenshots to `screenshots/`.
- `screenshots/` — output, gitignored. Re-generated on every run.
- `README.md` — this file.

## Run

```bash
python3 tests/smoke.py
```

Exits non-zero on any failure. Screenshots are written to
`tests/screenshots/<app>-<engine>.png`.

## Engines (cross-browser)

`smoke.py` runs every app on each engine in `PWA_ENGINES` (default
`chromium,webkit` — Blink baseline + the WebKit/Safari engine). An engine
whose browser can't launch (system libs missing) is **SKIPPED with a note**,
never a hard failure. `km-anchor.py` is single-engine: it uses the first
entry of `PWA_ENGINES` (default `chromium`).

```bash
PWA_ENGINES=chromium python3 tests/smoke.py   # Blink only
PWA_ENGINES=webkit   python3 tests/smoke.py   # Safari engine only
```

WebKit needs a heavy system-lib stack (root install). Pattern and setup
mirror `Jqh63/plex-jqh-omv/tests/README.md` § Engines.

## One-shot environment install

Requires Python 3.12+ plus Playwright with Chromium (and optionally WebKit):

```bash
python3 -m pip install --user playwright
python3 -m playwright install chromium webkit
```

The browser binaries live in `~/.cache/ms-playwright/` (~130 MB Chromium).

## Why a loopback HTTP server and not file://

`smoke.py` serves the repo over `http.server` on loopback. The suite used
`file://` until 2026-07-19, when the WebKit lane exposed the difference:
WebKit fetches `manifest.json` with CORS and blocks it on `file://`
(`Origin null`), while Chromium tolerates it. Loopback HTTP matches GitHub
Pages serving on both engines. `km-anchor.py` still uses `file://` (it
asserts DOM values only, no console-error capture).

## Extending

Add a new app:
1. Drop the file at the repo root (e.g. `notes.html`).
2. Add it to the `APPS` dict in `smoke.py` with a title substring.

Add deeper assertions (interaction, localStorage, multi-step flows):
inline in `smoke.py` after the `page.goto(...)` — keep it small enough
to read in one screen. If a single app accretes more than ~30 lines of
test, split it into a sibling file (`smoke_bibliotheque.py`) that
imports the same Playwright setup.

## Libs navigateur — rien à retenir

Chaque suite Playwright appelle `browser_guard.ensure()` à l'import. No-op quand
les moteurs sont sains (un `ldd`, quelques ms) et **idempotent** — plusieurs
appels dans un même process ne coûtent rien. Quand les libs système ont sauté
(les binaires survivent à un recreate du conteneur, leurs `.so` non), la suite
s'arrête tout de suite **avec la commande à taper**, au lieu de mourir en cours
de route dans du bruit d'éditeur de liens. `BROWSER_ENSURE_CMD` permet une
réparation automatique — le guard **re-vérifie** ensuite, il n'annonce jamais
« réparé » sur la foi d'un code de retour.

Banc : `python3 tests/browser-guard-selftest.py` (contrôle positif inclus — une
commande de réparation qui ne répare rien doit quand même échouer).
