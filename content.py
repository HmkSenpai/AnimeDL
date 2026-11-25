"""Empreinte visuelle du fichier final : sécurité anti-doublon indépendante du flux.

Les URLs HLS peuvent changer de token, de dossier ou de variante d'une lecture à
l'autre : l'empreinte du manifest peut donc rater un épisode rejoué. Ici on
compare les **pixels réellement téléchargés** : deux images 32x32 en niveaux de
gris, prélevées à 35 % et 75 % de la durée, comparées par distance de Hamming.
La même vidéo réencodée dans une autre qualité reste très proche ; un autre
épisode ne l'est pas.

Coût : deux appels ffmpeg avec seek (~0,2 à 0,5 s par fichier).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from common import ffmpeg_exe

_SIZE = 32                  # 32x32 pixels = 1024 bits par image
_MAX_DIFF = 0.06            # 6 % de bits différents tolérés (réencodage)


def _probe_duration(path: Path, ffmpeg: str) -> float | None:
    import re

    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)],
                          capture_output=True, text=True, errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", proc.stderr)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def frame_hash(path: Path, ffmpeg: str, seconds: float) -> str | None:
    """aHash d'une image 32x32 grise extraite à `seconds`."""
    proc = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{max(0.0, seconds):.3f}", "-i", str(path),
            "-frames:v", "1",
            "-vf", f"scale={_SIZE}:{_SIZE}:flags=area,format=gray",
            "-pix_fmt", "gray", "-f", "rawvideo", "-",
        ],
        capture_output=True,
    )
    pixels = proc.stdout[: _SIZE * _SIZE]
    if len(pixels) < _SIZE * _SIZE:
        return None
    # image quasi uniforme (noir, fondu) : empreinte non discriminante
    if max(pixels) - min(pixels) < 10:
        return None
    mean = sum(pixels) / len(pixels)
    bits = "".join("1" if value >= mean else "0" for value in pixels)
    return format(int(bits, 2), f"0{_SIZE * _SIZE // 4}x")


def visual_hash(path: Path, ffmpeg: str | None = None,
                duration: float | None = None) -> str | None:
    """Empreinte visuelle (2 images) d'un fichier vidéo, ou None si illisible."""
    if not path.exists():
        return None
    exe = ffmpeg or ffmpeg_exe()
    if not duration:
        duration = _probe_duration(path, exe)

    stamps = (duration * 0.35, duration * 0.75) if duration and duration >= 4 else (1.0, 3.0)
    hashes = [frame_hash(path, exe, seconds) for seconds in stamps]
    if not all(hashes):
        return None
    return ":".join(hashes)  # type: ignore[arg-type]


def same_content(first: str | None, second: str | None, max_diff: float = _MAX_DIFF) -> bool:
    """Vrai si deux empreintes visuelles désignent la même vidéo."""
    if not first or not second:
        return False
    a, b = first.split(":"), second.split(":")
    if len(a) != len(b):
        return False
    for ha, hb in zip(a, b):
        if len(ha) != len(hb):
            return False
        diff = (int(ha, 16) ^ int(hb, 16)).bit_count() / (len(ha) * 4)
        if diff > max_diff:
            return False
    return True
