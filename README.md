# Pock

Pocket tools — lightweight personal web apps that run offline in any browser.

No framework, no external dependencies. Just HTML/CSS/JS + system fonts. No backend by default — with one scoped exception: an **opt-in sync** to a personal server you control (see [Data & Privacy](#data--privacy)).

## Apps

### 🚗 Suivi km LOA

Track mileage against your lease (LOA) allowance. Add your own vehicles, log odometer readings, and see at a glance whether you're under or over budget.

- Pre-configured with two example vehicles
- Add/remove vehicles with custom name, color, start date, duration, km/year, and excess cost/km
- Dashboard: current km, delta vs expected, remaining budget per month
- Cost projection with stability threshold (needs a single reading and 30+ days of contract before projecting; warns if the last reading is older than 60 days)
- SVG chart: expected vs actual mileage curve
- Contract status: not started, active, or ended
- Reset entries while keeping vehicle config
- All vehicle configs and readings stored in localStorage

### 🩺 Tension

Blood-pressure self-monitoring built around the HAS "rule of 3" cycle: 3 measures morning and evening over 3 consecutive days (18 total), averaged against the home self-measurement threshold (135/85 mmHg, vs 140/90 at the clinic).

- Guided series: 3 chained measures with a timed rest/interval and screen wake-lock
- Manual one-off measures alongside cycles
- Verdict + 6-level classification (hypotension → severe HTA), colored scale, 30-measure trend chart
- History: every measure listed individually in a collapsible section per finished cycle, with inline edit and per-measure delete (not just whole-cycle delete)
- Doctor report: share/export a text summary of a cycle (average, verdict, the 18 measures detailed by day/slot) via the Web Share API, with clipboard + `.txt` download fallback
- All measures and cycles stored in localStorage (private app — see Sync below)

### 📚 Ma Bibliothèque

Track your reading list, library reservations, and borrowed books. Filter by status, search by title or author, import books in bulk.

- Statuses: to read, reading, read, reserved, borrowed
- Quick status change, edit, delete (with confirmation)
- Bulk import (paste a list: title ; author ; note)
- Sort by date, title, or author (stable sort)
- Persistent history in localStorage

### 🥾 Covoiturage Rando

Calculate fair cost-sharing for group hiking carpools at €0.30/km. Handles multiple cars, rounds up to the nearest euro, shows any surplus for the club fund.

- Detailed cost breakdown
- Backup rate table for offline use without the app
- Persistent history of last 20 calculations

### 💾 Data export / import

From the hub, export all your Pock data to a single JSON file, or import back. Supports merge or replace modes. Useful for backup or switching devices.

### 🔄 Sync (opt-in)

From the hub, point Pock at a self-hosted [sync server](sync/README.md) (URL + Bearer token, entered once per device). Each app then keeps a server-side copy of its data: pull on load, debounced push on change; two devices editing the same app are merged (entries added or removed on either side are kept), never overwritten. localStorage stays the source for the UI and offline use — if the server is unreachable, everything keeps working and sync resumes later. Without configuration, nothing is ever sent anywhere.

**Sharing model — per app, one token.** A single token enables both sync and backup; what gets shared is a property of the app, not the token:

- **Shared apps** (`km`, `covoit`, `biblio`) — one common server blob per app, synced across **all users and devices** that use the token. Hand the token to a family member and you share these.
- **Private apps** (`hta` — health data) — the server blob is suffixed with a random per-device id (`hta-<deviceId>`), so each device keeps its **own** blob: never synced to your other devices, never visible to others sharing the token, but still backed up (the server dump captures every blob). Isolation comes from the blob name, not a token scope.

Caveat: this is privacy *by namespacing*, not cryptographic isolation — someone holding the token who also knew your random device id could craft a manual read. The client never does this and blob names aren't enumerable, so in practice a private app stays private; hard isolation would need its own token + server-side enforcement.

## Install

### GitHub Pages

1. Fork or push to a GitHub repo
2. **Settings → Pages → Source: main branch**
3. Access at `https://<username>.github.io/<repo>/`

### Local

Open `index.html` in any browser. No server needed.

### As a mobile app (PWA)

Visit the site on your phone, then:
- **Android**: tap the install banner or Menu → "Add to Home Screen"
- **iOS**: Share → "Add to Home Screen"

The app works offline after first visit.

## Compatibility

Chrome, Safari, Firefox — Android, iOS, Windows, macOS.

## Files (flat, all at repo root)

```
index.html              ← Hub + data export/import
suivi-km-loa.html       ← Mileage tracker
covoiturage-rando.html  ← Carpooling calculator
bibliotheque.html       ← Book tracker
common.css              ← Shared base styles (reset, tokens, focus)
common.js               ← Shared helpers (esc, genId, SW reg, export/import, sync)
sync/                   ← Optional self-hosted sync server (FastAPI blob store)
manifest.json           ← PWA manifest
sw.js                   ← Service worker (offline, cache-first)
icon-192.png            ← Standard icon
icon-512.png            ← Large icon
icon-maskable.png       ← Maskable icon
apple-touch-icon.png    ← iOS home screen (180px)
```

## Data & Privacy

By default all data stays in your browser's localStorage and nothing is sent to any server. If you enable sync from the hub, data goes **only** to the server you configured yourself (see [sync/README.md](sync/README.md)) — never to any third party.

Storage keys used:
- `pock-km-vehicles` — vehicle configurations
- `pock-km-[id]` — mileage entries per vehicle
- `pock-km-active` — last selected vehicle
- `pock-biblio-books` — book collection
- `pock-covoit-history` — carpooling history
- `pock-hta-measures` / `pock-hta-campaigns` — blood-pressure measures and cycles
- `pock-sync-url` / `pock-sync-token` / `pock-sync-state` — sync config + per-app sync state (only when sync is enabled; `pock-sync-meta` = pre-2026-10-11 state, now unused)
- `pock-device` — random per-device id used to namespace private-app blobs (`hta`); local only, never synced

## License

MIT — fork it, adapt it, make it yours.
