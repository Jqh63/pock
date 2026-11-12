#!/usr/bin/env bash
# test_deploy_guard.sh — banc de la garde origin/main de sync/deploy.sh.
#
# deploy.sh pousse ce que contient l'arbre de travail : lancé depuis une
# branche non mergée, un clone en retard ou un fichier modifié, il livrait à
# la VM du code non relu ou périmé, sans un mot. Dépôts git jetables + ssh
# bouchonné ; les états sains d'abord (une garde qui refuse un clone sain
# finit contournée).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../deploy.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0
ok()   { if [ "$1" = "$2" ]; then echo "  ok   $3"; else echo "  FAIL $3 (want=$1 got=$2)"; fail=1; fi }
has()  { if printf '%s' "$2" | grep -- "$1" >/dev/null; then echo "  ok   $3"; else echo "  FAIL $3"; fail=1; fi }
none() { if [ -s "$1" ]; then echo "  FAIL $2 (appels ssh : $(tr '\n' ' ' < "$1"))"; fail=1; else echo "  ok   $2"; fi }

G() { git -c user.name=bench -c user.email=bench@example.invalid -c init.defaultBranch=main "$@"; }

# ssh bouchonné : note la route, réussit toujours. Ne lit stdin que sur
# push-* : les autres routes n'en reçoivent pas et bloqueraient dessus.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/ssh" <<'EOF'
#!/usr/bin/env bash
shift  # retire l'alias
echo "$*" >> "$SSH_CALLS"
case "$1" in push-*) cat > /dev/null ;; esac
exit 0
EOF
chmod +x "$TMP/bin/ssh"

# Un origin neuf + un clone portant le deploy.sh testé et le fichier qu'il pousse.
mkrepo() {  # $1 = dossier du cas → $1/origin.git, $1/clone
  mkdir -p "$1"
  G init -q --bare "$1/origin.git"
  G clone -q "$1/origin.git" "$1/clone" 2>/dev/null
  mkdir -p "$1/clone/sync" "$1/clone/other"
  cp "$SCRIPT" "$1/clone/sync/deploy.sh"
  echo "app v1" > "$1/clone/sync/app.py"
  echo "x" > "$1/clone/other/file"
  G -C "$1/clone" add -A
  G -C "$1/clone" commit -q -m init
  G -C "$1/clone" push -q origin HEAD:main
}

run() {  # $1 = dossier du cas
  : > "$1/calls"
  OUT="$(SSH_CALLS="$1/calls" PATH="$TMP/bin:$PATH" bash "$1/clone/sync/deploy.sh" 2>&1)"; RC=$?
}

echo "cas A — SAIN : clone sur origin/main, propre"
mkrepo "$TMP/a"; run "$TMP/a"
ok 0 "$RC" "exit 0"
has "^apply-pock-sync$" "$(cat "$TMP/a/calls")" "apply atteint"

echo "cas B — SAIN : HEAD détachée sur origin/main (worktree)"
mkrepo "$TMP/b"; G -C "$TMP/b/clone" checkout -q --detach; run "$TMP/b"
ok 0 "$RC" "exit 0"

echo "cas C — SAIN : modifs hors sync/ + fichier non suivi dedans"
mkrepo "$TMP/c"; echo "y" >> "$TMP/c/clone/other/file"; echo "n" > "$TMP/c/clone/sync/notes.txt"; run "$TMP/c"
ok 0 "$RC" "exit 0"

echo "cas D — commit non mergé sur une branche"
mkrepo "$TMP/d"
G -C "$TMP/d/clone" checkout -q -b feat/x
echo "app v2" > "$TMP/d/clone/sync/app.py"; G -C "$TMP/d/clone" commit -q -am wip
run "$TMP/d"
ok 4 "$RC" "exit 4"
has "origin/main" "$OUT" "nomme origin/main"
none "$TMP/d/calls" "rien envoyé à la VM"

echo "cas E — clone en retard sur origin/main"
mkrepo "$TMP/e"
G clone -q "$TMP/e/origin.git" "$TMP/e/other-clone"
echo "app v2" > "$TMP/e/other-clone/sync/app.py"
G -C "$TMP/e/other-clone" commit -q -am newer; G -C "$TMP/e/other-clone" push -q origin HEAD:main
run "$TMP/e"
ok 4 "$RC" "exit 4"
none "$TMP/e/calls" "rien envoyé à la VM"

echo "cas F — fichier suivi modifié sous sync/ (non indexé, puis indexé)"
mkrepo "$TMP/f"; echo "app hack" > "$TMP/f/clone/sync/app.py"; run "$TMP/f"
ok 4 "$RC" "exit 4 (non indexé)"
has "sync/app.py" "$OUT" "nomme le fichier modifié"
none "$TMP/f/calls" "rien envoyé à la VM"
G -C "$TMP/f/clone" add sync/app.py; run "$TMP/f"
ok 4 "$RC" "exit 4 (indexé)"

echo "cas G — fetch impossible : pas mesuré = refus"
mkrepo "$TMP/g"; G -C "$TMP/g/clone" remote set-url origin "$TMP/g/gone.git"; run "$TMP/g"
ok 4 "$RC" "exit 4"
has "fetch" "$OUT" "dit que le fetch a échoué"
none "$TMP/g/calls" "rien envoyé à la VM"

echo "cas H — échappement : DEPLOY_ALLOW_UNMERGED=1 déploie et le dit"
: > "$TMP/d/calls"
OUT="$(DEPLOY_ALLOW_UNMERGED=1 SSH_CALLS="$TMP/d/calls" PATH="$TMP/bin:$PATH" bash "$TMP/d/clone/sync/deploy.sh" 2>&1)"; RC=$?
ok 0 "$RC" "exit 0"
has "DEPLOY_ALLOW_UNMERGED" "$OUT" "avertissement affiché"
has "^apply-pock-sync$" "$(cat "$TMP/d/calls")" "apply atteint"

[ "$fail" -eq 0 ] && echo "TOUS LES CAS PASSENT" || { echo "DES CAS ÉCHOUENT"; exit 1; }
