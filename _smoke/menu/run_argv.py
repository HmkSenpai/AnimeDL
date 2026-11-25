"""Test : saisie « URL + options » collée dans le menu."""
from __future__ import annotations

import builtins
import contextlib
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import build_argv, resolve_choice, split_input, watchlist_menu  # noqa: E402
from common import log  # noqa: E402
import library  # noqa: E402
from library import load_watchlist, watch_add  # noqa: E402
from main import build_parser  # noqa: E402

CFG = {"sources": "", "display": "window"}

CASES = [
    (
        "URL seule",
        "https://site.test/anime/serie/",
        CFG,
        ["https://site.test/anime/serie/"],
    ),
    (
        "options après l'URL",
        "https://site.test/anime/serie/ --from-ep 12",
        CFG,
        ["https://site.test/anime/serie/", "--from-ep", "12"],
    ),
    (
        "URL entre guillemets",
        '"https://site.test/anime/serie/" --quality 720 --limit 2',
        CFG,
        ["https://site.test/anime/serie/", "--quality", "720", "--limit", "2"],
    ),
    (
        "préférence serveurs ajoutée",
        "https://site.test/a/ --from-ep 3",
        {"sources": "1,2", "display": "window"},
        ["https://site.test/a/", "--from-ep", "3", "--sources", "1,2"],
    ),
    (
        "sources explicites non écrasées",
        'https://site.test/a/ --sources "4,1"',
        {"sources": "1,2", "display": "window"},
        ["https://site.test/a/", "--sources", "4,1"],
    ),
    (
        "affichage masqué ajouté",
        "https://site.test/a/",
        {"sources": "", "display": "hidden"},
        ["https://site.test/a/", "--hidden"],
    ),
    (
        "chemin Windows préservé",
        'https://site.test/a/ --output "D:\\Anime"',
        CFG,
        ["https://site.test/a/", "--output", "D:\\Anime"],
    ),
    (
        "dry-run ajouté une seule fois",
        "https://site.test/a/ --dry-run",
        CFG,
        ["https://site.test/a/", "--dry-run"],
    ),
]


def check_watchlist_menu() -> list[tuple[bool, str]]:
    """Le sous-menu affiche les séries suivies et distribue les actions."""
    import app

    work = HERE / ".work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    target = work / "watchlist.json"
    watch_add("https://site.test/anime/serie-alpha/", "Série Alpha", target)
    watch_add("https://site.test/anime/serie-beta/", "Série Beta", target)

    original_ask, original_run, original_input = app.ask, library.run_latest, builtins.input
    checks: list[tuple[bool, str]] = []
    try:
        answers = iter(["4", "0"])
        app.ask = lambda prompt, default="": next(answers, "") or default
        calls: list[tuple[bool, Path]] = []
        library.run_latest = lambda cfg, dry_run=False, path=None: (calls.append((dry_run, path)), 0)[1]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            watchlist_menu({}, target)
        text = buf.getvalue()
        checks += [
            ("WATCHLIST" in text and "1) Série Alpha" in text and "2) Série Beta" in text,
             "watchlist : noms des séries affichés"),
            (calls == [(True, target)], "watchlist : simulation lancée depuis le sous-menu"),
        ]

        answers = iter(["1", "https://site.test/anime/nouvelle-serie/", "", "0"])
        app.ask = lambda prompt, default="": next(answers, "") or default
        with contextlib.redirect_stdout(io.StringIO()):
            watchlist_menu({}, target)
        entries = load_watchlist(target)
        checks.append((len(entries) == 3 and entries[-1]["name"] == "Nouvelle Serie",
                       "watchlist : ajout avec nom suggéré"))

        answers = iter(["2", "0"])
        app.ask = lambda prompt, default="": next(answers, "") or default
        builtins.input = lambda prompt="": "2"
        with contextlib.redirect_stdout(io.StringIO()):
            watchlist_menu({}, target)
        checks.append(([e["name"] for e in load_watchlist(target)] == ["Série Alpha", "Nouvelle Serie"],
                       "watchlist : retrait au numéro"))
    finally:
        app.ask, library.run_latest, builtins.input = original_ask, original_run, original_input
        shutil.rmtree(work, ignore_errors=True)
    return checks


def main() -> int:
    checks: list[tuple[bool, str]] = []

    for label, raw, cfg, expected in CASES:
        got = build_argv(raw, cfg, dry_run="--dry-run" in raw)
        checks.append((got == expected, f"{label} -> {got}"))

    tokens = split_input("  https://site.test/a/   --from-ep 4  ")
    checks.append((tokens == ["https://site.test/a/", "--from-ep", "4"], f"espaces multiples -> {tokens}"))

    args = build_parser().parse_args(build_argv("https://site.test/a/ --from-ep 7 --quality 480", CFG))
    checks.append((args.url == "https://site.test/a/" and args.from_ep == 7 and args.quality == "480",
                   f"argparse cohérent -> url={args.url} from_ep={args.from_ep} quality={args.quality}"))

    options = ["ask", "best", "worst", "720"]
    checks += [
        (resolve_choice("3", options) == "worst", "menu : numéro 3 -> worst"),
        (resolve_choice("", options, 2) == "worst", "menu : entrée vide -> défaut"),
        (resolve_choice("99", options) is None, "menu : numéro hors liste refusé"),
        (resolve_choice("0", options) is None, "menu : 0 refusé"),
        (resolve_choice("best", options) == "best", "menu : valeur exacte acceptée"),
        (resolve_choice("nimporte quoi", options) is None, "menu : texte libre refusé"),
    ]
    checks += check_watchlist_menu()

    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
