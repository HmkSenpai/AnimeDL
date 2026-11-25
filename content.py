"""Empreinte visuelle indépendante du flux : anti-doublon avant et après téléchargement.

Deux images 32x32 en niveaux de gris, prélevées à 35 % et 75 % de la durée,
comparées par distance de Hamming. La même vidéo réencodée dans une autre
qualité reste très proche ; un autre épisode ne l'est pas.

- `stream_hash()` lit directement le manifest HLS capté (quelques segments
  seulement) : sert à refuser un épisode rejoué **avant** de télécharger.
- `visual_hash()` lit le fichier final : filet de sécurité après téléchargement.

Coût : deux appels ffmpeg avec seek (~0,2 à 0,8 s par source).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Mapping

from common import ffmpeg_exe

_SIZE = 32                  # 32x32 pixels = 1024 bits par image
_MAX_DIFF = 0.06            # 6 % de bits différents tolérés (réencodage)


def _header_args(headers: Mapping[str, str] | None) -> list[str]:
    if not headers:
        return []
    text = "".join(f"{key}: {value}\r\n" for key, value in headers.items() if value)
    return ["-headers", text] if text.strip() else []


def _probe_duration(source: str, ffmpeg: str, headers: Mapping[str, str] | None = None) -> float | None:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", *_header_args(headers), "-i", source],
        capture_output=True, text=True, errors="replace",
    )
    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", proc.stderr)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def frame_hash(
    source: str,
    ffmpeg: str,
    seconds: float,
    headers: Mapping[str, str] | None = None,
) -> str | None:
    """aHash d'une image 32x32 grise extraite à `seconds` d'un fichier ou d'une URL."""
    proc = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            *_header_args(headers),
            "-ss", f"{max(0.0, seconds):.3f}", "-i", source,
            "-map", "0:v:0", "-frames:v", "1",
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


def _hash_source(
    source: str,
    ffmpeg: str | None,
    duration: float | None,
    headers: Mapping[str, str] | None,
) -> str | None:
    exe = ffmpeg or ffmpeg_exe()
    if not duration:
        duration = _probe_duration(source, exe, headers)
    stamps = (duration * 0.35, duration * 0.75) if duration and duration >= 4 else (1.0, 3.0)
    hashes = [frame_hash(source, exe, seconds, headers) for seconds in stamps]
    if not all(hashes):
        return None
    return ":".join(hashes)  # type: ignore[arg-type]


def visual_hash(path: Path, ffmpeg: str | None = None,
                duration: float | None = None) -> str | None:
    """Empreinte visuelle d'un fichier vidéo local, ou None si illisible."""
    if not path.exists():
        return None
    return _hash_source(str(path), ffmpeg, duration, None)


def stream_hash(
    url: str,
    ffmpeg: str | None = None,
    duration: float | None = None,
    headers: Mapping[str, str] | None = None,
) -> str | None:
    """Empreinte visuelle d'un manifest HLS, sans télécharger l'épisode entier.

    ffmpeg ne récupère que les segments autour des deux instants demandés
    (quelques Mo au plus), avec les en-têtes du navigateur capturés.
    """
    if not url:
        return None
    return _hash_source(url, ffmpeg, duration, headers)


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
