"""Blocage des publicités et des fenêtres surgissantes pendant la capture."""
from __future__ import annotations

from typing import Any, Callable

from playwright.sync_api import BrowserContext, Page, Route, Request

from common import log

# Hôtes de régies publicitaires (sous-chaîne, en minuscules)
AD_HOST_HINTS = (
    "doubleclick", "googlesyndication", "googleadservices", "adservice.",
    "popads", "popcash", "propellerads", "propeller", "exoclick", "juicyads",
    "trafficjunky", "adsterra", "clickadu", "hilltopads", "popmyads", "onclck",
    "mgid", "taboola", "outbrain", "revcontent", "adcash", "admaven",
    "monetag", "zergnet", "zedo", "adnxs", "criteo", "pubmatic",
    "rubiconproject", "smartadserver", "adform", "casalemedia", "openx",
    "tsyndicate", "a-ads", "adpushup", "media.net", "bidvertiser",
    "adskeeper", "ad-maven", "push-notifications", "onesignal.com",
)

# Motifs dans l'URL (chemin/requête)
AD_PATH_HINTS = (
    "/ads/", "/ad/", "adserver", "popunder", "popup-ad", "adframe",
    "prebid", "/vast", "adunit", "/advert", "ad_banner", "banner-ad",
    "sponsor", "promo-", "clickunder",
)

# Scripts qui ouvrent des fenêtres : neutralisés dès le chargement
JS_KILL_POPUPS = """
(() => {
  try {
    window.open = function () { return null; };
    const orig = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      const t = (this.getAttribute('target') || '').toLowerCase();
      if (t === '_blank') { return; }
      return orig.apply(this, arguments);
    };
  } catch (e) {}
})();
"""


class AdBlocker:
    def __init__(self, context: BrowserContext, cfg: dict[str, Any]) -> None:
        self.ctx = context
        self.cfg = cfg
        self.own_page: Page | None = None
        self.blocked = 0
        self.closed_popups = 0
        self._extra_hosts = tuple(h.lower() for h in cfg.get("ad_hosts", []))

    def install(self, is_own: Callable[[Page], bool]) -> None:
        self.ctx.route("**/*", self._route)
        self.ctx.on("page", lambda page: self._on_page(page, is_own))
        self.ctx.add_init_script(JS_KILL_POPUPS)
        log("[adblock] protection active (régies + popups)")

    def _is_ad(self, request: Request) -> bool:
        url = request.url.lower()
        if any(h in url for h in AD_HOST_HINTS + self._extra_hosts):
            return True
        path = url.split("?", 1)[0]
        return any(p in path for p in AD_PATH_HINTS)

    def _route(self, route: Route) -> None:
        try:
            if self._is_ad(route.request):
                self.blocked += 1
                route.abort()
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    def _on_page(self, page: Page, is_own: Callable[[Page], bool]) -> None:
        if is_own(page):
            return
        self.closed_popups += 1
        try:
            page.close()
            log("[adblock] popup fermée")
        except Exception:
            pass

    def summary(self) -> str:
        return f"{self.blocked} requête(s) pub bloquée(s), {self.closed_popups} popup(s) fermée(s)"
