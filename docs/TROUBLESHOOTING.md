# Dépannage

## Réflexe n°1 : `probe.py`

```bash
python probe.py "https://SITE/anime/ma-serie/ma-serie-01-vostfr/"
```

Il affiche les iframes, les `<video>`, les boutons Play et les serveurs détectés,
puis journalise tout le réseau. Il écrit `logs/probe-<date>.json` et un screenshot.
En cas d'échec de capture, `main.py` produit de son côté
`logs/fail-<épisode>-<date>.json` + `.png`.

## Symptômes courants

| Message | Cause probable | Solution |
|---|---|---|
| `aucun épisode détecté` | URL d'épisode au lieu de la série, ou motif différent | vérifier `episode_pattern` ; lancer `--dry-run` |
| `aucun manifest exploitable après Xs` | Play manqué, iframe non chargée, anti-bot | `probe.py`, puis ajuster `play_selectors` ; essayer `--browser brave` |
| `Did not get any data blocks` | yt-dlp a reçu un manifest publicitaire | garder `min_manifest_duration_s: 60` ; ne pas le baisser sans raison |
| `manifest invalide/expiré ignoré` | token consommé ou URL de pub | normal : le script essaie le candidat suivant |
| Téléchargement très lent | CDN limité / trop de connexions | baisser `fragment_concurrency` |
| fichier trop petit / `verify` échoue | flux tronqué, mauvaise variante | relancer avec `--retry-failed` ; le serveur suivant sera essayé |
| popups à répétition | régie non listée | ajouter ses domaines dans `ad_hosts`, ou utiliser Brave |
| page « Checking your browser » | protection anti-bot | mode `hidden` plutôt que `headless`, ou navigateur réel (`--browser chrome`) |
| qualité toujours la même | choix mémorisé | supprimer `.progress.json` du dossier série, ou `--quality 1080` |
| **É02 contient É01** (image identique, autre qualité) | le player n'a pas changé d'épisode, ou la page a redirigé | le script refuse désormais ce cas (`stream_identity_check`) ; lancer `probe.py` sur É02 et vérifier que l'iframe change bien de `src` |
| `espace disque insuffisant` | `min_free_gb` atteint | libérer de l'espace ou changer `base_output` |
| `ffmpeg introuvable` | installation incomplète | `pip install imageio-ffmpeg` |

## Le site a changé

1. `probe.py` sur un épisode : noter les sélecteurs réels et les URLs `.m3u8`.
2. Mettre à jour `play_selectors` / `dismiss_selectors` dans `config.yaml`.
3. Si les serveurs ne sont ni un `<select>` ni des onglets textuels, renseigner
   `source_buttons` (libellés exacts) ou `source_selectors` (CSS).
4. Si les URLs d'épisodes changent de forme, adapter `episode_pattern` :

```yaml
# ex. /anime/xxx/xxx-05-vostfr/
episode_pattern: '-(\d+)-(vostfr|vf)/?$'
```

## Repartir proprement

```bash
# ignorer les cookies/session (nouvelle session, challenge anti-bot)
python main.py "<url>" --fresh-profile

# rejouer uniquement les échecs
python main.py "<url>" --retry-failed

# repartir de zéro sur une série
rm "<dossier série>/.progress.json"
```

## Logs

Les logs sont en UTF-8 sur stdout (console Windows incluse). Pour archiver une
session :

```powershell
python main.py "<url>" *> session.log
```

## Ce qu'il faut fournir pour un rapport de bug

- la commande exacte (URL anonymisée) ;
- `logs/fail-*.json` (pensez à retirer cookies et tokens) ;
- la version de Python, du système et de Playwright (`pip show playwright`).
