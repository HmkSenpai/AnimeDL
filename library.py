"""Suivi hebdomadaire, reprise des téléchargements et états associés.

Données locales (non versionnées) :
  - `watchlist.json` : liste des séries à surveiller ;
  - `sessions.json`  : résumé des téléchargements en cours / interrompus.

Les fonctions d'orchestration importent `main` à l'intérieur des fonctions pour
éviter un cycle d'import (main importe ce module pour enregistrer les sessions).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import ROOT, dump_json, load_config, log, read_json, resolve_path, safe_filename, set_verbose
from scraper import clean_title

WATCHLIST_PATH = ROOT / "watchlist.json"
SESSIONS_PATH = ROOT / "sessions.json"
FAILED_STATUSES = ("en_cours", "echoue", "interrompu")


# ------------------------------------------------------------------ watchlist
def load_watchlist(path: Path = WATCHLIST_PATH) -> list[dict[str, Any]]:
    data = read_json(path, {"entries": []})
    entries = data.get("entries", []) if isinstance(data, dict) else []
    return [e for e in entries if isinstance(e, dict) and e.get("url")]


def save_watchlist(entries: list[dict[str, Any]], path: Path = WATCHLIST_PATH) -> None:
    dump_json(path, {"entries": entries})


def valid_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def watch_add(url: str, name: str = "", path: Path = WATCHLIST_PATH) -> str:
    url = (url or "").strip()
    if not valid_url(url):
        return "URL invalide (http/https attendu)."
    entries = load_watchlist(path)
    if any(e["url"].rstrip("/") == url.rstrip("/") for e in entries):
        return "Cette série est déjà dans la liste."
    entries.append({"url": url, "name": (name or "").strip()})
    save_watchlist(entries, path)
    return f"Ajouté : {name or url}"


def watch_remove(index: int, path: Path = WATCHLIST_PATH) -> str:
    entries = load_watchlist(path)
    if not 1 <= index <= len(entries):
        return "Numéro hors liste."
    removed = entries.pop(index - 1)
    save_watchlist(entries, path)
    return f"Retiré : {removed.get('name') or removed['url']}"


def series_key(url: str) -> str:
    """Clé stable pour une série, même si on passe une URL d'épisode."""
    parsed = urlparse((url or "").strip())
    path = parsed.path.rstrip("/")
    if re.search(r"-\d+-(?:vostfr|vf)/?$", path, re.I):
        path = path.rsplit("/", 1)[0]
    return parsed._replace(path=path or "/", query="", fragment="").geturl().lower()


# ------------------------------------------------------------------- sessions
def load_sessions(path: Path = SESSIONS_PATH) -> dict[str, dict[str, Any]]:
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


def save_sessions(data: dict[str, dict[str, Any]], path: Path = SESSIONS_PATH) -> None:
    dump_json(path, data)


def session_start(
    url: str,
    title: str,
    output: str,
    progress_path: str,
    total: int,
    options: dict[str, Any],
    path: Path = SESSIONS_PATH,
) -> None:
    data = load_sessions(path)
    data[series_key(url)] = {
        "url": url,
        "title": title,
        "output": output,
        "progress": progress_path,
        "status": "en_cours",
        "total": total,
        "done": 0,
        "failed": [],
        "options": options,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_sessions(data, path)


def session_finish(
    url: str,
    status: str,
    done: int,
    failed: list[str],
    total: int,
    path: Path = SESSIONS_PATH,
) -> None:
    data = load_sessions(path)
    key = series_key(url)
    entry = data.setdefault(key, {"url": url, "title": title_from_url(url)})
    entry.update({
        "status": status,
        "done": done,
        "failed": sorted(failed),
        "total": total,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    save_sessions(data, path)


def title_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[-1] if parts else url


def suggest_name(url: str) -> str:
    """Nom lisible proposé quand on ajoute une série à la watchlist."""
    slug = re.sub(r"-\d+-(?:vostfr|vf)/?$", "", title_from_url(url), flags=re.I)
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words)


def session_unfinished(path: Path = SESSIONS_PATH) -> list[dict[str, Any]]:
    pending = [e for e in load_sessions(path).values() if e.get("status") in FAILED_STATUSES]
    return sorted(pending, key=lambda e: str(e.get("updated", "")), reverse=True)


# ------------------------------------------------------------ args / lancement
def _args_for(url: str, cfg: dict[str, Any], from_ep: int = 0, limit: int = 0):
    """Construit les arguments CLI à partir des préférences courantes."""
    import main  # import différé : évite le cycle main -> library -> main

    argv = [url]
    if from_ep:
        argv += ["--from-ep", str(from_ep)]
    if limit:
        argv += ["--limit", str(limit)]
    sources = str(cfg.get("sources") or "").strip()
    if sources:
        argv += ["--sources", sources]
    quality = str(cfg.get("quality") or "").strip()
    if quality and quality != "ask":
        argv += ["--quality", quality]
    display = str(cfg.get("display") or "window").lower()
    if display == "hidden":
        argv.append("--hidden")
    elif display == "headless":
        argv.append("--headless")
    browser = str(cfg.get("browser") or "").strip()
    if browser and browser != "auto":
        argv += ["--browser", browser]
    if cfg.get("base_output"):
        argv += ["--output", str(cfg["base_output"])]
    if cfg.get("verbose"):
        argv.append("--verbose")
    return main.build_parser().parse_args(argv)


def _args_from_entry(entry: dict[str, Any], cfg: dict[str, Any]):
    """Reconstruit les arguments d'une session sauvegardée."""
    import main

    args = main.build_parser().parse_args([entry["url"]])
    for key, value in (entry.get("options") or {}).items():
        if key != "url" and hasattr(args, key):
            setattr(args, key, value)
    args.from_ep = 0       # on ne veut pas sauter les épisodes en échec antérieurs
    args.limit = 0
    args.retry_failed = True
    args.verbose = bool(cfg.get("verbose"))
    return args


def ask_index(label: str, count: int) -> int | None:
    while True:
        try:
            raw = input(label).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw.lower() in ("q", "quit", "annuler"):
            return None
        if not raw:
            return 1
        if raw.isdigit() and 1 <= int(raw) <= count:
            return int(raw)
        log("  Numéro invalide.")


# --------------------------------------------------------------- last episodes
def run_latest(cfg: dict[str, Any] | None = None, dry_run: bool = False,
               path: Path = WATCHLIST_PATH) -> int:
    """Pour chaque série suivie : ne télécharge que le dernier épisode disponible."""
    import main

    cfg = cfg or load_config()
    set_verbose(bool(cfg.get("verbose")))
    entries = load_watchlist(path)
    if not entries:
        log("[hebdo] liste vide — ajoute une série avec l'option 11.")
        return 0

    fresh = skipped = failed = 0
    for entry in entries:
        url = entry["url"]
        name = entry.get("name") or title_from_url(url)
        try:
            title, episodes = main.peek_series(url, cfg)
        except Exception as exc:  # site indisponible, captcha, etc.
            log(f"[hebdo] {name} : lecture impossible ({type(exc).__name__}: {exc})")
            failed += 1
            continue
        if not episodes:
            log(f"[hebdo] {name} : aucun épisode détecté")
            failed += 1
            continue

        last = max(episodes, key=lambda ep: ep.number)
        out_dir = resolve_path(cfg["base_output"]) / safe_filename(clean_title(title, cfg))
        existing = [
            p for p in out_dir.glob(f"*S01E{last.code}.*")
            if p.suffix.lower() not in (".part", ".ytdl", ".json")
        ]
        if existing:
            log(f"[hebdo] {name} : E{last.code} déjà présent — pas encore sorti")
            skipped += 1
            continue

        log(f"[hebdo] {name} : E{last.code} disponible")
        if dry_run:
            fresh += 1
            continue
        try:
            code = main.run(_args_for(url, cfg, from_ep=last.number, limit=1))
        except Exception as exc:
            log(f"[hebdo] {name} : échec ({type(exc).__name__}: {exc})")
            failed += 1
            continue
        if code == 0:
            fresh += 1
        else:
            failed += 1

    log(f"[hebdo] terminé : {fresh} nouveau(x), {skipped} déjà présent(s), {failed} échec(s)")
    return 0 if not failed else 1


def run_resume(cfg: dict[str, Any] | None = None, index: int | None = None,
               path: Path = SESSIONS_PATH) -> int:
    """Reprend un téléchargement interrompu sans repartir de zéro."""
    import main

    cfg = cfg or load_config()
    set_verbose(bool(cfg.get("verbose")))
    pending = session_unfinished(path)
    if not pending:
        log("[reprise] aucun téléchargement interrompu.")
        return 0

    if index is None:
        log("\nTéléchargements à reprendre :")
        for i, entry in enumerate(pending, 1):
            codes = ", ".join(entry.get("failed", [])) or "-"
            log(f"  {i}) {entry.get('title') or entry['url']} — "
                f"{entry.get('done', 0)}/{entry.get('total', '?')} épisodes, échecs : {codes}")
        index = ask_index("  Numéro [1] (q = annuler) : ", len(pending))
        if index is None:
            return 0

    entry = pending[index - 1]
    log(f"[reprise] {entry.get('title') or entry['url']}")
    return main.run(_args_from_entry(entry, cfg))
