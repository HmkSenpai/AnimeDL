"""Inspection/validation d'un manifest HLS : est-ce la vraie vidéo ou une pub ?"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests

_DUR_RE = re.compile(r"#EXTINF:\s*([\d.]+)")
_VARIANT_RE = re.compile(r"#EXT-X-STREAM-INF:([^\n]*)\n([^\s#]+)")
_BW_RE = re.compile(r"BANDWIDTH=(\d+)")
_RES_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
_NAME_RE = re.compile(r'NAME="([^"]+)"')


@dataclass
class Variant:
    url: str
    bandwidth: int = 0
    width: int | None = None
    height: int | None = None
    name: str = ""

    @property
    def label(self) -> str:
        if self.height:
            return f"{self.height}p"
        if self.name:
            return self.name
        return f"{self.bandwidth // 1000} kb/s"

    @property
    def bitrate(self) -> str:
        return f"{self.bandwidth / 1_000_000:.1f} Mb/s" if self.bandwidth else "?"


@dataclass
class ManifestInfo:
    url: str
    duration: float | None
    variant_url: str | None
    vod: bool
    variants: list[Variant] = field(default_factory=list)


def _sum_durations(text: str) -> float:
    return sum(float(x) for x in _DUR_RE.findall(text))


def parse_variants(url: str, text: str) -> list[Variant]:
    """Extrait les renditions d'un master.m3u8, dédoublonnées par hauteur."""
    out: dict[int | str, Variant] = {}
    for attrs, uri in _VARIANT_RE.findall(text):
        bw_m = _BW_RE.search(attrs)
        res_m = _RES_RE.search(attrs)
        name_m = _NAME_RE.search(attrs)
        variant = Variant(
            url=urljoin(url, uri),
            bandwidth=int(bw_m.group(1)) if bw_m else 0,
            width=int(res_m.group(1)) if res_m else None,
            height=int(res_m.group(2)) if res_m else None,
            name=name_m.group(1) if name_m else "",
        )
        key: int | str = variant.height if variant.height else (variant.name or variant.url)
        prev = out.get(key)
        if prev is None or variant.bandwidth > prev.bandwidth:
            out[key] = variant
    return sorted(out.values(), key=lambda v: (v.height or 0, v.bandwidth), reverse=True)


def inspect(url: str, headers: dict[str, str], timeout: int = 15) -> ManifestInfo | None:
    """Renvoie les infos du manifest, ou None s'il est invalide/expiré.

    Ne lève jamais : sert de filtre pour éliminer pubs et URLs mortes.
    """
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None
    if not resp.ok:
        return None
    text = resp.text.lstrip()
    if not text.startswith("#EXTM3U"):
        return None

    variants = parse_variants(url, text)
    vod = "#EXT-X-ENDLIST" in text

    if variants:
        best = variants[0]
        try:
            vresp = requests.get(best.url, headers=headers, timeout=timeout)
        except requests.RequestException:
            return ManifestInfo(url, None, best.url, vod, variants)
        if not vresp.ok or "#EXTM3U" not in vresp.text[:50]:
            return ManifestInfo(url, None, best.url, vod, variants)
        return ManifestInfo(url, _sum_durations(vresp.text), best.url,
                            "#EXT-X-ENDLIST" in vresp.text, variants)

    return ManifestInfo(url, _sum_durations(text), None, vod, [])
