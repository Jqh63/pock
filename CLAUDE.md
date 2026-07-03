# Pock — Documentation technique

> À lire en premier par tout outil IA travaillant sur ce repo. Pock est
> **public** (GitHub Pages) et personnel — règles cadrées en
> conséquence.

## Règles non-négociables

1. **Aucune donnée personnelle dans le code ou les commits.** Pas de
   vraie adresse email, pas de nom complet, pas de données financières
   ou d'historique perso en exemple. Les données utilisateur vivent
   dans le `localStorage` du navigateur (+ copie serveur perso si la
   sync opt-in est activée, cf. `sync/README.md`).
2. **Aucun secret** (token, API key, password) dans le code. Le token
   de sync n'apparaît jamais dans le repo : généré côté serveur, saisi
   manuellement par appareil (cf. *Sync*).
3. **Pas de force-push.** Jamais.
4. **Identité git noreply** configurée localement :
   `Jqh63 <12471916+Jqh63@users.noreply.github.com>`. Jamais d'email
   perso dans un commit.
5. **Ne pas modifier `CLAUDE.md` sans demande explicite.** Améliorer
   la doc de sa propre initiative est hors scope — proposer, attendre
   le feu vert.

## Workflow

- Toute modification passe par une **branche éphémère + PR** — pas de
  push direct sur `main`.
- Format de branche : `<type>/<sujet-court>` — types alignés sur les
  conventional commits : `feat`, `fix`, `docs`, `chore`, `refactor`,
  `security`.
- Commits **conventional commits en français, à l'impératif** :
  `type: description courte` (pas de scope — le repo est mono-projet).
  Pas de point final, sujet < 72 caractères.
- Les chaînes user-facing dans le code restent en **français**
  (`<html lang="fr">`, labels boutons, toasts). Cette règle ne
  concerne pas les messages commit / titres de PR / doc, qui peuvent
  rester en français aussi pour la cohérence.
- Ouvrir les PRs avec `gh pr create`. Merger via l'UI GitHub ou
  `gh pr merge <num> --merge --delete-branch` (préserver l'historique,
  pas de squash).

## Avant chaque commit

- `git status` — vérifier les fichiers staged
- `git diff --cached` — relire le diff
- `grep -E '(sk-|ghp_|Bearer |password\s*=)' <fichiers-modifiés>` —
  dernière ligne de défense secrets dans ce repo public
- Vérifier le message de commit (conventional, français, impératif,
  pas de point final)

Si quelque chose semble louche (fichier inattendu, chaîne suspecte,
scope flou), arrêter et signaler avant de pousser.

## Discipline d'édition

- **Atomicité** : 1 commit = 1 changement logique. Ne pas bundler un
  fix avec un refacto non lié — ouvrir des PRs séparées.
- **Éditions ciblées** : préférer `Edit` ciblé à la réécriture
  complète d'un fichier. Ne pas relire les fichiers "pour comprendre
  le contexte" au-delà de ce qui est strictement nécessaire.
- **Pas d'auto-fix opportuniste**. Si tu repères un problème en
  dehors de la tâche en cours (typo dans un commentaire, lien obsolète,
  aria-label manquant), ne le corrige pas silencieusement. Signale,
  propose (issue, PR de suivi, laisser tel quel), laisse l'utilisateur
  trancher.
- **Pas de features spéculatives.** Pas d'error handling pour des cas
  qui ne peuvent pas arriver, pas d'abstractions pour des besoins
  hypothétiques. Le code est petit, explicite > élégant.

## Versioning et propagation

Le service worker (`sw.js`) cache l'app. **Bumper la version `CACHE`
à chaque release qui change l'UX** pour déclencher l'auto-update PWA
chez les utilisateurs installés :

- `sw.js` : `const CACHE_NAME = 'pock-vN'` — entier monotone, +1 à chaque release UX (v1 → v14…). Pas de marqueur de version dans le footer (le footer affiche `Pock · Données stockées localement`).

Pas de staging — `main` est en production via GitHub Pages. Tester
sur l'URL publique après merge.

## Outillage .claude/

Skills sur-mesure dans `.claude/skills/` :

- **release-pwa** — bumper le marqueur visuel + la version `CACHE` du SW
  pour déclencher l'auto-update PWA. À lancer à chaque release qui
  change l'UX.
- **smoke-test** — smoke test Playwright vérifiant que chaque app charge
  proprement (pas d'erreur JS/console, titre attendu, rendu visible). À
  lancer avant toute PR touchant le code d'une app.

## Scope volontairement limité

- **Pas de framework JS, pas de build, pas de `package.json`.** Un
  fichier HTML par app = portabilité maximale et audit visuel facile.
- **Pas de tracking, pas de cookies, pas de backend par défaut.**
  Exception scoped actée (2026-06-11) : la **sync opt-in** vers un
  serveur personnel — le mini blob store vit dans `sync/` de ce repo
  (couplé à la PWA, pattern miroir du relais WoL de `plex-jqh-omv`).
  Sans configuration par l'utilisateur, rien n'est jamais envoyé.
- Toute autre feature exigeant un backend (relais HTTP→UDP,
  notifications push avec serveur) → **repo séparé**.

## En cas de doute

Demander à l'auteur plutôt que d'inventer. Le repo est petit, le
contexte rarement ambigu — mais quand il l'est, une question vaut
mieux qu'un commit à revert.

---

## Détails techniques (chargés à la demande)

L'état technique de référence — architecture, décisions UX par app, clés
localStorage, service worker, pièges connus, historique des versions SW —
vit dans [`.claude/docs/notes-techniques.md`](.claude/docs/notes-techniques.md).
À lire au besoin quand la tâche touche le code d'une app ; **pas `@`-importé**,
pour garder ce router léger au démarrage.
