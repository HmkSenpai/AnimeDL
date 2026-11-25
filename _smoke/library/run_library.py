"""Tests hors ligne : titre nettoyé, suivi hebdo, reprise, mode verbose."""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from common import debug, is_verbose, log, set_verbose  # noqa: E402
from library import (  # noqa: E402
    load_sessions,
    load_watchlist,
    run_latest,
    run_resume,
    series_key,
    session_finish,
    session_start,
    session_unfinished,
    watch_add,
    watch_remove,
)
from scraper import Episode, clean_title  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE / ".work"


def captured(fn, *args, **kwargs) -> tuple[str, object]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return buf.getvalue(), result


def main_test() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    checks: list[tuple[bool, str]] = []

    cfg = {"title_prefix": "Regarder maintenant |Voir ", "title_suffix": "site.com | - VOSTFR"}
    checks.append((clean_title("Regarder maintenant [Mon anime] site.com", cfg) == "Mon anime",
                   "préfixe + suffixe retirés"))
    checks.append((clean_title("VOIR Mon anime - VOSTFR", cfg) == "Mon anime",
                   "alternatives `|` et casse ignorée"))
    checks.append((clean_title("Mon anime", cfg) == "Mon anime", "titre sans marqueur inchangé"))
    checks.append((clean_title("", cfg) == "serie", "titre vide -> repli"))

    # ------------------------------------------------------------ watchlist
    wl = WORK / "watchlist.json"
    watch_add("https://site.test/anime/serie-a/", "Série A", wl)
    watch_add("https://site.test/anime/serie-b/", "Série B", wl)
    _, msg = captured(watch_add, "https://site.test/anime/serie-a/", "doublon", wl)
    checks.append((len(load_watchlist(wl)) == 2 and "déjà" in msg, "doublon refusé"))
    checks.append(("invalide" in watch_add("pas-une-url", path=wl), "URL invalide refusée"))
    watch_remove(2, wl)
    checks.append(([e["url"] for e in load_watchlist(wl)] == ["https://site.test/anime/serie-a/"],
                   "retrait par numéro"))

    # ------------------------------------------------------------- sessions
    sj = WORK / "sessions.json"
    session_start("https://site.test/anime/serie-a/", "Série A", "out", "out/.progress.json",
                  12, {"url": "https://site.test/anime/serie-a/", "quality": "worst"}, sj)
    checks.append((len(session_unfinished(sj)) == 1, "session en cours listée"))
    session_finish("https://site.test/anime/serie-a/", "echoue", 9, ["03", "07"], 12, sj)
    pending = session_unfinished(sj)
    checks.append((len(pending) == 1 and pending[0]["failed"] == ["03", "07"],
                   "échecs conservés pour reprise"))
    session_finish("https://site.test/anime/serie-a/", "termine", 12, [], 12, sj)
    checks.append((not session_unfinished(sj), "session terminée retirée de la reprise"))
    checks.append((series_key("https://x.test/anime/serie/serie-03-vostfr/")
                   == series_key("https://x.test/anime/serie/"), "URL épisode = clé série"))

    # ----------------------------------------------------------- verbose
    previous = is_verbose()
    set_verbose(False)
    out_off, _ = captured(debug, "[debug]")
    out_log, _ = captured(log, "[info]")
    set_verbose(True)
    out_on, _ = captured(debug, "[debug]")
    set_verbose(previous)
    checks.extend([
        (out_off == "" and out_on == "[debug]\n", "debug silencieux sauf --verbose"),
        (out_log == "[info]\n", "log toujours visible"),
    ])

    # ------------------------------------------------- suivi hebdo (dry-run)
    weekly = WORK / "weekly.json"
    watch_add("https://site.test/anime/serie-a/", "Série A", weekly)
    peeked = ("Série A", [
        Episode(1, "https://site.test/anime/serie-a/serie-a-01-vostfr/", "vostfr", "E01"),
        Episode(2, "https://site.test/anime/serie-a/serie-a-02-vostfr/", "vostfr", "E02"),
    ])
    original_peek = main.peek_series
    main.peek_series = lambda url, cfg=None: peeked  # type: ignore[assignment]
    out_dir = WORK / "out" / "Série A"
    out_dir.mkdir(parents=True)
    (out_dir / "Série A - S01E02.mp4").write_bytes(b"x")
    weekly_cfg = {"base_output": str(WORK / "out"), "title_prefix": "", "title_suffix": ""}

    text, code = captured(run_latest, weekly_cfg, True, weekly)
    checks.append((code == 0 and "pas encore sorti" in text,
                   f"E02 présent -> pas encore sorti ({text.strip()})"))
    (out_dir / "Série A - S01E02.mp4").unlink()
    text, code = captured(run_latest, weekly_cfg, True, weekly)
    checks.append((code == 0 and "E02 disponible" in text,
                   "dernier épisode manquant -> disponible"))

    # ------------------------------------------------------------- reprise
    main.peek_series = original_peek  # type: ignore[assignment]
    sj2 = WORK / "resume.json"
    session_start("https://site.test/anime/serie-a/", "Série A", "out", "out/.progress.json",
                  12, {"url": "https://site.test/anime/serie-a/", "from_ep": 5,
                       "quality": "worst", "limit": 3}, sj2)
    seen: dict = {}

    def fake_run(args):
        seen.update(vars(args))
        return 0

    original_run = main.run
    main.run = fake_run  # type: ignore[assignment]
    _, code = captured(run_resume, {}, 1, sj2)
    main.run = original_run  # type: ignore[assignment]
    checks.append((code == 0 and seen.get("retry_failed") is True
                   and seen.get("from_ep") == 0 and seen.get("limit") == 0
                   and seen.get("quality") == "worst",
                   "reprise : retry activé, filtres from_ep/limit ignorés"))

    shutil.rmtree(WORK, ignore_errors=True)
    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main_test())
