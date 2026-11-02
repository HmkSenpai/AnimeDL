"""AnimeDL — télécharge tous les épisodes d'une série depuis un player HLS.

Usage :
    python main.py "https://MonSite/anime/the-apothecary-diaries-3/"
    python main.py "https://MonSite/anime/xxx/xxx-05-vostfr/" --limit 3
    python main.py "<url>" --dry-run        # liste les épisodes seulement
    python main.py "<url>" --retry-failed   # rejoue les épisodes en échec
    python main.py                          # menu interactif (si lancé sans URL)
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from playwright.sync_api import sync_playwright

from adblock import AdBlocker
from capture import ManifestCapture
from common import (
    die,
    ensure_space,
    ffmpeg_exe,
    browser_launch_options,
    load_config,
    log,
    resolve_browser,
    resolve_path,
    safe_filename,
)
from downloader import DownloadError, cleanup_failed, download, verify
from progress import Progress
from scraper import collect_episodes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Téléchargement automatique d'épisodes HLS")
    p.add_argument("url", nargs="?", default="", help="URL de la série ou d'un épisode")
    p.add_argument("--output", help="Dossier de sortie (remplace base_output)")
    p.add_argument("--limit", type=int, default=0, help="Ne traiter que N épisodes")
    p.add_argument("--from-ep", type=int, default=0, help="Commencer à cet épisode")
    p.add_argument("--retry-failed", action="store_true", help="Rejouer les épisodes en échec")
    p.add_argument("--redo", type=int, action="append", default=[], metavar="N",
                   help="Refaire un épisode déjà terminé (répétable), ex: --redo 2")
    p.add_argument("--dry-run", action="store_true", help="Lister les épisodes sans télécharger")
    p.add_argument("--sources", default="", help="Serveurs à essayer, ex: \"1,2,4\" (défaut: tous)")
    p.add_argument("--headless", action="store_true", help="Navigateur invisible (souvent bloqué)")
    p.add_argument("--hidden", action="store_true", help="Fenêtre hors écran (recommandé si visible gêne)")
    p.add_argument("--min-duration", type=float, help="Durée minimale acceptée (s)")
    p.add_argument("--min-size-mb", type=float, help="Taille minimale acceptée (Mo)")
    p.add_argument("--fresh-profile", action="store_true", help="Ignorer le profil navigateur existant")
    p.add_argument("--browser", default="",
                   choices=["", "auto", "chromium", "chrome", "brave", "msedge"],
                   help="Navigateur à piloter (auto = navigateur déjà installé)")
    p.add_argument("--quality", default="",
                   help="Qualité: best, worst, ou une hauteur en p (720). Choisie une fois pour tous les épisodes.")
    return p


def choose_quality(cap, args, cfg: dict, progress: Progress) -> str:
    """Détermine la qualité à utiliser et la mémorise pour les épisodes suivants."""
    if args.quality:
        return args.quality
    saved = progress.get_quality()
    if saved:
        log(f"[qualité] conservée depuis la dernière exécution : {saved}")
        return saved
    cfg_q = str(cfg.get("quality") or "ask").strip().lower()
    if cfg_q not in ("ask", ""):
        progress.set_quality(cfg_q)
        return cfg_q

    variants = getattr(cap, "variants", []) or []
    if not variants:
        return "best"
    if len(variants) == 1:
        only = variants[0]
        choice = str(only.height) if only.height else "best"
        log(f"[qualité] une seule piste : {only.label}")
        progress.set_quality(choice)
        return choice

    log("\nQualités disponibles pour cet épisode :")
    for i, v in enumerate(variants, 1):
        log(f"  {i}) {v.label:>6}   {v.bitrate:>9}   {v.width or '?'}x{v.height or '?'}")

    if not (sys.stdin and sys.stdin.isatty()):
        log("  (mode non interactif : qualité par défaut = meilleure)")
        return "best"

    try:
        answer = input(f"Choix [1-{len(variants)}, Entrée = 1] : ").strip() or "1"
        index = int(answer) - 1
    except (EOFError, KeyboardInterrupt, ValueError):
        return "best"
    if 0 <= index < len(variants):
        chosen = variants[index]
        if chosen.height:
            log(f"  → {chosen.label} sélectionné pour tous les épisodes")
            progress.set_quality(str(chosen.height))
            return str(chosen.height)
        log("  (piste sans résolution connue : meilleure qualité utilisée)")
    return "best"


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    display = str(cfg.get("display") or "window").lower()
    if args.headless or display == "headless":
        cfg["headless"] = True
    hidden = args.hidden or display == "hidden"
    if args.output:
        cfg["base_output"] = args.output
    if args.min_duration is not None:
        cfg["min_duration_s"] = args.min_duration
    if args.min_size_mb is not None:
        cfg["min_size_mb"] = args.min_size_mb
    ffmpeg_exe()  # échoue tôt si absent

    pattern = re.compile(cfg["episode_pattern"])
    user_data = resolve_path(cfg["user_data_dir"])
    if args.fresh_profile and user_data.exists():
        import shutil

        shutil.rmtree(user_data, ignore_errors=True)

    sources_order = [int(x) - 1 for x in re.findall(r"\d+", args.sources)] or None

    requested = args.browser or str(cfg.get("browser") or "auto")
    browser = resolve_browser(requested)
    if browser == "chromium":
        log("[navigateur] chromium embarqué (Playwright)")
    else:
        log(f"[navigateur] {browser} déjà installé — aucun téléchargement")

    with sync_playwright() as pw:
        launch_kwargs: dict = {
            "headless": bool(cfg["headless"]),
            "viewport": {"width": 1280, "height": 800},
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"],
        }
        if hidden:
            # fenêtre réelle (moins détectable) mais placée hors écran
            launch_kwargs["args"] += ["--window-position=-32000,-32000", "--start-minimized"]

        try:
            channel_kwargs = dict(launch_kwargs)
            channel_kwargs.update(browser_launch_options(browser))
            ctx = pw.chromium.launch_persistent_context(str(user_data), **channel_kwargs)
        except Exception as exc:
            if browser == "chromium":
                raise
            log(f"[navigateur] échec avec {browser} ({type(exc).__name__}) — repli sur chromium")
            browser = "chromium"
            ctx = pw.chromium.launch_persistent_context(str(user_data), **launch_kwargs)
        ctx.set_default_timeout(30_000)

        capturer = ManifestCapture(ctx, cfg)
        page = capturer.ensure_page()
        blocker = AdBlocker(ctx, cfg)
        blocker.install(lambda p: p is page)

        title, episodes = collect_episodes(page, args.url, pattern, cfg["prefer_vf"])
        if not episodes:
            ctx.close()
            die("aucun épisode détecté — vérifie l'URL ou le motif `episode_pattern` du config.yaml")

        if args.from_ep:
            episodes = [e for e in episodes if e.number >= args.from_ep]
        if args.limit:
            episodes = episodes[: args.limit]

        log("\nÉpisodes détectés :")
        for ep in episodes:
            log(f"  E{ep.code}  [{ep.lang}]  {ep.url}")
        if args.dry_run:
            ctx.close()
            return 0

        out_dir = resolve_path(cfg["base_output"]) / safe_filename(title or "serie")
        ensure_space(float(cfg["min_free_gb"]), out_dir)
        progress = Progress(title, out_dir / ".progress.json")
        if args.retry_failed:
            progress.clear_failed()
        for number in args.redo or []:
            code = f"{int(number):02d}"
            old = progress.forget(code)
            if old and old.exists():
                old.unlink()
                log(f"[redo] E{code} : ancien fichier supprimé ({old.name})")
            else:
                log(f"[redo] E{code} : remis dans la file")

        results: list[tuple[str, str]] = []
        failures = 0
        quality: str | None = None
        # empreinte du flux -> épisode : détecte un player resté sur l'épisode précédent
        streams: dict[str, str] = {}
        identity_check = bool(cfg.get("stream_identity_check", True))

        for ep in episodes:
            if progress.is_done(ep.code):
                log(f"\n=== E{ep.code} — déjà téléchargé, skiper ===")
                continue

            log(f"\n=== E{ep.code} [{ep.lang}] {ep.url} ===")
            ensure_space(float(cfg["min_free_gb"]), out_dir)
            out_template = out_dir / f"{safe_filename(title)} - S01E{ep.code}.%(ext)s"
            ok = False
            last_error = "inconnu"

            order = list(sources_order) if sources_order else [0]
            pos = 0
            while pos < len(order):
                source_index = order[pos]
                log(f"\n--- Source #{source_index + 1} ---")
                cap = capturer.capture(ep.url, source_index, tag=f"E{ep.code}")

                # découverte dynamique : autant de serveurs que le site en propose
                if not sources_order:
                    detected = capturer.source_count()
                    if detected <= 0:
                        detected = int(cfg.get("max_sources", 2))
                    for extra in range(1, max(detected, 1)):
                        if extra not in order:
                            order.append(extra)

                duplicate = None
                if cap and cap.fingerprint and identity_check:
                    other = streams.get(cap.fingerprint)
                    if other and other != ep.code:
                        duplicate = other

                if cap and duplicate:
                    log(f"[!] E{ep.code} : flux identique à E{duplicate} — le player n'a pas changé d'épisode")
                    last_error = f"flux identique à E{duplicate}"
                elif cap:
                    if quality is None:
                        quality = choose_quality(cap, args, cfg, progress)
                    try:
                        final, duration = download(
                            cap.url,
                            cap.referer,
                            cap.user_agent,
                            out_template,
                            cfg,
                            label=f"E{ep.code}",
                            cookie=cap.cookie,
                            fallback_url=cap.variant_url,
                            quality=quality,
                        )
                        verify(final, duration, cfg, expected=cap.duration)
                        progress.mark_done(ep.code, final, source_index)
                        results.append((ep.code, str(final)))
                        if cap.fingerprint:
                            streams[cap.fingerprint] = ep.code
                        ok = True
                        break
                    except DownloadError as exc:
                        last_error = str(exc)
                        log(f"[dl] échec source #{source_index + 1} : {exc}")
                        cleanup_failed(out_template)
                    except Exception as exc:  # erreur yt-dlp / réseau
                        last_error = f"{type(exc).__name__}: {exc}"
                        log(f"[dl] erreur source #{source_index + 1} : {last_error}")
                        cleanup_failed(out_template)
                else:
                    last_error = f"aucun manifest (source {source_index + 1})"
                pos += 1

            if not ok:
                failures += 1
                progress.mark_failed(ep.code, last_error)
                log(f"[!] E{ep.code} abandonné ({last_error})")
                if last_error.startswith("flux identique"):
                    log("    Le player rejoue une autre vidéo : vérifie la page avec probe.py, "
                        "ou désactive stream_identity_check si c'est un faux positif.")

            time.sleep(float(cfg["delay_between_episodes_s"]))

        capturer.close()
        ctx.close()

    log("\n================ RÉSUMÉ ================")
    log(f"  Anti-pub : {blocker.summary()}")
    log(f"  Qualité : {quality or 'best'}")
    for code, path in results:
        log(f"  E{code} -> {path}")
    log(f"  État global : {progress.summary()}")
    if failures:
        log("  Relance avec --retry-failed pour rejouer les épisodes en échec.")
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.url:
        parser.print_help()
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
