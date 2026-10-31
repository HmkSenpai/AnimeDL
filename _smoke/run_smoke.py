"""Test de fumée : capture HLS + téléchargement yt-dlp sur un serveur local."""
from __future__ import annotations

import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from capture import ManifestCapture
from common import ffmpeg_exe, load_config, log
from downloader import download, verify

HERE = Path(__file__).resolve().parent
PORT = 8765


def ensure_hls() -> None:
    """Génère un petit flux HLS de test si absent (ffmpeg requis)."""
    hls_dir = HERE / "hls"
    playlist = hls_dir / "index.m3u8"
    if playlist.exists():
        return
    hls_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-t", "6",
            "-pix_fmt", "yuv420p", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
            "-hls_segment_filename", str(hls_dir / "seg%03d.ts"),
            str(playlist),
        ],
        check=True,
    )


def serve() -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(HERE))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    ensure_hls()
    httpd = serve()
    cfg = load_config()
    cfg.update(
        {
            "headless": True,
            "capture_timeout_s": 20,
            "source_buttons": [],
            "play_selectors": [".play-button", "video"],
            "dismiss_selectors": [],
            "min_duration_s": 2,
            "min_size_mb": 0,
            "min_manifest_duration_s": 2,
            "min_free_gb": 0,
            "user_data_dir": str(HERE / ".profile"),
            "fragment_concurrency": 2,
        }
    )
    profile = Path(cfg["user_data_dir"])
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(profile), headless=True)
        cap = ManifestCapture(ctx, cfg)
        result = cap.capture(f"http://127.0.0.1:{PORT}/page.html", 0)
        if not result:
            log("SMOKE FAIL: aucun manifest capté")
            ctx.close()
            httpd.shutdown()
            return 1
        log(f"manifest: {result.url}")
        out = HERE / "out" / "test - S01E01.%(ext)s"
        final, duration = download(result.url, result.referer, result.user_agent, out, cfg, "TEST")
        verify(final, duration, cfg)
        log(f"SMOKE OK: {final.name} ({final.stat().st_size} o, {duration}s)")
        cap.close()
        ctx.close()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
