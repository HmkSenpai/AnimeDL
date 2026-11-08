"""AnimeDL — menu interactif (lancer : python app.py ou AnimeDL.bat)."""
from __future__ import annotations

import re
import shlex
import sys

from common import USER_PREFS_PATH, load_config, log, resolve_browser, resolve_path, save_user_prefs
from main import build_parser, run

BANNER = r"""
 ▄▀▀▀▀▀▀▀▀▀█ █▀▀▀▀▀▀▀▀▀▄  █▀▀▀▀█ █▀▀▀▀▀▀▀▀▀▄▀▀▀▀▀▄   ▄▀▀▀▀▀▀▀▀▀█      █▀▀▀▀▀▀▀▀▀▄  █▀▀▀▀█      
█   .▄▄   ∙▀ ▀    ▄▄    █ ▀    ▓ ▀    ▄▄     ▄    █ █·   ▄▄▄▄▄▄█      ▀    ▄▄ .  █ █·   █      
▓    ▐▄▌.  ▓ ▓    ▓ ▌   ▓ ▓    ▓ ▓    ▓ ▌   ▓ ▌   ▓ ▓  . ▓▄▄▄▄▄▄      ▓    ▓ ▌   ▓ ▓  . ▓      
▒∙ . ▄▄▄   ▒ ▒    ▒ ▒ · ▒ ▒   ·▒ ▒    ▒ ▒ · ▒ ▒ · ▒ ▒ ∙  ▄▄▄▄▄▄▒      ▒  · ▒▄▓   ▒ ▒ ∙  ▒      
░    ░ ░  ·░ ░   ∙░ ░   ░ ░ .  ░ ░   ∙░ ░   ░ ░   ░ ░    ░▄▄▄▄▄▄      ░       ·. ░ ░    ░▄▄▄▄▄▄
█ .  █ █   █ █ ∙  █ █   █ █    █ █ ∙  █ █   █ █   █ █    .    ·█      █   .      █ █    .    ·█
█▄▄▄▄█ █▄▄▄█ █▄▄▄▄█ █▄▄▄█ █▄▄▄▄█ █▄▄▄▄█ █▄▄▄█ █▄▄▄█ █▄▄▄▄▄▄▄▄▄▄█      █▄▄▄▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▄▄█  
                  téléchargement automatique d'épisodes  ·  v1.3 by Hinmaka
"""



def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix} : ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return value or default


def show_settings(cfg: dict) -> None:
    log("\n  Configuration actuelle")
    log("  " + "-" * 58)
    log(f"  Dossier de sortie : {cfg.get('base_output')}")
    log(f"  Qualité par défaut: {cfg.get('quality')}")
    browser_pref = str(cfg.get("browser") or "auto")
    resolved = resolve_browser(browser_pref)
    suffix = "" if resolved == "chromium" else " (installé, sans téléchargement)"
    log(f"  Navigateur        : {resolved}{suffix}")
    log(f"  Affichage         : {cfg.get('display', 'window')}")
    log(f"  Serveurs          : {cfg.get('sources') or 'auto (tous détectés)'}")
    log(f"  Anti-pub          : actif ({len(cfg.get('ad_hosts') or [])} hôte(s) perso)")
    log(f"  Préférences       : {USER_PREFS_PATH.name if USER_PREFS_PATH.exists() else 'aucune'}")


def resolve_choice(raw: str, options: list[str], default_index: int = 0) -> str | None:
    """Traduit une saisie en valeur de la liste (numéro ou valeur exacte)."""
    text = (raw or "").strip()
    if not text:
        return options[default_index] if 0 <= default_index < len(options) else None
    if text.isdigit():
        index = int(text) - 1
        return options[index] if 0 <= index < len(options) else None
    return text if text in options else None


def pick(title: str, options: list[tuple[str, str]], default: str = "") -> str | None:
    """Menu numéroté : renvoie la valeur choisie, ou None si annulé (q)."""
    values = [value for _, value in options]
    default_index = values.index(default) if default in values else 0

    while True:
        log(f"\n  {title}")
        for index, (label, _) in enumerate(options, 1):
            current = "   (actuel)" if index - 1 == default_index else ""
            log(f"    {index}) {label}{current}")
        raw = ask("  Choix", str(default_index + 1))
        if raw.strip().lower() in ("q", "quit", "annuler"):
            return None
        chosen = resolve_choice(raw, values, default_index)
        if chosen is None:
            log("  Choix invalide — entre un numéro de la liste.")
            continue
        return chosen


def split_input(raw: str) -> list[str]:
    """Découpe une saisie « URL + options » collée d'un seul bloc.

    Accepte les guillemets (Windows les laisse souvent collés) et préserve les
    antislashs des chemins (D:\\Anime). Ex:
        https://site/anime/x/ --from-ep 5   ->  ['https://site/anime/x/', '--from-ep', '5']
    """
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parts = shlex.split(text, posix=False)
    except ValueError:
        parts = text.split()

    tokens: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        if part:
            tokens.append(part)
    return tokens


def build_argv(raw: str, cfg: dict, dry_run: bool = False) -> list[str]:
    """Construit la ligne de commande finale à partir de la saisie et du menu."""
    argv = split_input(raw)
    if not argv:
        return []

    flags = {token.split("=", 1)[0] for token in argv if token.startswith("--")}

    if dry_run and "--dry-run" not in flags:
        argv.append("--dry-run")

    sources = str(cfg.get("sources") or "").strip()
    if sources and "--sources" not in flags:
        argv += ["--sources", sources]

    display = str(cfg.get("display") or "window").lower()
    if display == "hidden" and "--hidden" not in flags and "--headless" not in flags:
        argv.append("--hidden")
    elif display == "headless" and "--headless" not in flags and "--hidden" not in flags:
        argv.append("--headless")

    return argv


def run_download(raw: str, dry_run: bool = False) -> None:
    cfg = load_config()
    argv = build_argv(raw, cfg, dry_run)
    if not argv:
        log("  Aucune URL fournie.")
        return
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        log("  Options invalides — exemple correct : https://SITE/anime/serie/ --from-ep 5")
        return
    if not args.url:
        log("  URL manquante — exemple : https://SITE/anime/ma-serie/ --from-ep 5")
        return
    log(f"  Options retenues : {' '.join(argv[1:]) or 'aucune'}")
    run(args)


def main() -> int:
    if "--update" in sys.argv[1:]:
        from update import run_update

        return run_update(with_deps="--deps" in sys.argv)

    if "--repair" in sys.argv[1:]:
        from repair import run_repair

        rest = [arg for arg in sys.argv[1:] if arg != "--repair"]
        target = next((arg for arg in rest if not arg.startswith("--")), str(load_config().get("base_output", "")))
        return run_repair(resolve_path(target), dry_run="--dry-run" in rest)

    while True:
        cfg = load_config()
        print(BANNER)
        show_settings(cfg)
        print(
            "\n  1) Télécharger une série (URL + options)\n"
            "  2) Tester une URL (lister les épisodes)\n"
            "  3) Modifier le dossier de sortie\n"
            "  4) Qualité par défaut\n"
            "  5) Serveurs à essayer\n"
            "  6) Navigateur\n"
            "  7) Affichage (fenêtre / masquée / headless)\n"
            "  8) Réinitialiser les préférences\n"
            "  9) Mettre à jour depuis GitHub\n"
            " 10) Réparer les vidéos existantes (seek fluide)\n"
            "  0) Quitter"
        )
        choice = ask("\n  Votre choix")

        if choice in ("0", "q", "quit", "exit"):
            log("  À bientôt.")
            return 0

        if choice == "1":
            log("  Colle l'URL, puis les options si besoin : --from-ep 5 --quality 720 --limit 2")
            url = ask("  URL (+ options)")
            if not url:
                log("  URL vide, retour au menu.")
                continue
            try:
                run_download(url)
            except SystemExit as exc:
                log(f"  Arrêt (code {exc.code}).")
            except Exception as exc:
                log(f"  Erreur : {type(exc).__name__}: {exc}")

        elif choice == "2":
            url = ask("  URL à tester")
            if not url:
                continue
            try:
                run_download(url, dry_run=True)
            except SystemExit as exc:
                log(f"  Arrêt (code {exc.code}).")
            except Exception as exc:
                log(f"  Erreur : {type(exc).__name__}: {exc}")

        elif choice == "3":
            new_path = ask("  Nouveau dossier de sortie", str(cfg.get("base_output", "")))
            save_user_prefs({"base_output": new_path})
            log(f"  Dossier enregistré : {new_path}")

        elif choice == "4":
            current = str(cfg.get("quality", "ask"))
            options = [
                ("Demander au 1er épisode (ask)", "ask"),
                ("Meilleure disponible (best)", "best"),
                ("La plus basse (worst)", "worst"),
                ("480p", "480"),
                ("720p", "720"),
                ("1080p", "1080"),
                ("Autre hauteur…", "__custom__"),
            ]
            while True:
                picked = pick("Qualité par défaut", options, current)
                if picked is None:
                    log("  Inchangé.")
                    break
                if picked == "__custom__":
                    raw = ask("  Hauteur en p (ex: 900)", "")
                    if not re.fullmatch(r"\d{3,4}", raw.strip()):
                        log("  Hauteur invalide — 3 ou 4 chiffres, ex: 720.")
                        continue
                    picked = raw.strip()
                save_user_prefs({"quality": picked})
                log(f"  Qualité enregistrée : {picked}")
                break

        elif choice == "5":
            current = str(cfg.get("sources") or "")
            options = [
                ("Tous les serveurs détectés (auto)", ""),
                ("Premier seulement", "1"),
                ("Les deux premiers", "1,2"),
                ("Les trois premiers", "1,2,3"),
                ("Autre liste (ex: 1,3,4)", "__custom__"),
            ]
            while True:
                picked = pick("Serveurs à essayer", options, current)
                if picked is None:
                    log("  Inchangé.")
                    break
                if picked == "__custom__":
                    raw = ask("  Numéros séparés par des virgules", "")
                    if not re.fullmatch(r"\d+(\s*,\s*\d+)*", raw.strip()):
                        log("  Liste invalide — ex: 1,3,4")
                        continue
                    picked = re.sub(r"\s+", "", raw.strip())
                save_user_prefs({"sources": picked})
                log(f"  Serveurs enregistrés : {picked or 'auto'}")
                break

        elif choice == "6":
            current = str(cfg.get("browser", "auto"))
            options = [
                ("Automatique — navigateur installé (auto)", "auto"),
                ("Chromium embarqué Playwright", "chromium"),
                ("Google Chrome", "chrome"),
                ("Brave", "brave"),
                ("Microsoft Edge", "msedge"),
            ]
            picked = pick("Navigateur", options, current)
            if picked is None:
                log("  Inchangé.")
            else:
                save_user_prefs({"browser": picked})
                log(f"  Navigateur enregistré : {picked}")

        elif choice == "7":
            current = str(cfg.get("display", "window"))
            options = [
                ("Fenêtre visible (window)", "window"),
                ("Fenêtre hors écran (hidden, recommandé)", "hidden"),
                ("Invisible (headless, souvent bloqué)", "headless"),
            ]
            picked = pick("Affichage", options, current)
            if picked is None:
                log("  Inchangé.")
            else:
                save_user_prefs({"display": picked})
                log(f"  Affichage enregistré : {picked}")

        elif choice == "8":
            if USER_PREFS_PATH.exists():
                USER_PREFS_PATH.unlink()
            log("  Préférences supprimées (config.yaml restaurée).")

        elif choice in ("9", "u", "update"):
            try:
                from update import run_update

                log("")
                run_update(with_deps=True)
                log("  Relance AnimeDL pour charger la nouvelle version.")
            except Exception as exc:
                log(f"  Mise à jour impossible : {type(exc).__name__}: {exc}")

        elif choice in ("10", "r", "repair"):
            target = ask("  Dossier à réparer", str(cfg.get("base_output", "")))
            dry = ask("  Simulation seulement ? (o/N)", "N").strip().lower().startswith("o")
            try:
                from repair import run_repair

                log("")
                run_repair(resolve_path(target), dry_run=dry)
            except Exception as exc:
                log(f"  Réparation impossible : {type(exc).__name__}: {exc}")

        else:
            log("  Choix invalide.")
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Interrompu.")
        sys.exit(130)
