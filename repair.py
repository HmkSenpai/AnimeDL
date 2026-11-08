"""Réparation des vidéos déjà téléchargées : remux en MP4 indexé (seek fluide).

Le téléchargeur HLS de yt-dlp a pu écrire un flux MPEG-TS dans un fichier
`.mp4`. Ce script le convertit en vrai MP4 (`moov` + `faststart`) sans
réencodage, ce qui supprime les freezes lors des déplacements dans la timeline.

Usage :
    python repair.py                      # dossier de sortie de la config
    python repair.py "D:\\Anime\\Ma série"
    python repair.py --dry-run            # liste sans rien modifier
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import ensure_mp4, load_config, log, mp4_is_indexed, resolve_path


def run_repair(root: Path, dry_run: bool = False) -> int:
    if not root.exists():
        log(f"[repair] dossier introuvable : {root}")
        return 1

    files = sorted(p for p in root.rglob("*.mp4") if p.is_file())
    todo = [p for p in files if not mp4_is_indexed(p)]
    log(f"[repair] {len(files)} fichier(s) MP4 — {len(todo)} à remuxer dans {root}")

    if dry_run:
        for path in todo:
            log(f"  - {path}")
        return 0

    fixed = failed = 0
    for index, path in enumerate(todo, 1):
        log(f"[repair] {index}/{len(todo)} {path.name}")
        if mp4_is_indexed(ensure_mp4(path)):
            fixed += 1
        else:
            failed += 1

    log(f"[repair] terminé : {fixed} réparé(s), {failed} échec(s)")
    return 0 if failed == 0 else 1


def main() -> int:
    cfg = load_config()
    default_root = cfg.get("base_output") or "."
    parser = argparse.ArgumentParser(
        description="Remuxe les vidéos existantes en MP4 indexé (seek fluide)."
    )
    parser.add_argument("path", nargs="?", default=str(default_root),
                        help=f"dossier à parcourir (défaut : {default_root})")
    parser.add_argument("--dry-run", action="store_true",
                        help="affiche les fichiers à réparer sans les modifier")
    args = parser.parse_args()
    return run_repair(resolve_path(args.path), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
