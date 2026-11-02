"""AnimeDL — mise à jour depuis GitHub (git pull, sinon archive zip)."""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from common import log

REPO = "HmkSenpai/AnimeDL"
BRANCH = "main"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"

ROOT = Path(__file__).resolve().parent

# Fichiers jamais écrasés : réglages de l'utilisateur
KEEP_FILES = {"config.yaml", "user.yaml"}
# Dossiers de travail / caches
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".browser-profile",
    "logs",
    ".media",
    ".profile",
    "venv",
    ".venv",
}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), text=True, capture_output=True, errors="ignore"
    )


def git_update(check_only: bool = False) -> int | None:
    """Retourne None si le dossier n'est pas un dépôt git."""
    if not (ROOT / ".git").exists():
        return None

    log("[update] dépôt git détecté")
    fetch = _git("fetch", "origin", BRANCH)
    if fetch.returncode != 0:
        log("[update] git fetch impossible : " + (fetch.stderr or "").strip()[:300])
        return 1

    head = _git("rev-parse", "HEAD").stdout.strip()
    remote = _git("rev-parse", f"origin/{BRANCH}").stdout.strip()
    if head and head == remote:
        log("[update] déjà à jour ✔")
        return 0

    behind = _git("rev-list", "--count", f"HEAD..origin/{BRANCH}").stdout.strip()
    log(f"[update] {behind or '?'} commit(s) de retard")
    if check_only:
        return 0

    pull = _git("pull", "--ff-only", "origin", BRANCH)
    if pull.returncode != 0:
        log("[update] pull --ff-only refusé (modifs locales ?) — tentative rebase --autostash")
        pull = _git("pull", "--rebase", "--autostash", "origin", BRANCH)
    if pull.returncode != 0:
        log("[update] échec : " + (pull.stderr or pull.stdout).strip()[:500])
        return 1

    log(pull.stdout.strip()[:500])
    log(f"[update] à jour : {_git('log', '-1', '--oneline').stdout.strip()}")
    return 0


def zip_update(check_only: bool = False) -> int | None:
    """Met à jour sans git : télécharge l'archive de la branche main."""
    if check_only:
        log("[update] installation sans git : impossible de comparer les versions")
        return None

    log(f"[update] téléchargement de {ZIP_URL}")
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=120) as response:
            data = response.read()
    except Exception as exc:
        log(f"[update] téléchargement impossible : {type(exc).__name__}: {exc}")
        return 1

    log(f"[update] archive reçue ({len(data) / 1048576:.1f} Mo)")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        src = roots[0] if roots else Path(tmp)

        copied = 0
        for item in src.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(src)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if rel.name in KEEP_FILES:
                continue
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied += 1

    log(f"[update] {copied} fichier(s) mis à jour (config.yaml et user.yaml conservés)")
    return 0


def install_deps() -> int:
    log("[update] mise à jour des dépendances…")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "--upgrade", "--quiet"]
    )
    if proc.returncode != 0:
        log("[update] pip a échoué — lance : pip install -r requirements.txt")
    return proc.returncode


def run_update(check_only: bool = False, with_deps: bool = False) -> int:
    code = git_update(check_only=check_only)
    if code is None:
        code = zip_update(check_only=check_only)
    if code == 0 and with_deps and not check_only:
        code = install_deps()
    return code if code is not None else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="update", description="Met à jour AnimeDL depuis GitHub.")
    parser.add_argument("--check", action="store_true", help="Vérifie sans rien modifier")
    parser.add_argument("--deps", action="store_true", help="Réinstalle aussi les dépendances pip")
    args = parser.parse_args(argv)

    if shutil.which("git") is None and not (ROOT / ".git").exists():
        log("[update] git absent — mise à jour par archive zip")

    code = run_update(check_only=args.check, with_deps=args.deps)
    if code == 0 and not args.check:
        log("[update] termine. Relance AnimeDL (les modules déjà chargés restent en mémoire).")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
