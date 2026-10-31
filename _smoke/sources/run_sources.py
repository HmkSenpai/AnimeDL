"""Test : détection de N serveurs (select natif) + bascule jusqu'au bon."""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from capture import ManifestCapture
from common import ffmpeg_exe, log

HERE = Path(__file__).resolve().parent
PORT = 8769


def build_manifest() -> None:
    target = HERE / "src3"
    if (target / "index.m3u8").exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-t", "6",
            "-pix_fmt", "yuv420p", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
            "-hls_segment_filename", str(target / "seg%03d.ts"), str(target / "index.m3u8"),
        ],
        check=True,
    )


def main() -> int:
    build_manifest()
    handler = partial(SimpleHTTPRequestHandler, directory=str(HERE))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    cfg = {
        "headless": True,
        "capture_timeout_s": 5,
        "source_buttons": [],
        "source_selectors": [],
        "play_selectors": [".play-button"],
        "dismiss_selectors": [],
        "min_manifest_duration_s": 2,
        "allow_unknown_duration": False,
        "ad_hosts": [],
        "min_duration_s": 2,
        "min_size_mb": 0,
        "fragment_concurrency": 2,
        "quality": "best",
        "user_data_dir": str(HERE / ".profile"),
    }

    url = f"http://127.0.0.1:{PORT}/page.html"
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(HERE / ".profile"), headless=True)
        cap = ManifestCapture(ctx, cfg)

        first = cap.capture(url, 0, tag="sources")
        count = cap.source_count()
        log(f"serveurs détectés : {count} -> {cap.sources}")

        good = None
        if not first:
            for i in range(1, count):
                res = cap.capture(url, i, tag="sources")
                if res:
                    good = res
                    log(f"source #{i + 1} OK : {res.url}")
                    break

        checks = [
            (count == 4, "4 serveurs détectés"),
            (first is None, "source 1 invalide ignorée"),
            (good is not None and "/src3/" in (good.url if good else ""), "source 4 (Stape) retenue"),
        ]
        for ok, label in checks:
            log(("  ✅ " if ok else "  ❌ ") + label)

        cap.close()
        ctx.close()
    httpd.shutdown()
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
