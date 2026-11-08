"""Test : un TS déguisé en .mp4 est remuxé en vrai MP4 indexé (seek fluide)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common import ensure_mp4, ffmpeg_exe, log, mp4_is_indexed  # noqa: E402
from downloader import probe_duration  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE / ".work"


def build_ts(target: Path) -> None:
    """Génère un MPEG-TS comme le fait le téléchargeur HLS de yt-dlp."""
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
            "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "4", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest",
            "-f", "mpegts", str(target),
        ],
        check=True,
    )


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)

    ts = WORK / "source.ts"
    build_ts(ts)
    fake_mp4 = WORK / "S01E01.mp4"
    shutil.copyfile(ts, fake_mp4)

    checks: list[tuple[bool, str]] = []
    checks.append((not mp4_is_indexed(fake_mp4), "TS renommé .mp4 détecté (pas d'index)"))
    checks.append((fake_mp4.read_bytes()[:1] == b"\x47", "le fichier de test commence bien par 0x47"))

    before_duration = probe_duration(fake_mp4, ffmpeg_exe())
    fixed = ensure_mp4(fake_mp4)
    after_duration = probe_duration(fixed, ffmpeg_exe())
    size_before = fake_mp4.stat().st_size

    checks.append((fixed == fake_mp4, "le fichier est remplacé sur place"))
    checks.append((mp4_is_indexed(fixed), "MP4 indexé après remux"))
    checks.append((fixed.read_bytes()[4:8] == b"ftyp", "en-tête MP4 (ftyp) présent"))
    checks.append((before_duration is not None and after_duration is not None
                   and abs(before_duration - after_duration) < 0.5,
                   f"durée conservée ({before_duration} -> {after_duration})"))
    checks.append((fixed.stat().st_size > 0 and size_before > 0, "taille non nulle"))

    # deuxième passage : aucun réencodage inutile
    stamp = fixed.stat().st_mtime_ns
    ensure_mp4(fixed)
    checks.append((fixed.stat().st_mtime_ns == stamp, "second appel = aucun travail"))

    # désactivable
    plain = WORK / "plain.mp4"
    shutil.copyfile(ts, plain)
    ensure_mp4(plain, enabled=False)
    checks.append((not mp4_is_indexed(plain), "remux_mp4: false respecté"))

    shutil.rmtree(WORK, ignore_errors=True)

    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
