# AnimeDL — téléchargement automatique d'épisodes (HLS → MP4)

Pilote un vrai navigateur pour capter le manifest `master.m3u8` d'un épisode,
puis `yt-dlp`/`ffmpeg` télécharge et assemble le `.mp4`. Boucle sur tous les
épisodes, avec repli automatique sur le serveur 2 et reprise après interruption.

## Installation

```powershell
cd C:\Users\Hinmaka\anime-dl
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`ffmpeg` est fourni par `imageio-ffmpeg` (aucune installation système requise).

## Utilisation

```powershell
# 1. Vérifier la liste des épisodes (ne télécharge rien)
python main.py "https://MON_SITE/anime/the-apothecary-diaries-3/" --dry-run

# 2. Tester sur 2 épisodes
python main.py "https://MON_SITE/anime/the-apothecary-diaries-3/" --limit 2

# 3. Téléchargement complet (reprise automatique si relancé)
python main.py "https://MON_SITE/anime/the-apothecary-diaries-3/"

# Variantes utiles
python main.py "<url>" --from-ep 7               # reprendre à l'épisode 7
python main.py "<url>" --retry-failed            # rejouer les échecs
python main.py "<url>" --sources "2,1"           # prioriser le serveur 2
python main.py "<url>" --output "D:/Anime"       # autre dossier de sortie
```

Sortie : `C:\Users\Hinmaka\Downloads\AnimeDL\<Titre série>\<Titre> - S01E01.mp4`
(le dossier est configurable via `base_output` dans `config.yaml`).

L'état est stocké dans `<dossier série>\.progress.json` : relancer la commande
saute automatiquement les épisodes déjà terminés.

## Anti-pub et validation du flux

- **Blocage réseau** des régies connues (`adblock.py`) + fermeture immédiate des
  popups + `window.open` neutralisé au chargement de chaque page.
- **Validation de chaque manifest capté** (`hls.py`) : requête HTTP avec les
  cookies du navigateur, vérification `#EXTM3U` et **durée totale**. Tout
  manifest plus court que `min_manifest_duration_s` (60 s par défaut) est
  considéré comme une pub et ignoré → fini les `Did not get any data blocks`.
- Si le site reste agressif, pilote Chrome ou **Brave** (boucliers intégrés) :

  ```powershell
  python main.py "<url>" --browser brave
  python main.py "<url>" --browser chrome
  ```

  Le profil est alors celui de Brave/Chrome (session, cookies, extensions).

## Choix de la qualité (SD / HD / FHD)

À la première capture, le script lit le `master.m3u8` et affiche les pistes
disponibles :

```
Qualités disponibles pour cet épisode :
  1)  1080p   4.2 Mb/s   1920x1080
  2)   720p   1.8 Mb/s   1280x720
  3)   480p   0.9 Mb/s    854x480
Choix [1-3, Entrée = 1] :
```

Le choix est appliqué à **tous les épisodes** et mémorisé dans
`.progress.json` (les relances le conservent). Pour le fixer sans interaction :

```powershell
python main.py "<url>" --quality 720     # 720p max
python main.py "<url>" --quality worst   # la plus légère
python main.py "<url>" --quality best    # la meilleure (défaut)
```

`quality: ask` dans `config.yaml` reproduit le comportement interactif.

## Si le player ne démarre pas (diagnostic)

```powershell
python probe.py "https://MON_SITE/anime/serie/serie-01-vostfr/"
```

Le probe liste les iframes, les `<video>`, les boutons Play et les onglets
serveurs, clique sur les candidats un par un, et affiche tout ce que le réseau
émet. Il écrit aussi `logs/probe-<date>.json` + `logs/probe-<date>.png`.

Quand une capture échoue, `main.py` dépose automatiquement
`logs/fail-<épisode>-<date>.json` et un screenshot — c'est ce qu'il faut
regarder (ou m'envoyer) pour ajuster `config.yaml`.

## Réglage si le site change

Tout est dans `config.yaml` :

| Clé | Rôle |
|---|---|
| `source_buttons` | Libellés exacts des onglets serveurs, dans l'ordre de repli |
| `source_selectors` | Sélecteurs CSS des onglets serveurs (prioritaires sur le texte) |
| `play_selectors` | Sélecteurs CSS du bouton Play |
| `dismiss_selectors` | Boutons de fermeture des popups/publicités |
| `episode_pattern` | Regex des liens d'épisodes (appliquée au chemin de l'URL) |
| `capture_timeout_s` | Temps d'attente du `master.m3u8` après le clic Play |
| `prefer_vf` | `true` pour prendre la VF quand elle existe |
| `min_manifest_duration_s` | En-dessous, le flux capté est vu comme une pub (60 s) |
| `allow_unknown_duration` | Accepter un manifest sans durée lisible (désactivé) |
| `max_sources` | Nombre de serveurs tentés avant abandon |
| `quality` | `ask`, `best`, `worst` ou une hauteur (`720`) |
| `ad_hosts` | Domaines pub supplémentaires à bloquer |
| `ytdlp.cookies_from_browser` | ex. `chrome` si le CDN exige les cookies de session |

## Architecture

```
main.py        orchestrateur CLI (boucle, repli serveurs, reprise)
scraper.py     liste des épisodes depuis la page série
capture.py     Playwright : clic Play + interception du master.m3u8 (token frais)
downloader.py  yt-dlp + vérification ffmpeg (durée, taille, .part)
progress.py    état .progress.json
common.py      config, logs UTF-8, ffmpeg, espace disque
```

## Test de fumée (hors ligne)

```powershell
python _smoke\run_smoke.py
```

Génère un flux HLS local, le sert, le capture avec Playwright, le télécharge et
vérifie le fichier : valide toute la chaîne sans toucher au site réel.
