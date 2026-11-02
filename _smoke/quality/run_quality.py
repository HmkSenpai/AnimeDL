"""Test qualité : détection des variantes + sélection 240p + barre sans rétrécissement."""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common import ffmpeg_exe, log
from downloader import _bar, download, format_selector, probe_duration, requested_height
from hls import inspect

HERE = Path(__file__).resolve().parent
PORT = 8768


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


def main() -> int:
    make_hls(HERE / "low", "320:240")
    make_hls(HERE / "high", "640:480")
    (HERE / "master.m3u8").write_text(
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=320x240\nlow/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=640x480\nhigh/index.m3u8\n",
        encoding="utf-8",
    )

    handler = partial(SimpleHTTPRequestHandler, directory=str(HERE))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    master = f"http://127.0.0.1:{PORT}/master.m3u8"
    info = inspect(master, {"User-Agent": "test"})
    if not info or len(info.variants) != 2:
        log("QUALITY FAIL ❌ : variantes non détectées")
        httpd.shutdown()
        return 1
    log("variantes : " + ", ".join(v.label for v in info.variants))

    cfg = {
        "user_data_dir": str(HERE / ".profile"),
        "min_duration_s": 2,
        "min_size_mb": 0,
        "fragment_concurrency": 2,
        "ytdlp": {},
    }
    out = HERE / "out" / "quality - S01E01.%(ext)s"
    final, duration = download(master, master, "test-agent", out, cfg, "Q", quality="240")
    probe = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(final)],
                           capture_output=True, text=True, errors="ignore")
    m = re.search(r"(\d{2,4})x(\d{2,4})", probe.stderr or "")
    height = int(m.group(2)) if m else 0
    log(f"fichier : {final.name} — {height}p, {duration}s")

    checks = [
        (format_selector("720") == "best[height<=720]/best", "sélecteur 720"),
        (format_selector("worst") == "worst", "sélecteur worst"),
        (info.variants[0].height == 480, "tri décroissant"),
        (height == 240, "téléchargement en 240p"),
        (_bar(0).count("█") == 0 and _bar(0).count("░") == 22, "barre à 0 %"),
        (_bar(50).count("█") == 11, "barre à 50 %"),
        (_bar(100).count("░") == 0, "barre à 100 %"),
        (requested_height("720") == 720 and requested_height("worst") is None,
         "hauteur demandée extraite"),
    ]
    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)

    httpd.shutdown()
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
