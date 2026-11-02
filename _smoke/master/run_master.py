"""Test : le master (multi-qualités) est préféré à la sous-playlist du player."""
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

HERE = Path(__file__).resolve().parent
MEDIA = HERE / ".media"
PORT = 8772


def make_hls(folder: Path, size: str) -> None:
    if (folder / "index.m3u8").exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x480:rate=15", "-t", "6",
            "-vf", f"scale={size}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
            "-pix_fmt", "yuv420p", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
            "-hls_segment_filename", str(folder / "seg%03d.ts"), str(folder / "index.m3u8"),
        ],
        check=True,
    )


PAGE = """<!doctype html><html><body>
<button class="play-button">▶ Lecture</button>
<script>
document.querySelector('.play-button').onclick = async () => {
  // le player charge d'abord le master, puis bascule sur une variante
  await fetch('/master.m3u8').catch(() => {});
  setTimeout(() => fetch('/low/index.m3u8').catch(() => {}), 400);
};
</script></body></html>"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(MEDIA), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        if re.search(r"-\d+-vostfr/?$", urlparse(self.path).path):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main() -> int:
    make_hls(MEDIA / "low", "320:240")
    make_hls(MEDIA / "high", "640:480")
    MEDIA.mkdir(exist_ok=True)
    (MEDIA / "master.m3u8").write_text(
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=320x240\nlow/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=640x480\nhigh/index.m3u8\n",
        encoding="utf-8",
    )

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    cfg = {
        "headless": True,
        "capture_timeout_s": 8,
        "source_buttons": [],
        "source_selectors": [],
        "play_selectors": [".play-button"],
        "dismiss_selectors": [],
        "min_manifest_duration_s": 2,
        "allow_unknown_duration": False,
        "ad_hosts": [],
        "episode_pattern": r"-(\d+)-vostfr/?$",
        "quality": "240",
        "user_data_dir": str(HERE / ".profile"),
    }

    url = f"http://127.0.0.1:{PORT}/serie/ma-serie-01-vostfr/"
    profile = HERE / ".profile"
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(profile), headless=True)
        cap = ManifestCapture(ctx, cfg)
        result = cap.capture(url, 0, tag="MASTER")
        cap.close()
        ctx.close()
    httpd.shutdown()
    shutil.rmtree(profile, ignore_errors=True)

    checks = [
        (result is not None, "manifest capté"),
        (bool(result and result.url.endswith("/master.m3u8")), "master retenu, pas la sous-playlist"),
        (bool(result and len(result.variants) == 2), "2 qualités disponibles pour le choix"),
        (bool(result and result.variant_url and "/high/" in result.variant_url),
         "meilleure variante calculée"),
        (bool(result and result.fingerprint), "empreinte de flux calculée"),
    ]
    if result:
        log(f"  url retenue : {result.url}")
        log(f"  variantes   : {', '.join(v.label for v in result.variants)}")

    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
