"""Test : saisie « URL + options » collée dans le menu."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import build_argv, split_input  # noqa: E402
from common import log  # noqa: E402
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

    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
