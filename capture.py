"""Capture du manifest HLS (master.m3u8) en pilotant le player dans Chromium.

Le player est souvent dans une iframe et le bouton Play est un <div> qui ouvre
parfois une pub. On combine donc : blocage pub (adblock.py), clics heuristiques
multi-frames, et **validation HTTP de chaque manifest** (durée, #EXTM3U) pour ne
jamais télécharger la vidéo publicitaire.
"""
from __future__ import annotations

import json
import re
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

JS_DETECT_SOURCES = """() => {
  const rx = /(lecteur|serveur|server|source|player|mirror|h[ée]bergeur|streamtape|voe|moon|mytv)/i;
  const out = {selects: [], tabs: []};

  document.querySelectorAll('select').forEach((sel, si) => {
    const options = [...sel.options].map(o => (o.textContent || '').trim());
    if (!options.some(t => rx.test(t))) return;
    sel.setAttribute('data-adl-select', String(si));
    out.selects.push({marker: si, options, selected: sel.selectedIndex});
  });

  const seen = new Set();
  for (const el of document.querySelectorAll('button,[role=button],a,li,div,span')) {
    const txt = (el.textContent || '').trim();
    if (!txt || txt.length > 40) continue;
    if (!rx.test(txt)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 6 || r.height < 6) continue;
    if (seen.has(txt)) continue;
    seen.add(txt);
    el.setAttribute('data-adl-tab', String(out.tabs.length));
    out.tabs.push(txt);
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
    fingerprint: str = ""


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
        self._loaded_episode: str | None = None
        self.sources: list[str] = []
        try:
            self._pattern: re.Pattern[str] | None = re.compile(
                str(cfg.get("episode_pattern") or r"-(\d+)-(?:vostfr|vf)/?$")
            )
        except re.error:
            self._pattern = None
        self._select_handle: tuple[Frame, int] | None = None
        self._tabs_frame: Frame | None = None

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

    # ------------------------------------------------------------ serveurs
    def detect_sources(self) -> list[str]:
        """Détecte tous les serveurs proposés (native <select> ou onglets)."""
        self.sources = []
        self._select_handle = None
        self._tabs_frame = None
        for frame in self._frames():
            try:
                data = frame.evaluate(JS_DETECT_SOURCES)
            except Exception:
                continue
            selects = data.get("selects") or []
            if selects:
                chosen = max(selects, key=lambda s: len(s.get("options") or []))
                self.sources = [str(o) for o in chosen.get("options") or []]
                self._select_handle = (frame, int(chosen.get("marker", 0)))
                log(f"[serveurs] {len(self.sources)} détecté(s) : {self.sources}")
                return self.sources
            tabs = data.get("tabs") or []
            if len(tabs) > 1:
                self.sources = [str(t) for t in tabs]
                self._tabs_frame = frame
                log(f"[serveurs] {len(self.sources)} onglet(s) : {self.sources}")
                return self.sources
        return self.sources

    def source_count(self) -> int:
        return len(self.sources)

    def _select_source(self, index: int) -> bool:
        """index 0 = premier serveur (déjà actif), index >= 1 = bascule."""
        assert self.page is not None
        if index <= 0:
            return True

        # 1) <select> natif : sélection par position
        if self._select_handle:
            frame, marker = self._select_handle
            try:
                el = frame.query_selector(f"select[data-adl-select='{marker}']")
                if el:
                    el.select_option(index=index)
                    label = self.sources[index] if index < len(self.sources) else str(index)
                    log(f"[serveurs] sélection : {label}")
                    return True
            except Exception as exc:
                log(f"[serveurs] select impossible ({exc})")

        # 2) onglets / menu déroulant custom
        if self._tabs_frame:
            frame = self._tabs_frame
            try:
                els = frame.query_selector_all("[data-adl-tab]")
                if els and index < len(els):
                    if not els[index].is_visible() and els:
                        els[0].click(timeout=1500, force=True)
                        self.page.wait_for_timeout(700)
                        els = frame.query_selector_all("[data-adl-tab]")
                    if index < len(els):
                        els[index].click(timeout=2500, force=True)
                        log(f"[serveurs] onglet cliqué : {self.sources[index]}")
                        return True
            except Exception:
                pass

        # 3) libellés / sélecteurs du config
        labels = self.cfg.get("source_buttons", [])
        wanted = labels[index] if index < len(labels) else None
        if wanted:
            for frame in self._frames():
                try:
                    loc = frame.get_by_text(wanted, exact=False)
                    if loc.count():
                        loc.first.click(timeout=3000)
                        log(f"[serveurs] sélection config : {wanted}")
                        return True
                except Exception:
                    continue

        for selector in self.cfg.get("source_selectors", []):
            try:
                loc = self.page.locator(selector).nth(index)
                if loc.count():
                    loc.click(timeout=3000)
                    log(f"[serveurs] sélection ({selector})")
                    return True
            except Exception:
                continue

        log(f"[serveurs] bascule #{index + 1} impossible")
        return False

    # -------------------------------------------------------- validation HLS
    def _fingerprint(self, info: hls.ManifestInfo) -> str:
        """Empreinte du contenu : premier segment (ou manifest) + durée.

        Deux épisodes différents ne doivent pas produire la même empreinte :
        c'est ce qui détecte un player resté bloqué sur l'épisode précédent.
        """
        raw = info.segment or info.variant_url or info.url
        return f"{urlparse(raw).path}|{round(info.duration or 0)}"

    def _episode_number(self, url: str) -> int | None:
        if not self._pattern:
            return None
        match = self._pattern.search(urlparse(url).path)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (IndexError, TypeError, ValueError):
            return None

    def _evaluate_candidates(self) -> CaptureResult | None:
        """Valide les nouveaux manifests et retient le meilleur candidat.

        Priorité au **master** (plusieurs variantes) : c'est le seul qui permet de
        respecter la qualité demandée. Le player, lui, demande souvent directement
        une sous-playlist (`index-v1-a1.m3u8`), ce qui figeait le débit maximal.
        """
        min_dur = float(self.cfg.get("min_manifest_duration_s", 60))
        candidates: list[CaptureResult] = []
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
                fingerprint=self._fingerprint(info),
            )
            if info.duration is None:
                # pas de #EXTINF lisible : accepté seulement si autorisé
                if self.cfg.get("allow_unknown_duration", False):
                    candidates.append(cand)
                continue
            if dur >= min_dur:
                candidates.append(cand)
            elif dur > best_dur:
                # trop court => très probablement une pub, on garde de côté
                best, best_dur = cand, dur

        if candidates:
            masters = [c for c in candidates if len(c.variants) > 1]
            if masters:
                chosen = max(masters, key=lambda c: len(c.variants))
                log(f"[hls] master retenu ({len(chosen.variants)} qualités) — le choix de qualité s'applique")
                return chosen
            log("[hls] flux unique (aucune variante) — la qualité ne peut pas être modifiée")
            return candidates[0]

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

    @staticmethod
    def _canonical(url: str) -> str:
        """Identité d'une page : chemin + query triée.

        Certains sites changent d'épisode via un paramètre (`?ep=2`) : comparer
        uniquement le chemin ferait croire qu'on est déjà sur la bonne page.
        """
        parsed = urlparse(url)
        query = "&".join(sorted(part for part in parsed.query.split("&") if part))
        return f"{parsed.path.rstrip('/').lower()}?{query.lower()}"

    def _same_episode_loaded(self, url: str) -> bool:
        return self._loaded_episode is not None and self._loaded_episode == self._canonical(url)

    def _check_landing_page(self, requested: str, tag: str) -> bool:
        """Vérifie que la page affichée est bien l'épisode demandé (pas de redirection)."""
        assert self.page is not None
        final = self.page.url or ""
        if not final or self._canonical(final) == self._canonical(requested):
            return True

        log(f"[capture] page finale différente : {final[:120]}")
        want, got = self._episode_number(requested), self._episode_number(final)
        if want is not None and got is not None and want != got:
            log(f"[capture] E{want:02d} demandé mais E{got:02d} affiché — capture annulée")
            self._dump_report(tag)
            return False
        if want is not None and got is None:
            log("[capture] la page a quitté la fiche épisode — capture annulée")
            self._dump_report(tag)
            return False
        return True

    def capture(self, episode_url: str, source_index: int = 0, tag: str = "") -> CaptureResult | None:
        timeout_s = int(self.cfg.get("capture_timeout_s", 35))
        self._seen = []
        self._checked = set()
        self._requests = []
        self._source_index = source_index

        self.ensure_page()

        if not self._same_episode_loaded(episode_url):
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
            if not self._check_landing_page(episode_url, tag):
                self._loaded_episode = None
                return None
            self._loaded_episode = self._canonical(episode_url)
            self.detect_sources()
            if source_index > 0:
                self._select_source(source_index)
                self.page.wait_for_timeout(2500)
        else:
            log(f"[capture] bascule vers le serveur #{source_index + 1}")
            self._select_source(source_index)
            self.page.wait_for_timeout(2500)

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
        self._loaded_episode = None
