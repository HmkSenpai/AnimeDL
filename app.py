"""AnimeDL — menu interactif (lancer : python app.py ou AnimeDL.bat)."""
from __future__ import annotations

import sys

from common import USER_PREFS_PATH, load_config, log, resolve_browser, save_user_prefs
from main import build_parser, run

BANNER = r"""
 █████╗ ███╗   ██╗██╗███╗   ███╗███████╗    ██████╗ ██╗
██╔══██╗████╗  ██║██║████╗ ████║██╔════╝    ██╔══██╗██║
███████║██╔██╗ ██║██║██╔████╔██║█████╗      ██║  ██║██║
██╔══██║██║╚██╗██║██║██║╚██╔╝██║██╔══╝      ██║  ██║██║
██║  ██║██║ ╚████║██║██║ ╚═╝ ██║███████╗    ██████╔╝███████╗
╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚═╝     ╚═╝╚══════╝    ╚═════╝ ╚══════╝
      téléchargement automatique d'épisodes  ·  v1.0
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


def run_download(url: str, dry_run: bool = False) -> None:
    cfg = load_config()
    parser = build_parser()
    argv = [url]
    if dry_run:
        argv.append("--dry-run")
    sources = str(cfg.get("sources") or "").strip()
    if sources:
        argv += ["--sources", sources]
    display = str(cfg.get("display") or "window").lower()
    if display == "hidden":
        argv.append("--hidden")
    elif display == "headless":
        argv.append("--headless")
    args = parser.parse_args(argv)
    run(args)


def main() -> int:
    while True:
        cfg = load_config()
        print(BANNER)
        show_settings(cfg)
        print(
            "\n  1) Télécharger une série (URL)\n"
            "  2) Tester une URL (lister les épisodes)\n"
            "  3) Modifier le dossier de sortie\n"
            "  4) Qualité par défaut\n"
            "  5) Serveurs à essayer\n"
            "  6) Navigateur\n"
            "  7) Affichage (fenêtre / masquée / headless)\n"
            "  8) Réinitialiser les préférences\n"
            "  0) Quitter"
        )
        choice = ask("\n  Votre choix")

        if choice in ("0", "q", "quit", "exit"):
            log("  À bientôt.")
            return 0

        if choice == "1":
            url = ask("  URL de la série ou d'un épisode")
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

        else:
            log("  Choix invalide.")
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Interrompu.")
        sys.exit(130)
