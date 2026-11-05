"""Vérifie l'interpréteur Python et les dépendances avant de lancer AnimeDL."""
from __future__ import annotations

import sys

MIN_VERSION = (3, 10)
MAX_MINOR = 13
MODULES = {
    "playwright": "playwright",
    "yt_dlp": "yt-dlp",
    "yaml": "PyYAML",
    "requests": "requests",
    "imageio_ffmpeg": "imageio-ffmpeg",
}


def check() -> int:
    version = sys.version_info
    if version[:2] < MIN_VERSION or version.minor > MAX_MINOR:
        print(f"Python {version.major}.{version.minor} n'est pas supporté par AnimeDL.")
        print(f"Il faut Python 3.{MIN_VERSION[1]} à 3.{MAX_MINOR}.")
        print("")
        print("PyYAML et greenlet n'ont pas encore de wheels pour 3.14/3.15 :")
        print("pip essaie de compiler et réclame Microsoft Visual C++.")
        print("")
        print("Solution :")
        print("  winget install -e --id Python.Python.3.13")
        print("  py -3.13 -m venv .venv")
        print("  .\\.venv\\Scripts\\python -m pip install -r requirements.txt")
        return 2

    missing = []
    for module, package in MODULES.items():
        try:
            __import__(module)
        except Exception:
            missing.append(package)

    if missing:
        print("Dépendances manquantes : " + ", ".join(missing))
        print("Installe-les avec :")
        print(f'  "{sys.executable}" -m pip install -r requirements.txt')
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(check())
