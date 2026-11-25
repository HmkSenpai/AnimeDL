"""Test : l'empreinte visuelle reconnaît le même épisode réencodé, pas un autre."""
from __future__ import annotations

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

from common import ffmpeg_exe, log  # noqa: E402
from content import same_content, stream_hash, visual_hash  # noqa: E402
from progress import Progress  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE / ".work"
FF = ffmpeg_exe()


class CountingHandler(SimpleHTTPRequestHandler):
    total = 0

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):  # noqa: N802
        local = WORK / urlparse(self.path).path.lstrip("/")
        if local.is_file():
            type(self).total += local.stat().st_size
        super().do_GET()


def build_hls(video: Path, name: str) -> Path:
    playlist = WORK / "hls" / f"{name}.m3u8"
    playlist.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
         "-c", "copy", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
         "-hls_segment_filename", str(playlist.parent / f"{name}_%03d.ts"),
         str(playlist)], check=True,
    )
    return playlist


def make(name: str, source: str, extra: list[str] | None = None) -> Path:
    target = WORK / name
    cmd = [
        FF, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", source, "-t", "8",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
    ]
    cmd += extra or []
    cmd += [str(target)]
    subprocess.run(cmd, check=True)
    return target


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)

    a = make("a.mp4", "testsrc=size=320x240:rate=15")
    b = make("b.mp4", "smptebars=size=320x240:rate=15")
    # réencodage de A en basse qualité / autre résolution
    a2 = WORK / "a2.mp4"
    subprocess.run(
        [FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(a),
         "-vf", "scale=160:120", "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "34", str(a2)], check=True,
    )

    ha = visual_hash(a, FF)
    hb = visual_hash(b, FF)
    ha2 = visual_hash(a2, FF)
    checks: list[tuple[bool, str]] = [
        (bool(ha and hb and ha2), "empreintes calculées sur les 3 vidéos"),
        (same_content(ha, ha2), "même épisode réencodé en 160x120 = identique"),
        (not same_content(ha, hb), "deux vidéos différentes = différentes"),
        (not same_content(ha, None), "empreinte absente = pas de correspondance"),
        (visual_hash(WORK / "inexistant.mp4", FF) is None, "fichier absent -> None"),
    ]

    # contrôle AVANT téléchargement : empreinte lue directement depuis le HLS
    pa = build_hls(a, "a")
    pb = build_hls(b, "b")
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(CountingHandler, directory=str(WORK))
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    CountingHandler.total = 0
    sa = stream_hash(f"http://127.0.0.1:{port}/hls/{pa.name}", FF, 8)
    sb = stream_hash(f"http://127.0.0.1:{port}/hls/{pb.name}", FF, 8)
    fetched = CountingHandler.total
    httpd.shutdown()
    checks += [
        (same_content(sa, ha), "stream_hash HLS = empreinte du fichier final"),
        (not same_content(sa, hb), "stream HLS A différent du fichier B"),
        (fetched < 8 * 1024 * 1024, f"prélèvement < 8 Mo ({fetched / 1048576:.2f} Mo)"),
    ]

    state = WORK / ".progress.json"
    progress = Progress("serie", state)
    progress.mark_done("01", a, 0, "chemin|8", ha or "")
    progress.mark_done("02", b, 0, "autre|8", hb or "")
    checks.append((progress.content_map() == {ha: "01", hb: "02"},
                   "content_map rechargée depuis .progress.json"))

    shutil.rmtree(WORK, ignore_errors=True)
    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    log(f"  distances : A/A2={_distance(ha, ha2)}, A/B={_distance(ha, hb)}")
    return 0 if all(ok for ok, _ in checks) else 1


def _distance(first: str | None, second: str | None) -> str:
    if not first or not second:
        return "-"
    total = bits = 0
    for a, b in zip(first.split(":"), second.split(":")):
        total += (int(a, 16) ^ int(b, 16)).bit_count()
        bits += len(a) * 4
    return f"{100 * total / bits:.1f} %" if bits else "-"


if __name__ == "__main__":
    raise SystemExit(main())
