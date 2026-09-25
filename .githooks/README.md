# Hooks git

`pre-push` refuse un push de branche qui modifie un fichier servi sans bumper
`CACHE_NAME` dans `sw.js` (CLAUDE.md § versionnement). Jugé sur toute la
branche : un bump dans son propre commit passe.

```bash
git config core.hooksPath .githooks   # par clone — à refaire après un clone neuf
bash .githooks/test-pre-push.sh       # banc (repo jetable, sans réseau)
```

Rejoué le 2026-09-25 sur les 29 dernières PR touchant un fichier servi :
1 bloquée — #27 (grille du cycle HTA, `hta.html`), un vrai oubli de bump.
