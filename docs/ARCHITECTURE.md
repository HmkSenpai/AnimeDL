# Architecture

## Vue d'ensemble

```
main.py
  ├── scraper.py      → liste des épisodes (Playwright, page série)
  ├── capture.py      → master.m3u8 (Playwright, page épisode)
  │     └── hls.py    → validation + variantes
  ├── downloader.py   → mp4 (yt-dlp + ffmpeg)
  └── progress.py     → .progress.json
```

`app.py` ne fait qu'habiller `main.build_parser()` / `main.run()` avec un menu ;
la logique reste dans `main.py`, ce qui garantit que CLI et menu se comportent
exactement pareil.

## Cycle d'un épisode

1. `scraper.collect_episodes()` charge la page série et applique
   `episode_pattern` au chemin des liens pour produire `(code, langue, url)`.
2. `Progress` charge `.progress.json` : les épisodes `done` sont sautés.
3. `ManifestCapture.capture(url, source_index)` :
   - navigue si nécessaire (comparaison d'URL normalisée, sans query ni slash final) ;
   - détecte les serveurs (`<select>` natif prioritaire, puis onglets/boutons) ;
   - clique sur Play (plusieurs frames, plusieurs sélecteurs) ;
   - observe les réponses réseau et retient les URLs `.m3u8` candidates.
4. `hls.inspect()` rejoue chaque candidat en HTTP avec les en-têtes du navigateur
   (cookies, UA, Referer, Origin) et vérifie `#EXTM3U`, les segments et la durée.
   Les manifests trop courts sont rejetés (publicité).
5. `downloader.download()` appelle yt-dlp avec l'URL signée et les en-têtes
   appropriés, puis `common.ensure_mp4()` remuxe en vrai MP4 (index `moov` +
   `faststart`, copie sans réencodage) et `verify()` contrôle durée, taille et
   absence de `.part`.
6. `Progress.mark_done()` / `mark_failed()` met à jour l'état, puis pause
   `delay_between_episodes_s`.

### Pourquoi un remux forcé

Le téléchargeur HLS de yt-dlp écrit parfois les octets **MPEG-TS** tels quels
dans `<épisode>.mp4` (le `.mp4` n'est qu'une extension). Sans index `moov`, le
lecteur doit re-scanner le fichier à chaque déplacement : freezes de 3-5 s dans
la timeline. `ensure_mp4()` détecte le cas (`ftyp` absent, `moov` après `mdat`)
et remuxe avec `-c copy -movflags +faststart -avoid_negative_ts make_zero`.
`repair.py` applique la même fonction aux fichiers déjà téléchargés.

## Décisions de conception

### Token régénéré à chaque épisode

Le `master.m3u8` porte un token (`?t=…&h=…`) lié à la session et au temps. On ne
met donc **jamais** en cache un manifest : chaque épisode repasse par le player.
C'est aussi la raison pour laquelle un navigateur reste ouvert pendant toute la
série.

### Validation plutôt que confiance

Le player déclenche souvent une pub avant l'épisode. Filtrer sur l'URL ne suffit
pas (même hôte), d'où la validation par durée : `min_manifest_duration_s`
(60 s) sépare un pré-roll d'un épisode. `allow_unknown_duration` permet de
relâcher la règle pour les flux sans `#EXTINF` exploitable.

### Sources découvertes, pas configurées

`capture.JS_DETECT_SOURCES` renvoie deux structures : les `<select>` dont les
options ressemblent à des serveurs, et les éléments visibles dont le texte
correspond à `lecteur|serveur|source|player|mirror`. `main.run()` étend sa liste
de tentatives à partir de `capture.source_count()` : ajouter un serveur au site
ne demande aucune modification du code.

Cas particulier Brave : Playwright n'expose pas de canal `brave`, on lance donc
son binaire via `executable_path`. Chrome et Edge passent par `channel`.

### Progression stable

yt-dlp ré-estime la taille totale à chaque fragment HLS, ce qui fait « reculer »
une barre classique. `downloader.py` fige le total au premier `dltotal > 0`
(`frozen_total`) et calcule l'avancement par différence de `downloaded_bytes`.
Le pourcentage vient du couple `fragment_index` / `fragment_count`, plus fiable
que la taille estimée. `common.status_line()` réécrit la ligne sur place quand
la console est interactive (`\r`), sinon écrit une ligne tous les 5 %.

### Le master, pas la sous-playlist

Le player (hls.js) demande `master.m3u8`, puis **bascule** sur une variante
(`index-v1-a1.m3u8`). Les deux requêtes sont captées ; garder la dernière
revenait à figer la qualité choisie par le player — d'où un fichier en 1080p
même avec `quality: worst`.

`_evaluate_candidates()` collecte désormais tous les candidats valides de la
période et retient celui qui a le plus de variantes (`#EXT-X-STREAM-INF`). La
sélection `best[height<=720]` / `worst` de yt-dlp s'applique alors réellement.
Sans master, le flux unique est utilisé et un avertissement est loggé.
`probe_resolution()` relit la résolution du fichier final pour vérifier.



### Un épisode = un flux

Deux garde-fous empêchent d'enregistrer l'épisode précédent sous un nouveau nom,
plus un troisième qui ne regarde plus l'URL mais le contenu :

1. **Identité de page** — `_canonical()` compare chemin **et query** : un site
   qui change d'épisode via `?ep=2` déclenche bien une navigation (avant, la
   query était ignorée, donc `_loaded_episode` restait inchangé).
2. **Identité de flux** — chaque manifest capté reçoit une empreinte
   (`identifiant de média normalisé + durée`). L'identifiant est le chemin du
   manifest/variante débarrassé des marqueurs de qualité (`index-v1-a1` →
   `index`, dossier `1080/` ignoré) : le même épisode joué dans une autre
   variante garde donc la même empreinte, alors qu'un autre épisode change de
   dossier. L'empreinte est stockée dans `.progress.json`, donc un épisode
   téléchargé lors d'une exécution précédente est aussi protégé. Si elle
   correspond à un autre épisode, `main.py` recharge la page une fois
   (`forget_page()`), puis refuse le téléchargement
   (`stream_identity_check`) et passe au serveur suivant.
3. **Vérification d'atterrissage** — après navigation, si l'URL finale désigne
   un autre numéro d'épisode (redirection), la capture est annulée au lieu de
   télécharger la mauvaise page.
4. **Identité visuelle (filet de sécurité)** — `content.visual_hash()` extrait
   deux images 32x32 en gris à 35 % et 75 % de la durée du **fichier final** et
   les compare à ceux des épisodes déjà faits (`same_content()`, distance de
   Hamming ≤ 6 %). Un même épisode réencodé reste à ~0,2 % ; un autre épisode à
   ~60 %. Contrairement à l'empreinte du manifest, ça ne dépend ni du token ni
   du chemin CDN : si ça correspond, le fichier est supprimé, l'épisode marqué
   en échec et la page rechargée pour réessayer. Les épisodes anciens sans
   `content_hash` sont hashés au démarrage (une fois) pour compléter la couverture.

### Profil persistant

`.browser-profile` conserve cookies, session et éventuel challenge anti-bot.
`--fresh-profile` le supprime, ce qui coûte une reconnexion mais repart propre.

### Journal utilisateur vs développeur

`common.log()` est le canal utilisateur (état des épisodes, succès, erreurs) ;
`common.debug()` est muet sauf si `verbose: true`, `--verbose` ou
`ANIMEDL_DEBUG=1`. Clics Play, popup fermée, sélection de serveur, candidats HLS
et URLs complètes passent par `debug()`. `set_verbose()` est appelé au début de
`main.run()` pour que la CLI et le menu se comportent pareil.

### Suivi hebdomadaire et reprise

`library.py` gère deux fichiers d'état globaux :

- `watchlist.json` : paires `{url, name}` gérées dans le sous-menu **11** ;
  `run_latest()` ouvre chaque série avec `main.peek_series()` (navigation seule),
  prend le numéro d'épisode le plus haut, regarde si `S01E<NN>` existe déjà dans
  le dossier calculé depuis le titre nettoyé, puis télécharge uniquement cet
  épisode avec `main.run()` — ou annonce « pas encore sorti ».
- `sessions.json` : `main.run()` y enregistre l'URL, le titre, le dossier, le
  chemin du `.progress.json`, les options utilisées et l'état. La reprise
  (option 12) reconstruit un `argparse.Namespace` à partir de ces options, force
  `retry_failed=True` et remet `from_ep/limit` à zéro : seuls les épisodes
  manquants ou en échec sont rejoués.

`scraper.clean_title()` applique `title_prefix` / `title_suffix` (chaînes ou
listes séparées par `|`, comparaison insensible à la casse) avant tout calcul de
dossier, dans `main.run()` comme dans `run_latest()`.

## Fichiers d'état

| Fichier | Contenu |
|---|---|
| `.progress.json` | `done{code: {file, source, fingerprint, content_hash}}`, `failed{code: raison}`, `quality` |
| `watchlist.json` | séries suivies : `{entries: [{url, name}]}` |
| `sessions.json` | état des séries lancées, options de relance, épisodes en échec |
| `logs/fail-*.json` | URL visitées, requêtes `.m3u8`, erreurs, config utile |
| `logs/fail-*.png` | capture d'écran au moment de l'échec |
| `logs/probe-*.json/png` | rapport de `probe.py` |

## Tests

Les suites `_smoke/*` démarrent un serveur HTTP local et un flux HLS généré par
ffmpeg. Elles couvrent la capture, le filtrage publicitaire, la sélection de
variantes et la bascule multi-serveurs, sans réseau externe ni navigateur visible.
