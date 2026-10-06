#!/usr/bin/env bash
# bootstrap-pock-sync.sh — one-shot install of the pock-sync service on
# the VM (first install or disaster recovery). Run as root from a copy
# of this sync/ directory (e.g. a clone of the public Jqh63/pock repo):
#
#   sudo bash sync/bootstrap-pock-sync.sh
#
# Idempotent: every step checks before acting, and /etc/pock-sync.env is
# never overwritten (the Bearer token survives re-runs).
#
# Day-2 updates of app.py go through the deploy channel (sync/deploy.sh →
# push-pock-sync-app / apply-pock-sync). The UNIT does not: a unit is
# root-equivalent, so the deploy key may not write one (relay scan finding
# F8, 2026-09-27) — a unit change means re-running this script, which then
# restarts the service only if the unit (or app.py) actually changed.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step() { echo; echo "== $* =="; }

step "user pock"
if ! id pock &>/dev/null; then
  useradd --system --home /opt/pock-sync --shell /usr/sbin/nologin pock
  echo "user pock created"
else
  echo "user pock already exists"
fi

step "directories"
install -d -m 0755 -o root -g root /opt/pock-sync
install -d -m 0700 -o pock -g pock /var/lib/pock-sync

step "python venv + deps"
if [[ ! -x /opt/pock-sync/venv/bin/uvicorn ]]; then
  python3 -m venv /opt/pock-sync/venv
  /opt/pock-sync/venv/bin/pip install --quiet fastapi 'uvicorn[standard]'
  echo "venv created"
else
  echo "venv already present"
fi

step "token + env file (0600, never overwritten)"
if [[ ! -f /etc/pock-sync.env ]]; then
  TOKEN="$(openssl rand -hex 32)"
  install -m 0600 -o root -g root /dev/null /etc/pock-sync.env
  printf 'POCK_SYNC_TOKEN=%s\n' "$TOKEN" > /etc/pock-sync.env
  echo "/etc/pock-sync.env created with a fresh token"
  echo "  → read it once with: sudo grep POCK_SYNC_TOKEN /etc/pock-sync.env"
  echo "  → enter it on each device in the Pock hub (Données → Synchronisation)"
else
  echo "/etc/pock-sync.env already present — token kept"
fi

step "app + systemd unit"
# app.py compte aussi : un rejeu DR avec un app.py plus récent laissait
# tourner l'ancien code (enable --now ne redémarre pas un service actif).
changed=0
cmp -s "$DIR/app.py" /opt/pock-sync/app.py || changed=1
cmp -s "$DIR/pock-sync.service" /etc/systemd/system/pock-sync.service || changed=1
install -o pock -g pock -m 0644 "$DIR/app.py" /opt/pock-sync/app.py
install -m 0644 "$DIR/pock-sync.service" /etc/systemd/system/pock-sync.service
systemctl daemon-reload
systemctl enable --now pock-sync
if [[ "$changed" -eq 1 ]]; then
  systemctl try-restart pock-sync && echo "app/unit changed — pock-sync restarted"
fi

step "health"
# Retry : sur l'e2-micro uvicorn met quelques secondes à binder (cf. deploy.sh) ;
# une sonde unique sous set -e faisait échouer le bootstrap à tort.
for attempt in 1 2 3 4 5; do
  if curl -fsS http://127.0.0.1:8001/pock/health; then echo; break; fi
  [[ "$attempt" -eq 5 ]] && { echo "health KO after 5 attempts" >&2; exit 1; }
  sleep 2
done

cat <<'EOF'

Done. Remaining manual steps:
  1. Caddy: deploy a Caddyfile carrying the /pock/* route + CORS
     (relay repo — relay/scripts/deploy.sh) and reload caddy.
  2. Test from outside: curl -s https://<domain>/pock/health
EOF
