"""Test : un épisode = un flux différent (pas de reprise de l'épisode précédent)."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from capture import ManifestCapture  # noqa: E402
from common import ffmpeg_exe, log  # noqa: E402
from scraper import clean_href  # noqa: E402

HERE = Path(__file__).resolve().parent
MEDIA = HERE / ".media"
PORT = 8771
PATTERN = r"-(\d+)-vostfr/?$"


def build_media(index: int) -> None:
    target = MEDIA / f"media{index}"
    if (target / "master.m3u8").exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15", "-t", "6",
            "-pix_fmt", "yuv420p", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
            "-hls_segment_filename", str(target / f"seg{index}_%03d.ts"),
            str(target / "master.m3u8"),
        ],
        check=True,
    )


def page_html(media: int) -> str:
    return (
        "<!doctype html><html><body>"
        '<button class="play-button">▶ Lecture</button>'
        "<script>"
        "document.querySelector('.play-button').onclick = () => "
        f"fetch('/media{media}/master.m3u8').catch(() => {{}});"
        "</script></body></html>"
    )


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(MEDIA), **kwargs)

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        match = re.search(PATTERN, path)
        if match:
            number = int(match.group(1))
            if number == 3:  # redirection vers l'épisode 1
                self.send_response(302)
                self.send_header("Location", "/serie/serie-01-vostfr/")
                self.end_headers()
                return
            media = 1 if number == 4 else number  # épisode 4 = flux de l'épisode 1
            body = page_html(media).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main() -> int:
    MEDIA.mkdir(exist_ok=True)
    build_media(1)
    build_media(2)

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    cfg = {
        "headless": True,
        "capture_timeout_s": 6,
        "source_buttons": [],
        "source_selectors": [],
        "play_selectors": [".play-button"],
        "dismiss_selectors": [],
        "min_manifest_duration_s": 2,
        "allow_unknown_duration": False,
        "ad_hosts": [],
        "episode_pattern": PATTERN,
        "quality": "best",
        "user_data_dir": str(HERE / ".profile"),
    }

    base = f"http://127.0.0.1:{PORT}/serie"
    ep = lambda n: f"{base}/serie-{n:02d}-vostfr/"  # noqa: E731

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(HERE / ".profile"), headless=True)
        cap = ManifestCapture(ctx, cfg)

        first = cap.capture(ep(1), 0, tag="E01")
        second = cap.capture(ep(2), 0, tag="E02")
        duplicate = cap.capture(ep(4), 0, tag="E04")
        redirected = cap.capture(ep(3), 0, tag="E03")

        checks = [
            (first is not None and second is not None,
             "E01 et E02 capturés"),
            (bool(first and second and first.fingerprint != second.fingerprint),
             "E02 a un flux différent de E01"),
            (bool(duplicate and first and duplicate.fingerprint == first.fingerprint),
             "flux rejoué détecté (E04 = E01)"),
            (redirected is None, "redirection E03 -> E01 refusée"),
            (first is not None and "media1" in first.url, "E01 pointe sur media1"),
            (second is not None and "media2" in second.url, "E02 pointe sur media2"),
        ]

        if first:
            log(f"  empreinte E01 : {first.fingerprint}")
        if second:
            log(f"  empreinte E02 : {second.fingerprint}")

        cap.close()
        ctx.close()
    httpd.shutdown()
    shutil.rmtree(HERE / ".profile", ignore_errors=True)

    checks += [
        (clean_href("https://x.test/anime/a/?ep=2&utm_source=fb") == "https://x.test/anime/a/?ep=2",
         "clean_href garde ?ep=2 et retire utm"),
        (clean_href("https://x.test/a/#frag") == "https://x.test/a/",
         "clean_href retire le fragment"),
        (ManifestCapture._canonical("http://x/a?ep=1") != ManifestCapture._canonical("http://x/a?ep=2"),
         "_canonical distingue les épisodes par query"),
    ]

    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
