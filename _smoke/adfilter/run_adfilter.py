"""Régression : le script doit ignorer la pub (manifest court) et garder l'épisode."""
from __future__ import annotations

import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from playwright.sync_api import sync_playwright

from capture import ManifestCapture
from common import ffmpeg_exe, log

HERE = Path(__file__).resolve().parent
PORT = 8767


def make_hls(name: str, seconds: int) -> None:
    folder = HERE / name
    if (folder / "index.m3u8").exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15", "-t", str(seconds),
            "-pix_fmt", "yuv420p", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
            "-hls_segment_filename", str(folder / "seg%03d.ts"), str(folder / "index.m3u8"),
        ],
        check=True,
    )


def main() -> int:
    make_hls("ad", 4)
    make_hls("ep", 12)
    handler = partial(SimpleHTTPRequestHandler, directory=str(HERE))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    cfg = {
        "headless": True,
        "capture_timeout_s": 25,
        "source_buttons": [],
        "source_selectors": [],
        "play_selectors": [".play-button"],
        "dismiss_selectors": [],
        "min_manifest_duration_s": 8,
        "allow_unknown_duration": False,
        "ad_hosts": [],
        "min_duration_s": 2,
        "min_size_mb": 0,
        "user_data_dir": str(HERE / ".profile"),
        "fragment_concurrency": 2,
    }

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(HERE / ".profile"), headless=True)
        cap = ManifestCapture(ctx, cfg)
        result = cap.capture(f"http://127.0.0.1:{PORT}/page.html", 0, tag="adfilter")
        ok = result is not None and "/ep/" in result.url
        if result:
            log(f"manifest retenu : {result.url} (durée={result.duration})")
        log("ADFILTER OK ✅ (pub ignorée)" if ok else "ADFILTER FAIL ❌")
        cap.close()
        ctx.close()
    httpd.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
