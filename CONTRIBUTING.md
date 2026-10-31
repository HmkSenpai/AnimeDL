# Contribuer

Merci de prendre le temps de contribuer.

## Signaler un problème

Un bon rapport contient :

- la commande exécutée (URL anonymisée) ;
- le message d'erreur complet ;
- `logs/fail-*.json` **nettoyé** des cookies, tokens et URLs signées ;
- la version de Python, du système et de Playwright.

Utilisez les modèles d'issue quand ils existent. Pour une faille de sécurité,
ne créez pas d'issue publique : contactez directement le mainteneur.

## Proposer une modification

1. Forkez le dépôt et créez une branche :
   `git checkout -b feat/nom-court`
2. Installez les dépendances :
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\pip install -r requirements.txt
   # Linux/macOS
   .venv/bin/pip install -r requirements.txt
   python -m playwright install chromium
   ```
3. Vérifiez que tout passe :
   ```bash
   python _smoke/run_smoke.py
   python _smoke/adfilter/run_adfilter.py
   python _smoke/quality/run_quality.py
   python _smoke/sources/run_sources.py
   ```
4. Ouvrez une pull request en décrivant le problème résolu et les tests exécutés.

## Style de code

- Python 3.11+, annotations de type, `from __future__ import annotations`.
- Les messages utilisateur et les logs sont en français, le code et les
  identifiants en anglais.
- Pas de nouvelle dépendance sans justification : le projet reste volontairement
  limité à Playwright, yt-dlp, PyYAML, requests et imageio-ffmpeg.
- Toute logique spécifique à un site va dans `config.yaml`, pas dans le code.
- Respectez l'esprit des tests hors ligne : un correctif notable doit être
  couvert par une suite `_smoke/`.

## Sécurité et vie privée

Ne committez jamais :

- `.browser-profile/` (cookies de session) ;
- `user.yaml` (chemins personnels) ;
- `logs/` (URLs signées, tokens) ;
- un fichier `.mp4` ou un manifest capturé.

Ces chemins sont déjà dans `.gitignore`.
