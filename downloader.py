"""Téléchargement du flux HLS via yt-dlp + vérification ffmpeg."""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yt_dlp

from common import end_status, ffmpeg_exe, log, status_line

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_RESOLUTION_RE = re.compile(r"Video:.*?(\d{2,5})x(\d{2,5})")


class DownloadError(RuntimeError):
    pass


def probe_duration(path: Path, ffmpeg: str) -> float | None:
    """Durée du fichier en secondes via `ffmpeg -i` (pas besoin de ffprobe)."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        errors="ignore",
    )
    m = _DURATION_RE.search(proc.stderr or "")
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def probe_resolution(path: Path, ffmpeg: str) -> tuple[int | None, int | None]:
    """Résolution réelle du fichier (largeur, hauteur)."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        errors="ignore",
    )
    m = _RESOLUTION_RE.search(proc.stderr or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def requested_height(quality: str | None) -> int | None:
    m = re.match(r"(\d{3,4})", str(quality or "").strip().lower())
    return int(m.group(1)) if m else None


def _bar(pct: float, width: int = 22) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100))
    return "█" * filled + "░" * (width - filled)


def _eta(seconds: Any) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    return f"  ETA {total // 60:02d}:{total % 60:02d}"


def _progress_printer(prefix: str):
    """Barre de progression stable : la taille totale HLS est figée au départ."""
    state = {"pct": -1, "total": 0.0}
    interactive = sys.stdout.isatty()

    def hook(d: dict[str, Any]) -> None:
        if d.get("status") == "downloading":
            done = float(d.get("downloaded_bytes") or 0)
            if not state["total"]:
                state["total"] = float(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)

            frag_i = d.get("fragment_index")
            frag_n = d.get("fragment_count")
            if frag_i and frag_n:
                pct = int(frag_i * 100 / frag_n)
            elif state["total"]:
                pct = int(done * 100 / state["total"])
            else:
                pct = 0

            step = 1 if interactive else 5
            if pct >= state["pct"] + step or (pct >= 100 > state["pct"]):
                state["pct"] = pct
                speed = (d.get("speed") or 0) / 1024 / 1024
                total = f"{state['total'] / 1048576:.1f}" if state["total"] else "?"
                status_line(
                    f"{prefix} {_bar(pct)} {pct:3d}%  "
                    f"{done / 1048576:5.1f}/{total} Mo  {speed:4.1f} Mo/s{_eta(d.get('eta'))}"
                )
        elif d.get("status") == "finished":
            end_status()
            log(f"   {prefix} 100% — assemblage/mux ffmpeg…")

    return hook


def format_selector(quality: str | None) -> str:
    """Traduit un choix utilisateur en sélecteur de format yt-dlp."""
    q = str(quality or "best").strip().lower()
    if q in ("", "best", "max"):
        return "best"
    if q in ("worst", "min", "sd"):
        return "worst"
    m = re.match(r"(\d{3,4})", q)
    if m:
        h = int(m.group(1))
        return f"best[height<={h}]/best"
    return "best"


def _download_once(
    url: str,
    referer: str,
    user_agent: str,
    out_template: Path,
    cfg: dict[str, Any],
    label: str,
    cookie: str,
    quality: str | None = None,
) -> tuple[Path, float | None]:
    ffmpeg = ffmpeg_exe()
    ytdlp_cfg = cfg.get("ytdlp", {}) or {}

    headers = {
        "Referer": referer,
        "User-Agent": user_agent or "Mozilla/5.0",
        "Accept": "*/*",
    }
    if cookie:
        headers["Cookie"] = cookie

    options: dict[str, Any] = {
        "format": format_selector(quality) if quality else (ytdlp_cfg.get("format") or "best"),
        "outtmpl": {"default": str(out_template)},
        "merge_output_format": "mp4",
        "http_headers": headers,
        "ffmpeg_location": os.path.dirname(ffmpeg),
        "concurrent_fragment_downloads": int(cfg.get("fragment_concurrency", 4)),
        "retries": 3,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "continuedl": True,
        "overwrites": True,
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_printer(label or "")],
    }
    cookies = ytdlp_cfg.get("cookies_from_browser")
    if cookies:
        options["cookiesfrombrowser"] = (cookies,)

    shown = out_template.name.replace(".%(ext)s", "")
    log(f"[dl] {shown} ← {url[:100]}")
    started = time.time()
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise DownloadError("yt-dlp n'a renvoyé aucune information")
        base = Path(ydl.prepare_filename(info))

    candidates = [
        *sorted(glob.glob(str(base.with_suffix(".*")))),
        *sorted(glob.glob(str(base.with_suffix(".mp4")))),
    ]
    existing = [Path(p) for p in candidates if os.path.exists(p) and not p.endswith(".part")]
    if not existing:
        raise DownloadError("fichier de sortie introuvable après téléchargement")

    final = max(existing, key=lambda p: p.stat().st_size)
    if final.suffix.lower() != ".mp4":
        raise DownloadError(f"format inattendu : {final.name}")

    elapsed = time.time() - started
    duration = probe_duration(final, ffmpeg)
    width, height = probe_resolution(final, ffmpeg)
    res = f", {width}x{height}" if width and height else ""
    log(f"[dl] OK {final.name} — {final.stat().st_size / 1048576:.1f} Mo en {elapsed:.0f}s"
        + (f", durée {duration:.0f}s" if duration else "") + res)

    wanted = requested_height(quality)
    if wanted and height and height > wanted * 1.15:
        log(f"[dl] ⚠ qualité réelle {height}p pour {wanted}p demandés : "
            "le flux n'expose peut-être pas cette variante")
    return final, duration


def download(
    url: str,
    referer: str,
    user_agent: str,
    out_template: Path,
    cfg: dict[str, Any],
    label: str = "",
    cookie: str = "",
    fallback_url: str | None = None,
    quality: str | None = None,
) -> tuple[Path, float | None]:
    """Télécharge le manifest ; en cas d'échec, retente la sous-playlist directe."""
    try:
        return _download_once(url, referer, user_agent, out_template, cfg, label, cookie, quality)
    except Exception as exc:
        if not fallback_url or fallback_url == url:
            raise
        log(f"[dl] échec ({exc}) — nouvelle tentative sur la sous-playlist…")
        cleanup_failed(out_template)
        return _download_once(fallback_url, referer, user_agent, out_template, cfg, label, cookie, quality)


def verify(path: Path, duration: float | None, cfg: dict[str, Any], expected: float | None = None) -> None:
    """Lève DownloadError si le fichier est vide / trop court / tronqué."""
    if not path.exists():
        raise DownloadError("fichier absent")
    min_bytes = int(float(cfg.get("min_size_mb", 1)) * 1024 * 1024)
    if path.stat().st_size < min_bytes:
        raise DownloadError(f"fichier trop petit ({path.stat().st_size} o)")
    minimum = float(cfg.get("min_duration_s", 30))
    if duration is not None and duration < minimum:
        raise DownloadError(f"durée anormale ({duration:.0f}s < {minimum:.0f}s)")
    if duration is not None and expected and expected > 30 and duration < expected * 0.85:
        raise DownloadError(f"fichier tronqué ({duration:.0f}s pour {expected:.0f}s attendus)")
    leftovers = list(path.parent.glob(path.name + "*.part"))
    if leftovers:
        raise DownloadError(f"segments restants : {leftovers[0].name}")


def cleanup_failed(out_template: Path) -> None:
    """Supprime les fichiers partiels d'un épisode en échec."""
    stem = str(out_template.with_suffix(""))
    for pattern in (stem + "*", str(out_template.with_suffix(".*"))):
        for path in glob.glob(pattern):
            try:
                if path.endswith((".part", ".ytdl", ".temp")):
                    os.remove(path)
            except OSError:
                pass
