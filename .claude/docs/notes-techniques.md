# Pock — Notes techniques (état actuel)

> Référence technique chargée **à la demande** (pas `@`-importée), depuis
> [`../../CLAUDE.md`](../../CLAUDE.md) § *Détails techniques*. Le router reste
> `CLAUDE.md` ; ici = l'état de l'implémentation (architecture, décisions UX
> par app, clés localStorage, service worker, pièges, historique des versions).

## Qu'est-ce que c'est ?

Pock est une collection de petites web apps personnelles (PWA). Pas de framework, pas de build, pas de backend — juste des fichiers HTML/CSS/JS autonomes servis via GitHub Pages. Plus aucune dépendance externe depuis la v13 (polices système, pas de Google Fonts).

**Déployé sur** : https://jqh63.github.io/pock/
**Repo** : https://github.com/jqh63/pock

## Contexte d'usage

Ces apps tournent sur Android, iOS et Chrome Windows 11 :
- **Covoiturage Rando** → la plus utilisée, pour calculer les frais de covoiturage lors de sorties de club de randonnée
- **Suivi km LOA** → suivi du kilométrage de véhicules en location longue durée (LOA)
- **Ma Bibliothèque** → suivi de livres à lire / en cours / lus / réservés / empruntés

Le code est public sur GitHub mais les données restent dans le localStorage de chaque navigateur, jamais partagées ni uploadées. Un export/import JSON manuel est dispo depuis le hub pour backup ou migration d'appareil.

La roadmap, les décisions d'architecture et le contexte plus large vivent dans un repo `knowledge-base` privé de l'auteur. Ne pas le citer par URL ou chemin dans ce repo public — paraphraser ou résumer si une référence est nécessaire.

## État actuel

- Service Worker : `pock-v16`
- 3 apps live : covoiturage-rando, suivi-km-loa, bibliotheque
- Panneau Export/Import sur le hub (JSON, mode fusion ou remplacement)
- **Sync opt-in** (v16) : couche dans `common.js` + config sur le hub
  (URL + token Bearer) vers le blob store `sync/` self-hébergé. Pull au
  chargement, push debounced 1,5 s (flush `keepalive` quand l'onglet
  passe en arrière-plan), last-write-wins par app (`updatedAt`), reload
  unique gardé par sessionStorage si le serveur est plus récent. Hook
  `Storage.prototype.setItem/removeItem` (filtré localStorage + préfixes
  d'app) : tout point de sauvegarde est couvert sans câblage par app.
- PWA complète (manifest, icônes PNG, auto-update via `controllerchange` avec garde anti-boucle)
- Structure à plat : tous les fichiers à la racine du repo
- Base partagée : `common.css` (reset, tokens, focus, fade) + `common.js` (esc, genId, SW reg, export/import, sync)
- Polices 100 % système (`-apple-system`, `ui-monospace`, `Georgia`) — plus de Google Fonts, plus de dépendance réseau
- Inputs à 16px minimum (iOS Safari auto-zoom prevention)
- Match exact dans le SW (plus d'`ignoreSearch`, toutes les URLs sont internes donc déterministes)
- Cache SW ne stocke que les réponses same-origin (`resp.type === 'basic'`)
- XSS protégé via helper `esc()` **effectivement** appliqué partout (v13 a corrigé le cas oublié dans covoit)

## Architecture

- Chaque app est un **fichier HTML unique** avec son CSS et son JS spécifiques inline
- Le **commun** est extrait dans deux fichiers partagés (`common.css`, `common.js`) importés par toutes les pages — ~300 lignes de CSS et quelques helpers JS ne se répètent plus
- Données en **localStorage** (pas de serveur, pas de base)
- Toutes les clés de storage préfixées `pock-`
- PWA : `manifest.json` + `sw.js` pour offline et "Ajouter à l'écran d'accueil"
- Icônes PNG (obligatoire iOS : apple-touch-icon ne supporte pas SVG)
- Tout rendu par JS vanilla (pas de React, Vue, etc.)
- Pattern : un `render()` reconstruit tout l'HTML via `innerHTML` à chaque changement d'état

## Arborescence du repo (15 fichiers à la racine, hors dotfiles)

```
index.html              ← Hub + panneau Export/Import · ordre : Rando → Véhicules → Lecture → Données
covoiturage-rando.html  ← Calculateur covoiturage (0,30€/km)
suivi-km-loa.html       ← Tracker km LOA (multi-véhicules)
bibliotheque.html       ← Suivi de livres
common.css              ← Reset, tokens, stacks polices système, .pock-back, focus, fade
common.js               ← esc, genId, enregistrement SW, pockExport/pockImport, sync
sync/                   ← Blob store de sync self-hébergé (FastAPI) — app.py, unit systemd, env.example, README
manifest.json           ← Manifest PWA (name: Pock)
sw.js                   ← Service worker (cache-first, match exact)
icon-192.png            ← Icône standard
icon-512.png            ← Grande icône
icon-maskable.png       ← Icône maskable avec safe zone
apple-touch-icon.png    ← iOS écran d'accueil (180px)
README.md               ← README public pour visiteurs GitHub
LICENSE                 ← Licence du projet
CLAUDE.md               ← Router instructions IA (ce fichier)
```

## Clés localStorage

- `pock-km-vehicles` — configs véhicules : `[{id, name, color, startDate, durationMonths, kmPerYear, excessCostPerKm}]`
- `pock-km-[vehicleId]` — relevés km par véhicule : `[{id, date, km}]` — les `id` sont désormais générés par `genId()` (timestamp base36 + random)
- `pock-km-active` — id du dernier véhicule sélectionné
- `pock-covoit-history` — historique covoiturage (20 derniers calculs)
- `pock-biblio-books` — collection de livres : `[{id, title, author, note, status, addedAt}]` — à l'import en masse, `addedAt` est staggéré (`base + index`) pour un tri date stable
- `pock-sync-url` / `pock-sync-token` / `pock-sync-meta` — config sync + timestamps last-write par app (uniquement si la sync est activée). Ces clés ne matchent aucun préfixe d'app → jamais incluses dans les blobs poussés (mais incluses dans l'export JSON `pock-*` du hub)

## Export / Import

Le hub `index.html` contient un panneau "Données" (bouton dépliable en bas de page). Il utilise `common.js` :

- **Export** : `pockExportToFile()` dump toutes les clés `pock-*` dans un fichier JSON `pock-backup-YYYY-MM-DD.json` (format `{version:1, exportedAt, data:{clé:valeur…}}`)
- **Import** : `pockImportFromJSON(text, mode)` avec mode `merge` (par défaut, écrit par-dessus) ou `replace` (supprime d'abord toutes les clés `pock-*` existantes)
- Confirmation native `confirm()` avant import, plus explicite pour le mode `replace`

## Données par défaut (premier lancement)

Le suivi km pré-remplit 2 véhicules d'exemple si `pock-km-vehicles` est null :
- **Véhicule 1** — couleur `#3563e9`, début 2024-01-01, 37 mois, 10 000 km/an, 0,15€/km excédentaire
- **Véhicule 2** — couleur `#00796b`, début 2024-06-01, 37 mois, 10 000 km/an, 0,12€/km excédentaire

Une migration au chargement ajoute `excessCostPerKm` aux véhicules existants si absent.

Palette couleurs véhicules : `#3563e9`, `#00796b`, `#d97706`, `#9333ea`, `#dc2626`, `#0891b2`, `#4f46e5`, `#059669`

## Décisions UX clés

### Suivi km

- En haut : sélecteur véhicules + bouton "+" pour en ajouter
- Hero "Écart vs prévu" en grand (l'info principale)
- Carte "Coût km excédentaires" si un taux est défini : actuel + projeté fin de contrat
- **Projection conditionnelle** : un seul relevé suffit. Le rythme est calculé sur la durée écoulée du contrat (`currentKm / daysElapsed`), pas sur l'écart entre relevés — ça évite de devoir maintenir un historique dense, ce qui n'est pas dans l'usage réel (effacement cache, changement d'appareil, saisies espacées). Affichée à partir de 30 jours de contrat (en dessous, le rythme est trop bruité). Si le dernier relevé date de plus de 60 jours, un warning "dernier relevé il y a X j, pense à mettre à jour" apparaît à côté du chiffre.
- Projection cappée à `Math.max(currentKm, projected)` (ne peut jamais être < km actuel)
- Quick-add toujours visible (date + km + bouton), pas de modal
- Puis KPIs, barres de progression (temps vs km), graphique SVG, liste des relevés
- Validation : refuse dates futures et dates avant début contrat (alert), confirm si le km baisse vs relevé précédent
- Si contrat terminé : banner "Contrat terminé" + coût final (plus de projection)
- Si contrat pas encore commencé : banner "Contrat démarre dans X jours"
- **Bouton "Réinitialiser les relevés"** (v13) dans le header du véhicule actif : vide les relevés sans supprimer la config du véhicule

### Covoiturage

- `type="text"` avec `inputmode="numeric"` + `pattern="[0-9]*"` — **PAS** `type="number"` (ça causait des bugs de re-ordre de chiffres sur pavé numérique Android, et les spinners sont indésirables)
- Pas de re-render pendant la saisie (sinon curseur perdu). `syncForm()` lit les valeurs DOM juste avant tout render déclenché par un bouton
- Bouton Calculer toujours actif (pas de `disabled`), validation via `errorMsg` affiché en rouge
- Messages d'erreur distincts : "Remplis tous les champs" vs "uniquement des nombres" vs "plus de voitures que de participants"
- Barème de secours (dépliable, avec `aria-expanded`) au cas où l'app n'est pas accessible
- Historique des 20 derniers calculs
- **esc() appliqué** sur les valeurs de formulaire et les dates d'historique (v13 a corrigé un oubli qui permettait un self-XSS)

### Biblio

- 5 statuts : to_read, reading, read, reserved, borrowed (avec couleurs et labels FR)
- Import en masse via séparateurs : priorité `;` ou `|` ou tab > tiret entouré d'espaces. Important : le tiret est détecté uniquement s'il est entouré d'espaces, pour ne pas casser "Jean-Paul Sartre"
- Format : `Titre ; Auteur ; Note`
- Recherche par titre ou auteur, tri date/titre/auteur
- Position du curseur préservée pendant la recherche
- **Tri date stable** (v13) : tiebreaker sur `id` en cas d'`addedAt` identique. À l'import batch, chaque livre reçoit un `addedAt` incrémenté (`base + index`) pour un ordre déterministe
- **`confirm()` sur delete livre** (v13) avec le titre du livre dans le message — évite les mistap sur la cible ✕

## Conventions de code

- UI en français, code et commentaires en anglais
- Tous les inputs à `font-size: 16px` minimum (anti auto-zoom iOS Safari)
- Saisie numérique mobile : `type="text" inputmode="numeric" pattern="[0-9]*"` (ou `inputmode="decimal"` pour les prix en €) **partout** — v13 a éliminé les derniers `type="number"` qui traînaient dans suivi-km
- Chaque page HTML contient : title, meta description, theme-color, meta apple-*, lien manifest, icon, apple-touch-icon, `<link>` vers `common.css`, `<script src>` vers `common.js`
- Base commune : ne pas redéfinir dans chaque app ce qui est déjà dans `common.css` (reset `*`, `body`, `.pock-back`, `@keyframes pockFadeIn`, `:focus-visible`) et `common.js` (`esc()`, `genId()`, enregistrement SW, export/import)
- CSS utilise des custom properties (`--bg`, `--surface`, `--border`, `--text`, `--text2`, `--text3`, `--accent`, etc.) — définies dans `common.css` avec des valeurs par défaut, chaque app peut les override
- Polices **exclusivement système** (plus de Google Fonts) :
  - `--font-sans` : stack Apple/Segoe UI/Roboto
  - `--font-mono` : `ui-monospace`, SF Mono, Menlo, Consolas
  - `--font-serif` : Georgia, Iowan Old Style, Palatino
  - Biblio garde son caractère "livre" via `--font-serif` sur les titres (Playfair remplacé par Georgia)
- **Aucune dépendance JS externe** — vanilla uniquement
- XSS : tout contenu user-generated passe par `esc()` (createElement-based, dans common.js)
- **Pas de `window.storage`** (c'était l'API Claude Artifacts, pas pour la prod)
- **Pas de `selectionStart/End` sur number inputs** (crash iOS Safari) — mais vu qu'on n'utilise plus `type="number"`, le risque est annulé
- A11y : `aria-label` sur tous les boutons icône (`✎`, `✕`, `+`, `✓`), `aria-expanded` sur les toggles dépliables, `role="img"` + `aria-label` sur le SVG du graphique suivi-km, `for=` sur les labels

## Service Worker

```
const CACHE_NAME = 'pock-v15';  // bumper à chaque changement d'assets
```

- Stratégie : cache-first, fallback réseau
- Tous les HTML + `common.css` + `common.js` + icônes pré-cachés à l'install
- `skipWaiting()` + `clients.claim()` pour activation immédiate
- **Match exact** (plus d'`ignoreSearch`) — plus besoin depuis qu'on n'a plus de Google Fonts avec URLs à query
- Garde `resp.type === 'basic'` avant mise en cache (évite de stocker des réponses opaques cross-origin)
- L'enregistrement est dans `common.js` avec un **flag `refreshing`** qui empêche le `controllerchange` de déclencher des reloads multiples

Extrait registration (dans common.js) :
```js
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').catch(() => {});
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  });
}
```

## Procédure pour ajouter une nouvelle app

1. Créer `new-app.html` — copier les meta PWA d'une app existante
2. Ajouter `<link rel="stylesheet" href="common.css">` dans le head
3. Ajouter le lien retour `<a class="pock-back" href="index.html">← Pock</a>` en haut
4. Ajouter `<script src="common.js"></script>` AVANT le script de l'app (pour que `esc`, `genId`, la registration SW soient dispo)
5. Ajouter une carte dans `index.html` (emoji icon + couleur accent)
6. Ajouter le fichier à l'array `ASSETS` dans `sw.js`
7. Incrémenter `CACHE_NAME` dans `sw.js` (`pock-vN`)
8. Documenter la clé localStorage utilisée (ce fichier + README.md)
9. Tester iOS Safari (font-size 16px+, inputmode, tap targets) et Android Chrome
10. Vérifier que le zip de release ne contient que les fichiers du repo (pas de doc perso)

## Cibles de compatibilité

- Chrome (Android + Windows + macOS) — cible principale
- Safari (iOS + macOS)
- Firefox (toutes plateformes)
- Éviter : modules ES, top-level await, optional chaining dans les chemins critiques pour anciens Safari

## Pièges connus à éviter

1. **`type="number"` + re-render sur input** : sur Android, les chiffres du pavé numérique arrivent dans le désordre. Solution appliquée en v13 : `type="text" inputmode="numeric"` partout.
2. **`selectionStart` sur number input** : crash iOS Safari. Comme on n'a plus de `type="number"`, le risque est éliminé — mais rester vigilant si un jour on y revient.
3. **`font-size < 16px` sur un input** : iOS Safari zoome automatiquement au focus.
4. **Icônes SVG pour `apple-touch-icon`** : pas supporté, il FAUT du PNG.
5. **`innerHTML` sans `esc()`** : XSS possible si des données utilisateur sont injectées (titres de livres, noms de véhicules, valeurs de formulaire, etc.). Règle : dès qu'une variable vient d'un input, d'un localStorage ou d'un calcul dérivé, elle passe par `esc()`.
6. **Cache SW non bumpé** : les modifications ne se propagent pas. Toujours incrémenter `CACHE_NAME`.
7. **Parser avec tiret simple** : "Jean-Paul" casse si le tiret est considéré comme séparateur. Exiger des espaces autour.
8. **Projection kilométrique avec peu de données** : un seul relevé précoce (type 500 km à J+10) extrapole à 56 000 km sur 37 mois — absurde. Solution : seuil sur l'âge du contrat (30 j minimum), pas sur le nombre de relevés. Le rythme s'appuie sur `currentKm / daysElapsed` (durée écoulée du contrat), pas sur l'écart entre relevés — un seul relevé récent suffit. Si le dernier relevé est trop ancien (60 j+), warning visible.
9. **Projection kilométrique après fin de contrat** : peut donner un chiffre inférieur au réel. Capper à `Math.max(currentKm, projected)`.
10. **`ignoreSearch: true` + plusieurs URLs Google Fonts** : toutes les URLs `css2?family=…` matchaient la première cachée, ce qui cassait Playfair offline. Problème éliminé en v13 en passant aux polices système.

## Déploiement

1. `git add .` et push sur le repo `pock`
2. GitHub → Settings → Pages → Source : main branch
3. URL : `https://<user>.github.io/pock/`
4. Install mobile : ouvrir dans le navigateur → "Ajouter à l'écran d'accueil"

## Évolutions envisagées (discutées mais non implémentées)

- Synchronisation via Git (trop complexe, nécessiterait un backend pour les tokens)
- URL params `?km=XXX` sur suivi-km-loa pour auto-remplir depuis un widget externe (abandonné : pas de widget constructeur exploitable sans OCR)
- **Modales custom** pour remplacer les `confirm()` / `alert()` natifs — **écarté volontairement** : les gains (cohérence visuelle, bouton d'action nommé) ne justifient pas le coût (~120 lignes, focus trap, scroll-lock iOS, tests a11y). Le natif reste en place.
- Notifications PWA mensuelles "Relève ton compteur"
- Share Target PWA pour biblio (recevoir un titre + auteur partagé depuis Babelio, Goodreads, etc.)

## Historique des versions SW

- v1 → v2 : conversion SVG → PNG icons (iOS compat)
- v3 → v4 : ajout icon-maskable dans le cache
- v5 : ajout `ignoreSearch`, `esc()` partout, `controllerchange`
- v6 → v7 : refonte UX covoiturage (type=text, pas de re-render)
- v8 → v9 : tentative URL params (annulée)
- v10 : ajout carte coût km excédentaires
- v11 : fix parser biblio tiret, validation dates suivi-km, projection cappée
- v12 : flat structure (icônes à la racine, suppression dossier icons/)
- v13 : refonte post-audit
  - extraction `common.css` + `common.js` (fin des ~300 lignes CSS dupliquées)
  - polices 100 % système (suppression Google Fonts, fix du bug offline où Playfair tombait en fallback)
  - `type="text" inputmode="numeric"` uniformisé (suivi-km avait des `type="number"` qui violaient la convention)
  - `esc()` effectivement appliqué partout (covoit était oublié)
  - projection km : seuil basé sur l'âge du contrat uniquement (30 j), un relevé suffit. Warning si le dernier relevé date de > 60 j. Cohérent avec un usage où la donnée est rarement maintenue dans la durée.
  - `genId()` pour les ids de relevés km (évite les collisions `Date.now()`)
  - `confirm()` sur delete livre (biblio), avec le titre dans le message
  - bouton "Réinitialiser les relevés" dans suivi-km (sans supprimer la config véhicule)
  - `aria-label`/`aria-expanded`/`role="img"` ajoutés sur les éléments interactifs et décoratifs
  - légende du graph suivi-km conditionnelle (ne montre plus "Réel" sans courbe)
  - tri date stable dans biblio + stagger `addedAt` à l'import batch
  - panneau Export/Import JSON sur le hub
  - match SW exact (plus d'`ignoreSearch`) + `resp.type === 'basic'` avant cache
  - garde anti-boucle sur `controllerchange` (flag `refreshing`)
  - contraste `--text3` renforcé (`#94a1b2` → `#7a889a`) pour lisibilité AA du petit texte
- v16 : sync cross-device opt-in (serveur `sync/` + couche client `common.js` + config hub)
- v14 : assouplissement de la règle de projection km
  - seuil sur le nombre de relevés retiré (un seul relevé suffit)
  - seuil sur l'âge du contrat passé de 14 à 30 jours
  - rythme calculé sur durée écoulée du contrat, pas sur écart entre relevés
  - warning visible si le dernier relevé date de > 60 jours (pousse à mettre à jour avant de se fier au chiffre)
