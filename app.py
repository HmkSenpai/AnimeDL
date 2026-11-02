"""AnimeDL — menu interactif (lancer : python app.py ou AnimeDL.bat)."""
from __future__ import annotations

import shlex
import sys

from common import USER_PREFS_PATH, load_config, log, resolve_browser, save_user_prefs
from main import build_parser, run

BANNER = r"""
 ▄▀▀▀▀▀▀▀▀▀█ █▀▀▀▀▀▀▀▀▀▄  █▀▀▀▀█ █▀▀▀▀▀▀▀▀▀▄▀▀▀▀▀▄   ▄▀▀▀▀▀▀▀▀▀█      █▀▀▀▀▀▀▀▀▀▄  █▀▀▀▀█      
█   .▄▄   ∙▀ ▀    ▄▄    █ ▀    ▓ ▀    ▄▄     ▄    █ █·   ▄▄▄▄▄▄█      ▀    ▄▄ .  █ █·   █      
▓    ▐▄▌.  ▓ ▓    ▓ ▌   ▓ ▓    ▓ ▓    ▓ ▌   ▓ ▌   ▓ ▓  . ▓▄▄▄▄▄▄      ▓    ▓ ▌   ▓ ▓  . ▓      
▒∙ . ▄▄▄   ▒ ▒    ▒ ▒ · ▒ ▒   ·▒ ▒    ▒ ▒ · ▒ ▒ · ▒ ▒ ∙  ▄▄▄▄▄▄▒      ▒  · ▒▄▓   ▒ ▒ ∙  ▒      
░    ░ ░  ·░ ░   ∙░ ░   ░ ░ .  ░ ░   ∙░ ░   ░ ░   ░ ░    ░▄▄▄▄▄▄      ░       ·. ░ ░    ░▄▄▄▄▄▄
█ .  █ █   █ █ ∙  █ █   █ █    █ █ ∙  █ █   █ █   █ █    .    ·█      █   .      █ █    .    ·█
█▄▄▄▄█ █▄▄▄█ █▄▄▄▄█ █▄▄▄█ █▄▄▄▄█ █▄▄▄▄█ █▄▄▄█ █▄▄▄█ █▄▄▄▄▄▄▄▄▄▄█      █▄▄▄▄▄▄▄▄▄▄█ █▄▄▄▄▄▄▄▄▄▄█  
                  téléchargement automatique d'épisodes  ·  v1.2 by Hinmaka
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
            log("  Valeurs : ask (demander), best, worst, ou une hauteur (480, 720, 1080)")
            quality = ask("  Qualité", str(cfg.get("quality", "ask")))
            save_user_prefs({"quality": quality})
            log(f"  Qualité enregistrée : {quality}")

        elif choice == "5":
            log("  'auto' = tous les serveurs détectés ; sinon ex: 1,2,4")
            sources = ask("  Serveurs", str(cfg.get("sources") or "auto"))
            save_user_prefs({"sources": "" if sources.lower() == "auto" else sources})
            log(f"  Serveurs enregistrés : {sources}")

        elif choice == "6":
            log("  auto = navigateur déjà installé (recommandé) ; sinon chromium, chrome, brave, msedge")
            browser = ask("  Navigateur", str(cfg.get("browser", "auto")))
            save_user_prefs({"browser": browser})
            log(f"  Navigateur enregistré : {browser}")

        elif choice == "7":
            log("  window = fenêtre visible, hidden = hors écran (recommandé), headless = invisible")
            display = ask("  Affichage", str(cfg.get("display", "window")))
            save_user_prefs({"display": display})
            log(f"  Affichage enregistré : {display}")

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

        else:
            log("  Choix invalide.")
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Interrompu.")
        sys.exit(130)
