"""Capture du manifest HLS (master.m3u8) en pilotant le player dans Chromium.

Le player est souvent dans une iframe et le bouton Play est un <div> qui ouvre
parfois une pub. On combine donc : blocage pub (adblock.py), clics heuristiques
multi-frames, et **validation HTTP de chaque manifest** (durée, #EXTM3U) pour ne
jamais télécharger la vidéo publicitaire.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Frame, Page, TimeoutError as PWTimeout

import hls
from adblock import AD_HOST_HINTS, AD_PATH_HINTS
from common import ROOT, log
from hls import Variant

M3U8_HINTS = (".m3u8", "m3u8")
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

JS_MARK_PLAY = """() => {
  const rx = /(play|lecteur|regarder|launch)/i;
  const out = [];
  for (const el of document.querySelectorAll('button,[role=button],a,div,span,svg,i')) {
    const sig = [el.className, el.id, el.getAttribute('aria-label'),
                 el.getAttribute('title'), el.getAttribute('data-title')].join(' ');
    if (!rx.test(sig)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.width > 700 || r.height > 500) continue;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || +st.opacity === 0) continue;
    el.setAttribute('data-adl-play', String(out.length));
    out.push({w: Math.round(r.width), h: Math.round(r.height), cls: String(el.className).slice(0, 80)});
  }
  return out;
}"""

JS_MARK_PLAYER = """() => {
  const rx = /(player|poster|thumb|cover|video-?(wrap|container|player)|embed|episode)/i;
  const out = [];
  for (const el of document.querySelectorAll('div,a,img,section')) {
    const sig = [el.className, el.id, el.getAttribute('data-title')].join(' ');
    if (!rx.test(sig)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 120 || r.width > 2200) continue;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    el.setAttribute('data-adl-player', String(out.length));
    out.push({w: Math.round(r.width), h: Math.round(r.height), cls: String(el.className).slice(0, 60)});
  }
  return out;
}"""

JS_MARK_SOURCES = """() => {
  const rx = /(serveur|server|source|lecteur|player|h[ée]bergeur|host|mirror)/i;
  const out = [];
  for (const el of document.querySelectorAll('button,[role=button],a,li,div,span')) {
    const txt = (el.textContent || '').trim();
    if (txt.length > 60) continue;
    const sig = txt + ' ' + String(el.className) + ' ' + (el.id || '');
    if (!rx.test(sig)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 6 || r.height < 6) continue;
    el.setAttribute('data-adl-source', String(out.length));
    out.push(txt.slice(0, 40));
  }
  return out;
}"""

JS_PLAYER_STATE = """() => {
  const vids = [...document.querySelectorAll('video')].map(v => ({
    cls: String(v.className).slice(0, 60),
    readyState: v.readyState, paused: v.paused,
    src: (v.currentSrc || v.src || '').slice(0, 100),
    w: Math.round(v.getBoundingClientRect().width), h: Math.round(v.getBoundingClientRect().height),
  }));
  return {videos: vids, title: document.title};
}"""


@dataclass
class CaptureResult:
    url: str
    referer: str
    user_agent: str
    source_index: int
    cookie: str = ""
    variant_url: str | None = None
    duration: float | None = None
    duration_unknown: bool = False
    variants: list[Variant] = field(default_factory=list)


@dataclass
class _Seen:
    url: str
    referer: str


class ManifestCapture:
    def __init__(self, context: BrowserContext, cfg: dict[str, Any]) -> None:
        self.ctx = context
        self.cfg = cfg
        self.page: Page | None = None
        self._seen: list[_Seen] = []
        self._checked: set[str] = set()
        self._requests: list[str] = []
        self._ua = ""
        self._source_index = 0

    # ------------------------------------------------------------------ utils
    def _is_ad_url(self, url: str) -> bool:
        low = url.lower()
        if any(h in low for h in AD_HOST_HINTS + tuple(self.cfg.get("ad_hosts", []))):
            return True
        path = low.split("?", 1)[0]
        return any(p in path for p in AD_PATH_HINTS)

    def _on_request(self, request) -> None:
        url = request.url
        self._requests.append(url)
        if len(self._requests) > 500:
            del self._requests[:300]
        if not any(h in url.lower() for h in M3U8_HINTS):
            return
        if self._is_ad_url(url):
            return
        headers = request.headers or {}
        referer = headers.get("referer") or self._current_url
        self._seen.append(_Seen(url, referer))

    @property
    def _current_url(self) -> str:
        return self.page.url if self.page else ""

    def _frames(self) -> list[Frame]:
        return list(self.page.frames) if self.page else []  # type: ignore[union-attr]

    def _headers_for(self, url: str, referer: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self._ua or DEFAULT_UA,
            "Referer": referer or self._current_url or url,
            "Accept": "*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }
        parsed = urlparse(self._current_url or url)
        if parsed.scheme and parsed.netloc:
            headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
        try:
            cookies = self.ctx.cookies([url])
        except Exception:
            cookies = []
        if cookies:
            headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        return headers

    # --------------------------------------------------------------- actions
    def _dismiss(self) -> None:
        selectors = list(self.cfg.get("dismiss_selectors", []))
        selectors += [
            ".modal .close",
            "[class*='close-button']",
            "[class*='popup'] [class*='close']",
            "button[aria-label*='close' i]",
        ]
        for frame in self._frames():
            for selector in selectors:
                try:
                    for el in frame.query_selector_all(selector):
                        if el.is_visible():
                            el.click(timeout=700)
                            log(f"[capture] popup fermée ({selector})")
                except Exception:
                    continue

    def _click_play_everywhere(self) -> bool:
        clicked = False
        assert self.page is not None

        for frame in self._frames():
            for selector in self.cfg.get("play_selectors", []):
                try:
                    for el in frame.query_selector_all(selector):
                        if el.is_visible():
                            el.click(timeout=1500, force=True)
                            log(f"[capture] clic play ({selector})")
                            clicked = True
                            break
                except Exception:
                    continue
                if clicked:
                    break
            if clicked:
                break

            try:
                marked = frame.evaluate(JS_MARK_PLAY)
            except Exception:
                marked = []
            for cand in marked[:4]:
                try:
                    for el in frame.query_selector_all("[data-adl-play]"):
                        if el.is_visible():
                            el.click(timeout=1500, force=True)
                            log(f"[capture] clic play (heuristique: {str(cand.get('cls', ''))[:40]})")
                            clicked = True
                            break
                except Exception:
                    continue
                if clicked:
                    break
            if clicked:
                break

        if not clicked:
            for frame in self._frames():
                try:
                    marked = frame.evaluate(JS_MARK_PLAYER)
                except Exception:
                    marked = []
                for cand in marked[:2]:
                    try:
                        for el in frame.query_selector_all("[data-adl-player]"):
                            if el.is_visible():
                                el.click(timeout=1500, force=True)
                                log(f"[capture] clic conteneur player ({str(cand.get('cls', ''))[:40]})")
                                clicked = True
                                break
                    except Exception:
                        continue
                    if clicked:
                        break
                if clicked:
                    break

        if not clicked:
            for frame in self._frames():
                try:
                    video = frame.query_selector("video")
                    if video:
                        box = video.bounding_box()
                        if box and box["width"] > 20 and box["height"] > 20:
                            self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            log("[capture] clic au centre de la vidéo")
                            clicked = True
                            break
                except Exception:
                    continue

        if not clicked:
            try:
                best = None
                for el in self.page.query_selector_all("iframe"):
                    box = el.bounding_box()
                    if box and (best is None or box["width"] * box["height"] > best["width"] * best["height"]):
                        best = box
                if best and best["width"] > 100:
                    self.page.mouse.click(best["x"] + best["width"] / 2, best["y"] + best["height"] / 2)
                    log("[capture] clic au centre de l'iframe")
                    clicked = True
            except Exception:
                pass

        self._js_play_all_frames()
        return clicked

    def _js_play_all_frames(self) -> None:
        for frame in self._frames():
            try:
                frame.evaluate(
                    """() => {
                        for (const v of document.querySelectorAll('video')) {
                            v.muted = true;
                            if (v.paused) v.play().catch(() => {});
                        }
                    }"""
                )
            except Exception:
                continue

    def _click_source_button(self, index: int) -> None:
        """index 1 => 2e serveur (le premier est déjà actif par défaut)."""
        assert self.page is not None
        labels = self.cfg.get("source_buttons", [])
        wanted = labels[index - 1] if 0 <= index - 1 < len(labels) else None
        log(f"[capture] recherche du serveur #{index + 1}" + (f" ({wanted})" if wanted else ""))

        if wanted:
            for frame in self._frames():
                try:
                    loc = frame.get_by_text(wanted, exact=False)
                    if loc.count():
                        loc.first.click(timeout=3000)
                        log(f"[capture] serveur sélectionné : {wanted}")
                        return
                except Exception:
                    continue

        for selector in self.cfg.get("source_selectors", []):
            try:
                loc = self.page.locator(selector).nth(index - 1)
                if loc.count():
                    loc.click(timeout=3000)
                    log(f"[capture] serveur sélectionné ({selector})")
                    return
            except Exception:
                continue

        for frame in self._frames():
            try:
                texts = frame.evaluate(JS_MARK_SOURCES)
            except Exception:
                continue
            if not texts:
                continue
            if index < len(texts):
                try:
                    for el in frame.query_selector_all(f"[data-adl-source='{index}']"):
                        if el.is_visible():
                            el.click(timeout=3000, force=True)
                            log(f"[capture] serveur sélectionné (heuristique: {texts[index]})")
                            return
                except Exception:
                    continue
            log(f"[capture] serveurs détectés : {texts}")

        log("[capture] aucun onglet serveur trouvé — bascule ignorée")

    # -------------------------------------------------------- validation HLS
    def _evaluate_candidates(self) -> CaptureResult | None:
        """Valide les nouveaux manifests ; renvoie le premier qui ressemble à l'épisode."""
        min_dur = float(self.cfg.get("min_manifest_duration_s", 60))
        best: CaptureResult | None = None
        best_dur = -1.0

        for seen in reversed(self._seen):
            if seen.url in self._checked:
                continue
            self._checked.add(seen.url)
            headers = self._headers_for(seen.url, seen.referer)
            info = hls.inspect(seen.url, headers)
            if info is None:
                log(f"[hls] manifest invalide/expiré ignoré : {seen.url[:90]}")
                continue
            dur = info.duration or 0.0
            log(f"[hls] candidat valide — durée {dur:.0f}s — {seen.url[:90]}")
            if info.variants:
                log("[hls] qualités : " + ", ".join(f"{v.label} ({v.bitrate})" for v in info.variants))
            cand = CaptureResult(
                url=info.url,
                referer=headers.get("Referer", ""),
                user_agent=headers.get("User-Agent", DEFAULT_UA),
                source_index=self._source_index,
                cookie=headers.get("Cookie", ""),
                variant_url=info.variant_url,
                duration=info.duration,
                duration_unknown=info.duration is None,
                variants=info.variants,
            )
            if info.duration is None:
                # pas de #EXTINF lisible : accepté seulement si autorisé
                if self.cfg.get("allow_unknown_duration", False):
                    return cand
                continue
            if dur >= min_dur:
                return cand
            # trop court => très probablement une pub, on garde de côté
            if dur > best_dur:
                best, best_dur = cand, dur

        if best is not None:
            log(f"[hls] aucun manifest ≥ {min_dur:.0f}s ; le plus long vu : {best_dur:.0f}s (pub ?)")
        return None

    # ---------------------------------------------------------------- rapport
    def _dump_report(self, tag: str) -> Path:
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shot = logs / f"fail-{tag or 'capture'}-{stamp}.png"
        report = logs / f"fail-{tag or 'capture'}-{stamp}.json"
        try:
            self.page.screenshot(path=str(shot))  # type: ignore[union-attr]
        except Exception:
            pass
        data = {
            "page_url": self._current_url,
            "frames": [{"url": f.url, "name": f.name} for f in self._frames()],
            "requests": self._requests[-100:],
            "manifests": [s.url for s in self._seen],
            "players": [],
        }
        for frame in self._frames():
            try:
                data["players"].append({"frame": frame.url, **(frame.evaluate(JS_PLAYER_STATE) or {})})
            except Exception:
                continue
        report.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"[capture] rapport d'échec : {report}")
        if shot.exists():
            log(f"[capture] screenshot : {shot}")
        return report

    # ---------------------------------------------------------------- capture
    def ensure_page(self) -> Page:
        if self.page is None:
            self.page = self.ctx.new_page()
            self.page.on("request", self._on_request)
        return self.page

    def capture(self, episode_url: str, source_index: int = 0, tag: str = "") -> CaptureResult | None:
        timeout_s = int(self.cfg.get("capture_timeout_s", 35))
        self._seen = []
        self._checked = set()
        self._requests = []
        self._source_index = source_index

        self.ensure_page()

        if source_index == 0 or not self.page.url:
            log(f"[capture] navigation -> {episode_url}")
            try:
                self.page.goto(episode_url, wait_until="domcontentloaded", timeout=60_000)
            except PWTimeout:
                log("[capture] timeout de chargement de la page")
                self._dump_report(tag)
                return None
            try:
                self.page.wait_for_load_state("load", timeout=15_000)
            except Exception:
                pass
            self.page.wait_for_timeout(2500)
        else:
            log(f"[capture] bascule vers le serveur #{source_index + 1}")
            self._click_source_button(source_index)
            self.page.wait_for_timeout(2000)

        try:
            self._ua = self.page.evaluate("() => navigator.userAgent")
        except Exception:
            pass

        self._dismiss()
        self._click_play_everywhere()

        deadline = timeout_s * 10
        next_click = 20   # 2 s
        next_check = 10   # 1 s
        while deadline > 0:
            self.page.wait_for_timeout(100)
            deadline -= 1

            next_check -= 1
            if next_check <= 0:
                next_check = 10
                hit = self._evaluate_candidates()
                if hit:
                    log(f"[capture] manifest retenu : {hit.url[:110]}…")
                    return hit

            next_click -= 1
            if next_click <= 0:
                self._dismiss()
                self._click_play_everywhere()
                next_click = 20

        log(f"[capture] aucun manifest exploitable après {timeout_s}s (source #{source_index + 1})")
        self._dump_report(tag)
        return None

    def close(self) -> None:
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        self.page = None
