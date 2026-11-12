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
# Garde : ne déploie que ce qui est mergé. Refus (exit 4) si HEAD n'est pas
# exactement origin/main (fetch à l'instant) ou si un fichier suivi est
# modifié sous sync/ — sinon une branche non mergée, un clone en retard ou
# une modif locale partirait en silence. Urgence seulement :
# DEPLOY_ALLOW_UNMERGED=1 saute la garde, bruyamment.
#
# Exit codes: 0 OK, 1 push/apply failed, 2 status KO post-restart,
#             4 garde : clone pas sur un origin/main propre (ou non mesuré), rien envoyé.

set -euo pipefail

ALIAS="${WOL_RELAY_ALIAS:-wol-relay-deploy}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

refuse() { echo "[deploy] REFUS — $1" >&2; echo "[deploy]   rien envoyé à la VM. Urgence : DEPLOY_ALLOW_UNMERGED=1" >&2; exit 4; }
if [ "${DEPLOY_ALLOW_UNMERGED:-}" = "1" ]; then
  echo "[deploy] WARN — DEPLOY_ALLOW_UNMERGED=1 : garde origin/main sautée, l'arbre de travail part tel quel" >&2
else
  git -C "$DIR" fetch --quiet origin main 2>/dev/null \
    || refuse "git fetch origin main en échec : impossible de savoir si ce clone est à jour"
  head_sha="$(git -C "$DIR" rev-parse HEAD)" && main_sha="$(git -C "$DIR" rev-parse origin/main)" \
    || refuse "HEAD / origin/main illisibles"
  [ "$head_sha" = "$main_sha" ] \
    || refuse "HEAD (${head_sha:0:7}) n'est pas origin/main (${main_sha:0:7}) : merger d'abord, puis pull"
  dirty="$(git -C "$DIR" status --porcelain --untracked-files=no -- "$DIR")" \
    || refuse "git status en échec"
  [ -z "$dirty" ] || refuse "fichiers suivis modifiés sous sync/ : $(tr '\n' ' ' <<<"$dirty")"
fi

echo "[deploy] push app.py ..."
# Le push coupé se termine côté VM par une fin de fichier ordinaire : seul le
# nombre d'octets annoncé distingue un fichier entier d'un fichier tronqué.
want="$(wc -c < "$DIR/app.py" | tr -d ' ')"
out="$(ssh "$ALIAS" push-pock-sync-app < "$DIR/app.py")"; printf '%s\n' "$out"
got="$(sed -n 's/.*OK (\([0-9][0-9]*\) bytes).*/\1/p' <<<"$out")"
[ "$got" = "$want" ] || { echo "[deploy] FAIL — VM : '${got:-?}' octets reçus, $want envoyés. Rien appliqué." >&2; exit 1; }

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
