# Pock Sync — per-app JSON blob store

Tiny FastAPI service giving the Pock PWAs a server-side copy of their
data: `GET/PUT /pock/<app>` — one JSON blob per app, Bearer token
required on every operation. Designed to run alongside the
[WoL relay](https://github.com/Jqh63/plex-jqh-omv/tree/main/relay) on
the same always-on VM, behind the same Caddy (path route, no new
vhost/cert). The client side lives in `common.js` (§ *Sync* — opt-in,
configured from the hub).

## Why it exists

Pock is "no backend" by design — but `localStorage` is not durable
storage: it vanishes with a browser-data cleanup, no trash bin. This
service is a **scoped exception** to that principle: data goes only to
a personal server you control, only if you opt in from the hub. Without
configuration, nothing is ever sent anywhere.

## API

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /pock/health` | none | liveness `{"status":"ok"}` — reveals nothing |
| `GET /pock/<app>` | Bearer | returns the blob verbatim, `404` if none |
| `PUT /pock/<app>` | Bearer | stores the blob (atomic write), JSON object only, size-capped (256 KB default) |

`<app>` must match `[a-z0-9-]{1,32}` (doubles as path-traversal guard).
No listing endpoint. Absent and invalid tokens both get `401` with the
same body (no oracle); the comparison is constant-time. Per-IP
sliding-window rate limit (60 req/min) applied before the token check.

Blob format (written by the client, stored verbatim):

```json
{ "version": 1, "updatedAt": 1718000000000, "data": { "pock-km-vehicles": "…" } }
```

Conflict resolution is client-side last-write-wins per app, using
`updatedAt` (device clock, ms).

## Sharing with another person (scoped tokens)

Set `POCK_SYNC_SCOPED_TOKENS` in the env file (see `.env.example`):
each extra token is limited to a list of apps and reads/writes the
**same blobs** as the full token — that's the sharing. Example: a
`<token>:km` entry given to a family member shares the vehicle
tracking both ways, while their book list / carpool history stay
local-only on their devices (the PWA degrades silently on 403, by
construction of the client sync layer). The full token keeps access to
everything.

Trade-offs (accepted): conflicts stay last-write-wins per app — two
near-simultaneous writes and the later one wins silently. Fine for
spaced-out usage (monthly odometer readings); revisit with per-record
merge if concurrent editing becomes real. No per-person private space
*within* a shared app — that would need namespaced blobs.

## Deploy (mirror of the WoL relay procedure)

**One-shot bootstrap** (first install / DR) — as root on the VM, from a
copy of this `sync/` directory:

```bash
sudo bash sync/bootstrap-pock-sync.sh
```

Creates the `pock` system user, dirs (`/var/lib/pock-sync` 700), venv
(fastapi + uvicorn), generates the token into `/etc/pock-sync.env`
(0600, never overwritten on re-run), installs app + unit, enables the
service, and curls `/pock/health`.

**Day-2 updates** — from the deploying host, through the existing
forced-command channel (`wol-relay-deploy` alias, dispatch whitelist
extended with the `pock-sync-*` verbs — see the relay repo):

```bash
bash sync/deploy.sh        # push app.py, apply, status
ssh wol-relay-deploy pock-sync-status
ssh wol-relay-deploy logs-pock-sync
```

> ⚠️ **The systemd unit is not deployable through this channel** (relay scan
> finding F8, 2026-09-27): a unit is root-equivalent, so letting the deploy
> key write one made that key root. A change to `pock-sync.service` = rerun
> `sync/bootstrap-pock-sync.sh` on the VM (idempotent; restarts the service
> only if the unit changed).

### Caddy (existing site block of the relay domain)

Add a path route **before** the relay's catch-all `reverse_proxy`:

```caddyfile
handle /pock/* {
	reverse_proxy localhost:8001 {
		header_up -X-Forwarded-For
		header_up X-Real-IP {remote_host}
	}
}
```

And extend the existing CORS headers for the PWA origin:

- `Access-Control-Allow-Methods`: add `PUT`
- `Access-Control-Allow-Headers`: add `Authorization`

(Same rationale as the relay: CORS at the Caddy layer so the headers
are present on Caddy-generated errors too; X-Real-IP is the only
client IP the rate limiter can trust.)

## Token handling

- Generated on the VM (`openssl rand -hex 32`), lives only in
  `/etc/pock-sync.env` (0600) — never in any repo.
- Entered once per device in the PWA hub (stored in `localStorage`; if
  a cache cleanup wipes it, re-enter it — the data itself is on the
  server).
- Revocation = change the env file + restart the unit. Worst case on
  compromise: read/overwrite of low-sensitivity blobs (km logs, book
  lists), restorable from the home backup.

## Backup

The VM is never the sole holder of the data: the home server pulls the
blob files (`/var/lib/pock-sync/*.json`) daily through its existing
read-only deploy channel and feeds them to its regular backup. Losing
the VM loses at most a few hours of sync, never the data.
