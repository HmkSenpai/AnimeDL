# AnimeDL

**Télécharge une série entière depuis un player HLS : capture du `master.m3u8`, export MP4, reprise automatique.**

[![CI](https://github.com/HmkSenpai/AnimeDL/actions/workflows/ci.yml/badge.svg)](https://github.com/HmkSenpai/AnimeDL/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#installation)
<center><img width="732" height="185" alt="image" src="https://github.com/user-attachments/assets/ce4c2b9e-800c-427e-ad42-0bfe1c44b8a4" /></center>

AnimeDL pilote un vrai navigateur (Playwright) pour déclencher le player, capter
l'URL signée du manifest HLS, puis laisse `yt-dlp` + `ffmpeg` produire un `.mp4`.
Il parcourt la liste des épisodes, essaie automatiquement les différents serveurs,
ignore les publicités et reprend là où il s'est arrêté.

```
page série ──► liste des épisodes ──► player (Playwright)
                                            │
                                  master.m3u8 signé (token frais)
                                            │
                                     validation HLS
                                            │
                                 yt-dlp + ffmpeg ──► S01E01.mp4
```

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Ligne de commande](#ligne-de-commande)
- [Configuration](#configuration)
- [Serveurs multiples](#serveurs-multiples)
- [Qualité vidéo](#qualité-vidéo)
- [Publicités et validation du flux](#publicités-et-validation-du-flux)
- [Affichage du navigateur](#affichage-du-navigateur)
- [Fichiers produits](#fichiers-produits)
- [Dépannage](#dépannage)
- [Tests](#tests)
- [Structure du projet](#structure-du-projet)
- [Avertissement](#avertissement)
- [Licence](#licence)

---

## Fonctionnalités

- **Liste d'épisodes automatique** à partir d'une URL de série (ou d'épisode).
- **Capture HLS réelle** : le token du manifest est régénéré pour chaque épisode,
  donc pas de lien expiré.
- **Serveurs illimités** : détection d'un `<select>` natif, d'onglets ou de boutons
  (`LECTEUR myTV / MOON / VOE / Stape`, …) et bascule automatique en cas d'échec.
- **Filtre anti-publicité** : blocage réseau, fermeture des popups, `window.open`
  neutralisé, et rejet des manifests trop courts (pré-roll).
- **Choix de la qualité** (SD / HD / FHD) demandé une seule fois, mémorisé pour la série.
  Le script remonte au `master.m3u8` pour que le choix s'applique vraiment, et
  vérifie la résolution réelle du fichier obtenu.
- **Barre de progression stable** (fragments HLS, pourcentage, vitesse, ETA).
- **Reprise** : `.progress.json` saute les épisodes déjà terminés ; `--retry-failed`
  rejoue les échecs.
- **Garde-fou anti-doublon** : refuse un épisode dont le flux est identique au
  précédent (player bloqué), au lieu d'enregistrer deux fois la même vidéo.
- **Vérification du fichier final** : durée, taille, absence de `.part`.
- **Menu interactif** (`AnimeDL.bat`) ou CLI complète.
- **Aucun ffmpeg à installer** : `imageio-ffmpeg` embarque le binaire.
- **Aucun Chromium à télécharger** si Chrome / Edge / Brave est déjà présent.
- **Mise à jour intégrée** : `AnimeDL.bat --update` (git pull ou archive GitHub).

## Prérequis

| Élément | Détail |
|---|---|
| Python | 3.11 ou plus récent |
| Système | Windows 10/11, Linux ou macOS |
| Navigateur | Chrome, Edge ou Brave installé — sinon Chromium Playwright |
| Droits | aucun droit administrateur nécessaire |

## Installation

### Windows (recommandé)

```powershell
git clone https://github.com/HmkSenpai/AnimeDL.git
cd AnimeDL
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` crée un environnement `.venv`, installe les dépendances et ne
télécharge Chromium **que si aucun navigateur n'est déjà installé**.
`AnimeDL.bat` détecte ensuite `.venv` automatiquement.

### Linux / macOS

```bash
git clone https://github.com/HmkSenpai/AnimeDL.git
cd AnimeDL
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# facultatif : seulement si aucun Chrome/Edge/Brave n'est installé
python -m playwright install chromium
```

### Installation manuelle (tous systèmes)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # optionnel, voir ci-dessus
```

## Démarrage rapide

```powershell
AnimeDL.bat            # Windows
python app.py          # tous systèmes
```


<img width="740" height="696" alt="image" src="https://github.com/user-attachments/assets/0421ee1b-8a03-4fc1-b5b7-21e122f231b1" />


Les choix du menu sont enregistrés dans `user.yaml` (non versionné), qui
**surcharge** `config.yaml` sans le modifier.

Dans l'option 1, tu peux coller l'URL **et ses options sur la même ligne** :

```
  URL (+ options) : https://SITE/anime/ma-serie/ --from-ep 5 --quality 720 --limit 2
  Options retenues : --from-ep 5 --quality 720 --limit 2
```

Les guillemets autour de l'URL sont acceptés (et retirés), ainsi que les
chemins Windows (`--output "D:\Anime"`).

## Mise à jour

Le script est sur GitHub : une commande récupère la dernière version.

```powershell
AnimeDL.bat --update        # Windows (menu ou CLI)
python update.py            # tous systèmes
python update.py --check    # voir s'il y a du retard, sans rien modifier
python update.py --deps     # mettre à jour aussi les dépendances pip
```

- Dépôt git → `git fetch` + `git pull --ff-only` (repli `--rebase --autostash`
  si des fichiers locaux gênent) ;
- installation sans git → téléchargement de l'archive `main` et copie des
  fichiers, **sans écraser `config.yaml` ni `user.yaml`**.

Dans le menu interactif : option **9**.

## Ligne de commande

```bash
python main.py "https://SITE/anime/ma-serie/"                 # tout télécharger
python main.py "https://SITE/anime/ma-serie/" --dry-run       # lister seulement
python main.py "https://SITE/anime/ma-serie/" --limit 2       # tester 2 épisodes
```

| Option | Description |
|---|---|
| `URL` | URL de la série **ou** d'un épisode (positionnel, optionnel avec le menu) |
| `--output DOSSIER` | Remplace le dossier de sortie |
| `--limit N` | Ne traite que N épisodes |
| `--from-ep N` | Reprend à l'épisode N |
| `--retry-failed` | Rejoue les épisodes marqués en échec |
| `--redo N` | Refaire l'épisode N (supprime le fichier et l'état), répétable |
| `--dry-run` | Affiche la liste des épisodes sans rien télécharger |
| `--sources "1,2,4"` | Force l'ordre/le choix des serveurs (1 = premier du menu) |
| `--quality best\|worst\|720` | Qualité imposée pour toute la série |
| `--browser auto\|chromium\|chrome\|brave\|msedge` | Navigateur piloté |
| `--hidden` | Fenêtre réelle mais hors écran |
| `--headless` | Navigateur invisible (souvent bloqué par les anti-bots) |
| `--min-duration S` | Durée minimale d'un épisode valide (secondes) |
| `--min-size-mb N` | Taille minimale d'un fichier valide (Mo) |
| `--fresh-profile` | Repart d'un profil navigateur vierge (perte de session) |

Exemples :

```bash
python main.py "<url>" --from-ep 7 --quality 1080
python main.py "<url>" --sources "4,1,2" --hidden
python main.py "<url>" --retry-failed
python main.py "<url>" --redo 2 --redo 5     # refaire E02 et E05
```

## Configuration

`config.yaml` contient les réglages du projet ; `user.yaml` (créé par le menu)
les surcharge. Les deux sont fusionnés au démarrage.

| Clé | Défaut | Rôle |
|---|---|---|
| `base_output` | `~/Downloads/AnimeDL` | Dossier racine des séries (`~` accepté) |
| `user_data_dir` | `.browser-profile` | Profil navigateur persistant (cookies, session) |
| `headless` | `false` | Navigateur invisible |
| `capture_timeout_s` | `35` | Attente du `master.m3u8` après le clic Play |
| `source_buttons` | `[]` | Libellés d'onglets serveurs (si détection auto insuffisante) |
| `source_selectors` | `[]` | Sélecteurs CSS des onglets serveurs |
| `play_selectors` | liste | Sélecteurs CSS du bouton Play |
| `dismiss_selectors` | liste | Boutons de fermeture des popups |
| `episode_pattern` | `-(\d+)-(vostfr\|vf)/?$` | Regex des liens d'épisode (appliquée au chemin) |
| `prefer_vf` | `false` | Prendre la VF quand elle existe |
| `fragment_concurrency` | `4` | Fragments HLS téléchargés en parallèle |
| `delay_between_episodes_s` | `2` | Pause entre deux épisodes |
| `min_duration_s` | `30` | En dessous, le fichier est invalide |
| `min_size_mb` | `1` | Taille minimale d'un fichier valide |
| `max_sources` | `4` | Repli si aucun serveur n'est détecté sur la page |
| `browser` | `auto` | `auto`, `chromium`, `chrome`, `brave`, `msedge` |
| `display` | `window` | `window`, `hidden`, `headless` |
| `sources` | `""` | `""` = tous, sinon `"1,2,4"` |
| `quality` | `ask` | `ask`, `best`, `worst` ou une hauteur (`720`) |
| `min_manifest_duration_s` | `60` | En dessous, le flux capté est considéré comme une pub |
| `allow_unknown_duration` | `false` | Accepter un manifest sans durée lisible |
| `stream_identity_check` | `true` | Refuser un épisode dont le flux est identique au précédent |
| `ad_hosts` | `[]` | Domaines publicitaires supplémentaires à bloquer |
| `min_free_gb` | `1` | Pause si l'espace disque restant est inférieur |
| `ytdlp.cookies_from_browser` | `null` | ex. `chrome` si le CDN exige les cookies de session |
| `ytdlp.format` | `best` | Format yt-dlp |

## Serveurs multiples

Aucun nombre de serveurs n'est codé en dur :

1. AnimeDL inspecte chaque frame de la page.
2. Un `<select>` contenant des options `lecteur/serveur/source/player/mirror`
   est prioritaire : **toutes ses options** sont essayées dans l'ordre.
3. Sinon, les onglets et boutons correspondants sont cliqués successivement
   (ouverture du menu déroulant si nécessaire).
4. Dès qu'un manifest valide est trouvé, il est utilisé. Si le téléchargement
   échoue, le serveur suivant est essayé.

```bash
python main.py "<url>" --sources "4,1,2"   # ordre imposé
```

## Qualité vidéo

À la première capture, les variantes du `master.m3u8` sont listées :

```
Qualités disponibles pour cet épisode :
  1)  1080p   4.2 Mb/s   1920x1080
  2)   720p   1.8 Mb/s   1280x720
  3)   480p   0.9 Mb/s    854x480
Choix [1-3, Entrée = 1] :
```

Le choix s'applique à **tous les épisodes** et est mémorisé dans `.progress.json`.
Sans terminal interactif, la meilleure qualité est utilisée.

Quand le player a déjà demandé une sous-playlist (`index-v1-a1.m3u8`), le script
remonte au **master** capté sur la même page : c'est la seule façon de faire
respecter `worst` / `720`. Si le site n'expose aucun master, le flux unique est
utilisé et la ligne suivante s'affiche :

```
[hls] flux unique (aucune variante) — la qualité ne peut pas être modifiée
```

Après chaque téléchargement, la résolution réelle est vérifiée :

```
[dl] OK Anime - S01E02.mp4 — 98.4 Mo en 41s, durée 1440s, 640x360
[dl] ⚠ qualité réelle 1080p pour 480p demandés : le flux n'expose peut-être pas cette variante
```

## Barre de progression

Une barre est réécrite sur place (pourcentage, Mo, vitesse, ETA) :

```
E02 ████████░░░░░░░░░░░░░░  36%   98.4/665.8 Mo  4.2 Mo/s  ETA 02:14
```

Elle est recalculée sur le nombre de fragments HLS (pas sur la taille estimée),
donc elle ne recule pas. Dans un fichier de log (sortie non interactive), la
barre est écrite en lignes de 5 %.

## Publicités et validation du flux

- blocage réseau des régies connues et des `ad_hosts` ;
- fermeture des popups ouverts au clic sur Play ;
- `window.open` neutralisé au chargement de chaque page et de chaque frame ;
- **validation de chaque manifest capté** : requête HTTP avec les cookies du
  navigateur, contrôle de `#EXTM3U`, des segments et de la **durée totale**.
  Un flux plus court que `min_manifest_duration_s` est ignoré (pub pré-roll).

C'est ce mécanisme qui évite les classiques `Did not get any data blocks` de
yt-dlp sur un manifest publicitaire.

## Affichage du navigateur

La capture nécessite un vrai navigateur : le site génère le lien `master.m3u8`
en JavaScript, avec un token lié à la session et au User-Agent.

| Mode | Réglage | Comportement |
|---|---|---|
| `window` | défaut | fenêtre visible |
| `hidden` | `display: hidden` / `--hidden` | vraie fenêtre placée hors écran (recommandé) |
| `headless` | `display: headless` / `--headless` | invisible, souvent bloqué |

Une fois la capture faite, le téléchargement n'utilise plus le navigateur.

## Fichiers produits

```
<base_output>/<Titre série>/
├── <Titre> - S01E01.mp4
├── <Titre> - S01E02.mp4
└── .progress.json        # épisodes terminés, échecs, qualité choisie
```

En cas d'échec, `logs/` contient `fail-<épisode>-<date>.json` et un screenshot.
`probe.py` y dépose ses propres rapports.

## Dépannage

Guide détaillé : [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

```bash
python probe.py "https://SITE/anime/ma-serie/ma-serie-01-vostfr/"
```

`probe.py` liste les iframes, `<video>`, boutons Play et onglets serveurs,
clique sur les candidats et journalise tout le trafic réseau. C'est l'outil à
lancer en premier si un site change.

## Tests

Tests hors ligne : ils génèrent des flux HLS locaux et valident toute la chaîne
sans toucher à un site réel.

```bash
python _smoke/run_smoke.py                 # capture -> mp4
python _smoke/adfilter/run_adfilter.py     # pub pré-roll ignorée
python _smoke/quality/run_quality.py       # variantes SD/HD/FHD
python _smoke/sources/run_sources.py       # 4 serveurs, bascule automatique
python _smoke/browsers/check.py            # navigateurs déjà installés
python _smoke/menu/run_argv.py             # saisie « URL + options » du menu
python _smoke/master/run_master.py         # master (multi-qualités) préféré au flux du player
python _smoke/episodes/run_identity.py     # un épisode = un flux différent
```

La CI (GitHub Actions) exécute la compilation et ces tests sur Ubuntu.

## Structure du projet

```
AnimeDL.bat        lanceur Windows du menu
app.py             menu interactif
main.py            orchestrateur (CLI, boucle, serveurs, reprise)
scraper.py         extraction de la liste des épisodes
capture.py         Playwright : Play, serveurs, interception du manifest
hls.py             validation du manifest et extraction des variantes
adblock.py         blocage publicitaire et neutralisation des popups
downloader.py      yt-dlp + vérification ffmpeg
progress.py        état .progress.json
common.py          configuration, logs UTF-8, ffmpeg, navigateurs, disque
update.py          mise à jour depuis GitHub (git pull ou archive zip)
probe.py           diagnostic du player
setup.ps1          installation Windows (venv + dépendances)
```

Détails d'architecture : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Avertissement

Cet outil est fourni à des fins personnelles et éducatives. Il ne contient aucun
contenu protégé et n'héberge aucun flux. Vous êtes responsable de l'usage que
vous en faites et devez respecter les conditions d'utilisation des sites
concernés ainsi que la législation de votre pays. Les auteurs déclinent toute
responsabilité quant à une utilisation abusive.

## Licence

[MIT](LICENSE) © AnimeDL contributors
