"""Récupération de la liste des épisodes d'une série."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import Page

from common import log


@dataclass
class Episode:
    number: int
    url: str
    lang: str
    label: str

    @property
    def code(self) -> str:
        return f"{self.number:02d}"


_TRACKING_KEYS = ("utm_", "fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "referrer", "ref")


def clean_href(href: str) -> str:
    """URL absolue sans fragment ni paramètres de tracking.

    La query est conservée : certains sites changent d'épisode uniquement par un
    paramètre (`?ep=2`). La supprimer faisait pointer tous les épisodes vers le
    même player.
    """
    parsed = urlparse(href)
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower() == t or key.lower().startswith(t) for t in _TRACKING_KEYS)
    ]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(pairs), ""))


def series_url_from(url: str, pattern: re.Pattern[str]) -> str:
    """Transforme une URL d'épisode en URL de série (retire le dernier segment)."""
    parsed = urlparse(url)
    path = parsed.path
    if pattern.search(path):
        parent = path.rstrip("/").rsplit("/", 1)[0]
        path = parent + "/"
    return parsed._replace(path=path, query="", fragment="").geturl()


def _page_title(page: Page) -> str:
    for selector in ('meta[property="og:title"]', "h1", "title"):
        try:
            el = page.query_selector(selector)
            if not el:
                continue
            text = el.get_attribute("content") if selector.startswith("meta") else el.inner_text()
            text = (text or "").strip()
            if text:
                return text
        except Exception:
            continue
    return "serie"


def _collect_links(page: Page) -> list[tuple[str, str]]:
    """Renvoie [(href absolu, texte du lien)] pour tous les <a> de la page."""
    try:
        raw = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(e => [e.href, (e.textContent || '').trim().slice(0, 120)])""",
        )
    except Exception:
        return []
    return [(h, t) for h, t in raw if h]


def collect_episodes(
    page: Page,
    url: str,
    pattern: re.Pattern[str],
    prefer_vf: bool = False,
) -> tuple[str, list[Episode]]:
    """Ouvre la série (ou l'épisode donné) et renvoie (titre, épisodes triés)."""
    target = series_url_from(url, pattern)
    log(f"[scraper] ouverture de la page série : {target}")
    page.goto(target, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1500)

    title = _page_title(page)
    links = _collect_links(page)

    if not any(pattern.search(urlparse(h).path) for h, _ in links):
        # La page série ne liste rien (ou URL d'épisode seule) : on scanne la page fournie.
        if target != url:
            log("[scraper] aucun épisode sur la page série, scan de l'URL fournie...")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1200)
            links += _collect_links(page)
            title = _page_title(page) or title

    found: dict[tuple[int, str], Episode] = {}
    for href, text in links:
        path = urlparse(href).path
        m = pattern.search(path)
        if not m:
            continue
        number = int(m.group(1))
        lang = (m.group(2) or "vostfr").lower()
        clean = clean_href(href)
        found[(number, lang)] = Episode(number, clean, lang, text or clean)

    if not found:
        return title, []

    by_number: dict[int, dict[str, Episode]] = {}
    for (number, lang), ep in found.items():
        by_number.setdefault(number, {})[lang] = ep

    preferred = "vf" if prefer_vf else "vostfr"
    other = "vostfr" if prefer_vf else "vf"

    episodes = [
        by_number[n].get(preferred) or by_number[n].get(other) or next(iter(by_number[n].values()))
        for n in sorted(by_number)
    ]
    log(f"[scraper] {len(episodes)} épisode(s) trouvé(s) — {title}")
    return title, episodes
