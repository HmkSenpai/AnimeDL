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
   appropriés, puis `verify()` contrôle durée, taille et absence de `.part`.
6. `Progress.mark_done()` / `mark_failed()` met à jour l'état, puis pause
   `delay_between_episodes_s`.

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

### Un épisode = un flux

Deux garde-fous empêchent d'enregistrer l'épisode précédent sous un nouveau nom :

1. **Identité de page** — `_canonical()` compare chemin **et query** : un site
   qui change d'épisode via `?ep=2` déclenche bien une navigation (avant, la
   query était ignorée, donc `_loaded_episode` restait inchangé).
2. **Identité de flux** — chaque manifest capté reçoit une empreinte
   (`premier segment + durée`). Si l'empreinte d'un épisode est déjà celle d'un
   autre, `main.py` refuse le téléchargement (`stream_identity_check`) et essaie
   le serveur suivant. Cela couvre le cas d'un player bloqué sur l'épisode
   précédent, qui joue la même vidéo dans une autre qualité.
3. **Vérification d'atterrissage** — après navigation, si l'URL finale désigne
   un autre numéro d'épisode (redirection), la capture est annulée au lieu de
   télécharger la mauvaise page.

### Profil persistant

`.browser-profile` conserve cookies, session et éventuel challenge anti-bot.
`--fresh-profile` le supprime, ce qui coûte une reconnexion mais repart propre.

## Fichiers d'état

| Fichier | Contenu |
|---|---|
| `.progress.json` | `done{code: {file, source}}`, `failed{code: raison}`, `quality` |
| `logs/fail-*.json` | URL visitées, requêtes `.m3u8`, erreurs, config utile |
| `logs/fail-*.png` | capture d'écran au moment de l'échec |
| `logs/probe-*.json/png` | rapport de `probe.py` |

## Tests

Les suites `_smoke/*` démarrent un serveur HTTP local et un flux HLS généré par
ffmpeg. Elles couvrent la capture, le filtrage publicitaire, la sélection de
variantes et la bascule multi-serveurs, sans réseau externe ni navigateur visible.
