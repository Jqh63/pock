#!/bin/bash
# Hook PreToolUse : bloque un `git commit` si le diff staged contient un
# secret a HAUTE CONFIANCE (forme complete de cle, pas un simple prefixe).
#
# Choix volontaire : on ne matche QUE des formes completes (prefixe +
# entropie suffisante) pour ne PAS bloquer les fichiers de doc du repo qui
# citent les prefixes nus (sk-, ghp_, Bearer) en exemple. Pour un audit
# plus large (mots de passe en clair, IP publique, *_TOKEN non ${VAR}),
# deleguer au subagent `secret-scanner`.
#
# exit 0 = laisse passer / non concerne ; exit 2 = bloque le commit.

INPUT=$(cat)

CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
# Ne s'active que sur un git commit
echo "$CMD" | grep -qE '\bgit\b.*\bcommit\b' || exit 0

DIFF=$(git diff --cached 2>/dev/null)
[ -z "$DIFF" ] && exit 0

# Formes completes uniquement (les prefixes nus en doc ne matchent pas) :
# - ghp_/gho_ + 36, github_pat_ + long  (GitHub PAT)
# - sk-ant- + long, sk- + 40+           (Anthropic / OpenAI-like)
# - AKIA + 16                           (AWS access key id)
# - bloc cle privee PEM
PATTERNS='ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}|sk-ant-[A-Za-z0-9_-]{40,}|sk-[A-Za-z0-9]{40,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

# Ne scanne que les lignes AJOUTEES (un secret qu'on retire ne doit pas bloquer)
HITS=$(echo "$DIFF" | grep -E '^\+' | grep -onE "$PATTERNS" 2>/dev/null | head -3)

# Formes SANS prefixe (2026-09-28 : un `openssl rand -hex 32` pose en « exemple »
# dans dash-pat/docs/HANDOFF.md etait le vrai token, invisible aux motifs ci-dessus).
# - hex nu >= 32 car., sauf 40 (SHA git) et sauf ligne qui parle de digest/SHA/
#   commit/pin (`@`)/plex.direct — mesure sur les 4 repos : 1 hit, le vrai.
# - hash bcrypt, sauf le hash admin AdGuard, versionne a dessein (knowledge-base).
# Banc : knowledge-base .claude/test-secret-scan-hook.sh (etats sains inclus).
HEX_CTX='sha(1|224|256|384|512)?|digest|checksum|integrity|hash|commit|uses:|@|plex\.direct'
BCRYPT_ALLOW='homelab/adguard/conf/AdGuardHome.yaml'
ADDED=$(echo "$DIFF" | awk '/^\+\+\+ /{f=$2; sub(/^b\//,"",f); next} /^\+/{print f "\t" substr($0,2)}')
HITS="$HITS
$(printf '%s\n' "$ADDED" | awk -F'\t' -v a="$BCRYPT_ALLOW" '$1 != a' | cut -f2- \
    | grep -oE '\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}' | sed 's/^/bcrypt:/' | head -3)
$(printf '%s\n' "$ADDED" | cut -f2- | grep -viE "$HEX_CTX" \
    | grep -oE '(^|[^0-9A-Za-z])[0-9a-f]{32,}([^0-9A-Za-z]|$)' | grep -oE '[0-9a-f]{32,}' \
    | awk 'length($0) != 40' | sed 's/^/hex:/' | head -3)"
HITS=$(printf '%s\n' "$HITS" | grep -v '^$' | head -3)

if [ -n "$HITS" ]; then
  {
    echo "✗ secret-scan : secret(s) à haute confiance détecté(s) dans le diff staged — commit bloqué."
    echo "  Type(s) repéré(s) : $(echo "$HITS" | sed -E '/^(bcrypt|hex):/{s/:.*/:****/;b}; s/[A-Za-z0-9_-]{6,}/****/g' | sort -u | tr '\n' ' ')"
    echo "  Action : retirer du diff et déplacer en variable OMV \${VAR_NAME}, vérifier .gitignore."
    echo "  Audit complet : déléguer au subagent secret-scanner."
  } >&2
  exit 2
fi

exit 0
