#!/usr/bin/env bash
# deploy.sh — deploy pock-sync's code to the VM through the existing
# forced-command channel (same alias as the WoL relay).
#
# Pipes app.py over stdin to the VM-side dispatch.sh, then triggers
# apply-pock-sync + pock-sync-status. The systemd unit is NOT deployed here:
# a unit is root-equivalent, so only bootstrap-pock-sync.sh installs it
# (relay scan finding F8, 2026-09-27). Unit change = rerun the bootstrap.
#
# Prerequisites:
#   - the `wol-relay-deploy` SSH alias configured on the deploying host
#   - dispatch.sh + sudoers on the VM carrying the pock-sync verbs
#   - one-shot bootstrap done (sync/bootstrap-pock-sync.sh)
#
# Usage:
#   bash sync/deploy.sh
#   WOL_RELAY_ALIAS=other-alias bash sync/deploy.sh
#
# Exit codes: 0 OK, 1 push/apply failed, 2 status KO post-restart.

set -euo pipefail

ALIAS="${WOL_RELAY_ALIAS:-wol-relay-deploy}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[deploy] push app.py ..."
ssh "$ALIAS" push-pock-sync-app < "$DIR/app.py"

echo "[deploy] apply-pock-sync ..."
ssh "$ALIAS" apply-pock-sync

echo "[deploy] status ..."
# Retry: on the e2-micro, uvicorn takes a few seconds to bind after the
# restart — a 0-delay probe gives a false-negative WARN on every deploy.
for attempt in 1 2 3; do
  if ssh "$ALIAS" pock-sync-status; then
    echo "[deploy] DONE — pock-sync restarted, /pock/health OK"
    exit 0
  fi
  [ "$attempt" -lt 3 ] && { echo "[deploy] not ready, retry ${attempt}/3 in 5s ..."; sleep 5; }
done
echo "[deploy] WARN — status KO post-restart, investigate VM side (logs-pock-sync)" >&2
exit 2
