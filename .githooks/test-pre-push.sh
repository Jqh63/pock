#!/usr/bin/env bash
# Banc de .githooks/pre-push — pousse pour de vrai vers un remote jetable.
# Le cas B est celui qu'un garde par commit ratait (bump dans son propre commit).
set -uo pipefail
unset $(env | sed -n 's/^\(GIT_[A-Z_]*\)=.*/\1/p') 2>/dev/null
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pre-push"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
git init -q --bare "$T/remote.git"; git init -q -b main "$T/r"; cd "$T/r" || exit 1
git config user.email t@t; git config user.name t
mkdir -p .githooks tests sync; cp "$HOOK" .githooks/
echo "const CACHE_NAME = 'pock-v1';" > sw.js; echo a > app.js; echo a > README.md
git add -A; git commit -q -m seed; git remote add origin "$T/remote.git"
git push -q origin main; git fetch -q origin; git config core.hooksPath .githooks
fail=0; n=0
touch_() { if [ "$1" = BUMP ]; then n=$((n+1)); echo "const CACHE_NAME = 'pock-v1$n';" > sw.js; set -- sw.js; else echo "$RANDOM" >> "$1"; fi; git add "$1"; }
try() { # $1 libellé, $2 attendu (pass|block), puis les commits séparés par "--"
  local label="$1" want="$2"; shift 2
  git checkout -q -b "b$RANDOM" main
  for f in "$@"; do [ "$f" = -- ] && { git commit -q -m c; continue; }; touch_ "$f"; done
  git commit -q -m c
  if git push -q origin HEAD 2>/dev/null; then got=pass; else got=block; fi
  git checkout -q main
  [ "$got" = "$want" ] && echo "  ok   $label" || { echo "  FAIL $label (obtenu $got)"; fail=1; }
}
try "A — fichier servi, sans bump"                 block app.js
try "B — bump dans son PROPRE commit (même branche)" pass  app.js -- BUMP
try "C — sw.js modifié, CACHE_NAME inchangé"        block sw.js
try "D — prose seule"                           pass  README.md
try "E — tests + sync seulement"                   pass  tests/x.py sync/y.py
try "F — prose + servi, sans bump"              block README.md index.html
[ $fail -eq 0 ] && echo "TOUS LES CAS PASSENT" || echo "DES CAS ÉCHOUENT"
exit $fail
