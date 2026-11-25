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
import shutil
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from adblock import AdBlocker
from capture import ManifestCapture
from content import same_content, stream_hash, visual_hash
from common import (
    debug,
    die,
    ensure_space,
    ffmpeg_exe,
    browser_launch_options,
    load_config,
    log,
    resolve_browser,
    resolve_path,
    safe_filename,
    set_verbose,
)
from downloader import DownloadError, cleanup_failed, download, verify
from library import session_finish, session_start
from progress import Progress
from scraper import clean_title, collect_episodes


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
    p.add_argument("--verbose", action="store_true",
                   help="Afficher les détails techniques (clics, serveurs, candidats HLS)")
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


def dns_rules(hosts: list[str], cfg: dict | None = None) -> str | None:
    """Règles Chromium MAP host->IP quand son résolveur DNS échoue.

    Sur certaines machines, Chromium (même Brave piloté par Playwright) renvoie
    `ERR_NAME_NOT_RESOLVED` alors que le DNS système fonctionne (curl, Python).
    On résout les hôtes connus côté Python et on les passe à Chromium : le nom
    d'hôte et le SNI TLS restent les bons, seule l'adresse IP est forcée.
    """
    cfg = cfg or {}
    if cfg.get("dns_map") is False:
        return None
    extra = cfg.get("dns_hosts") or []
    if isinstance(extra, str):
        extra = [h.strip() for h in extra.split(",") if h.strip()]
    names: list[str] = []
    for host in [*hosts, *extra]:
        host = str(host or "").strip().lower().rstrip(".")
        if host and host not in names and host not in ("localhost", "127.0.0.1", "::1"):
            names.append(host)
    rules: list[str] = []
    for host in names:
        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET)
        except (socket.gaierror, OSError):
            continue
        ips: list[str] = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        if ips:
            rules.append(f"MAP {host} {ips[0]}")
    return ", ".join(rules) if rules else None


def launch_context(
    pw,
    cfg: dict,
    *,
    fresh_profile: bool = False,
    hidden: bool = False,
    hosts: list[str] | None = None,
):
    """Ouvre le profil navigateur persistant (avec repli Chromium)."""
    user_data = resolve_path(cfg["user_data_dir"])
    if fresh_profile and user_data.exists():
        shutil.rmtree(user_data, ignore_errors=True)

    launch_kwargs: dict = {
        "headless": bool(cfg.get("headless")),
        "viewport": {"width": 1280, "height": 800},
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }
    if hidden:
        # fenêtre réelle (moins détectable) mais placée hors écran
        launch_kwargs["args"] += ["--window-position=-32000,-32000", "--start-minimized"]

    mapping = dns_rules(hosts or [], cfg)
    if mapping:
        launch_kwargs["args"].append(f"--host-resolver-rules={mapping}")
        debug(f"[dns] {mapping}")

    browser = resolve_browser(str(cfg.get("browser") or "auto"))
    if browser == "chromium":
        debug("[navigateur] chromium embarqué (Playwright)")
    else:
        debug(f"[navigateur] {browser} déjà installé — aucun téléchargement")

    try:
        channel_kwargs = dict(launch_kwargs)
        channel_kwargs.update(browser_launch_options(browser))
        ctx = pw.chromium.launch_persistent_context(str(user_data), **channel_kwargs)
    except Exception as exc:
        if browser == "chromium":
            raise
        log(f"[navigateur] échec avec {browser} ({type(exc).__name__}) — repli sur chromium")
        ctx = pw.chromium.launch_persistent_context(str(user_data), **launch_kwargs)
    ctx.set_default_timeout(30_000)
    return ctx


def peek_series(url: str, cfg: dict | None = None) -> tuple[str, list]:
    """Lit seulement la page série : titre nettoyé + épisodes (pour le suivi hebdo)."""
    local_cfg = dict(cfg or load_config())
    display = str(local_cfg.get("display") or "window").lower()
    if display == "headless":
        local_cfg["headless"] = True
    pattern = re.compile(local_cfg["episode_pattern"])

    with sync_playwright() as pw:
        ctx = launch_context(
            pw, local_cfg, hidden=(display == "hidden"),
            hosts=[urlparse(url).hostname],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            raw_title, episodes = collect_episodes(
                page, url, pattern, bool(local_cfg.get("prefer_vf"))
            )
        finally:
            ctx.close()
    return clean_title(raw_title, local_cfg), episodes


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    set_verbose(bool(getattr(args, "verbose", False)) or bool(cfg.get("verbose")))
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
    ffmpeg = ffmpeg_exe()  # échoue tôt si absent

    pattern = re.compile(cfg["episode_pattern"])
    sources_order = [int(x) - 1 for x in re.findall(r"\d+", args.sources)] or None
    if args.browser:
        cfg["browser"] = args.browser

    with sync_playwright() as pw:
        ctx = launch_context(
            pw, cfg, fresh_profile=args.fresh_profile, hidden=hidden,
            hosts=[urlparse(args.url).hostname],
        )

        capturer = ManifestCapture(ctx, cfg)
        page = capturer.ensure_page()
        blocker = AdBlocker(ctx, cfg)
        blocker.install(lambda p: p is page)

        raw_title, episodes = collect_episodes(page, args.url, pattern, cfg["prefer_vf"])
        title = clean_title(raw_title, cfg)
        if title != (raw_title or "").strip():
            debug(f"[titre] {raw_title!r} -> {title!r}")
        if not episodes:
            ctx.close()
            die("aucun épisode détecté — vérifie l'URL ou le motif `episode_pattern` du config.yaml")

        if args.from_ep:
            episodes = [e for e in episodes if e.number >= args.from_ep]
        if args.limit:
            episodes = episodes[: args.limit]

        debug("\nÉpisodes détectés :")
        for ep in episodes:
            debug(f"  E{ep.code}  [{ep.lang}]  {ep.url}")
        if args.dry_run:
            log(f"{len(episodes)} épisode(s) détecté(s) :")
            for ep in episodes:
                log(f"  E{ep.code} [{ep.lang}] {ep.url}")
            ctx.close()
            return 0

        out_dir = resolve_path(cfg["base_output"]) / safe_filename(title or "serie")
        ensure_space(float(cfg["min_free_gb"]), out_dir)
        progress = Progress(title, out_dir / ".progress.json")
        session_start(
            args.url,
            title,
            str(out_dir),
            str(progress.path),
            len(episodes),
            dict(vars(args)),
        )
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
        # empreinte du flux -> épisode : couvre aussi les épisodes déjà faits avant
        streams: dict[str, str] = progress.stream_map()
        identity_check = bool(cfg.get("stream_identity_check", True))

        # 2e garde-fou : comparer les pixels du fichier final. L'empreinte du
        # manifest peut rater un rejeu si le CDN change de token/de dossier.
        contents: dict[str, str] = progress.content_map()
        if identity_check:
            rebuilt = False
            for code, entry in list(progress.data["episodes"].items()):
                if entry.get("status") != "done" or entry.get("content_hash"):
                    continue
                stored = entry.get("file")
                if not stored or not Path(stored).exists():
                    continue
                visual = visual_hash(Path(stored), ffmpeg)
                if visual:
                    entry["content_hash"] = visual
                    contents[visual] = code
                    rebuilt = True
            if rebuilt:
                progress.save()

        for ep in episodes:
            if progress.is_done(ep.code):
                log(f"[E{ep.code}] déjà présent — ignoré")
                continue

            log(f"[E{ep.code}] téléchargement…")
            debug(f"  URL : {ep.url} [{ep.lang}]")
            ensure_space(float(cfg["min_free_gb"]), out_dir)
            out_template = out_dir / f"{safe_filename(title)} - S01E{ep.code}.%(ext)s"
            ok = False
            last_error = "inconnu"

            order = list(sources_order) if sources_order else [0]
            pos = 0
            reload_done = False
            while pos < len(order):
                source_index = order[pos]
                debug(f"\n--- Source #{source_index + 1} ---")
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
                    last_error = f"flux identique à E{duplicate}"
                    if not reload_done:
                        reload_done = True
                        log(f"[!] E{ep.code} : flux identique à E{duplicate} — rechargement complet de la page")
                        capturer.forget_page()
                        continue  # même source, nouvelle navigation
                    log(f"[!] E{ep.code} : flux identique à E{duplicate} — le player n'a pas changé d'épisode")
                elif cap:
                    if quality is None:
                        quality = choose_quality(cap, args, cfg, progress)

                    # Contrôle VISUEL avant de télécharger : ffmpeg ne lit que
                    # deux petits morceaux du flux HLS (quelques Mo, pas l'épisode).
                    if identity_check and contents:
                        headers = {
                            "User-Agent": cap.user_agent or "",
                            "Referer": cap.referer or "",
                        }
                        if cap.cookie:
                            headers["Cookie"] = cap.cookie
                        parsed_ref = urlparse(cap.referer or "")
                        if parsed_ref.scheme and parsed_ref.netloc:
                            headers["Origin"] = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
                        preview = stream_hash(
                            cap.variant_url or cap.url, ffmpeg, cap.duration, headers
                        )
                        conflict = next(
                            (
                                code for known, code in contents.items()
                                if known != ep.code and same_content(known, preview)
                            ),
                            None,
                        )
                        if conflict:
                            last_error = f"contenu identique à E{conflict} (avant téléchargement)"
                            log(f"[!] E{ep.code} : même vidéo que E{conflict} — téléchargement annulé")
                            progress.mark_failed(ep.code, last_error)
                            if not reload_done:
                                reload_done = True
                                capturer.forget_page()
                                continue  # même source, page rechargée
                            pos += 1
                            continue

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
                        visual = visual_hash(final, ffmpeg, duration) if identity_check else None
                        conflict = None
                        if visual:
                            conflict = next(
                                (
                                    known_code
                                    for known, known_code in contents.items()
                                    if known_code != ep.code and same_content(known, visual)
                                ),
                                None,
                            )
                        if conflict:
                            last_error = f"contenu identique à E{conflict}"
                            log(f"[!] E{ep.code} : contenu identique à E{conflict} — fichier supprimé")
                            final.unlink(missing_ok=True)
                            cleanup_failed(out_template)
                            progress.mark_failed(ep.code, last_error)
                            if not reload_done:
                                reload_done = True
                                capturer.forget_page()
                                continue  # même source, page rechargée
                        else:
                            progress.mark_done(ep.code, final, source_index, cap.fingerprint, visual or "")
                            results.append((ep.code, str(final)))
                            if cap.fingerprint:
                                streams[cap.fingerprint] = ep.code
                            if visual:
                                contents[visual] = ep.code
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
    debug(f"  Anti-pub : {blocker.summary()}")
    log(f"  Qualité : {quality or 'best'}")
    log(f"  État global : {progress.summary()}")
    for code, path in results:
        debug(f"  E{code} -> {path}")
    if failures:
        log("  Relance avec --retry-failed pour rejouer les épisodes en échec.")
    done_total = sum(1 for ep in episodes if progress.is_done(ep.code))
    failed_codes = [
        code for code, entry in progress.data["episodes"].items()
        if entry.get("status") == "failed"
    ]
    session_finish(
        args.url,
        "termine" if failures == 0 else "echoue",
        done_total,
        failed_codes,
        len(episodes),
    )
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
