"""Diagnostic du player : liste iframes, boutons Play / serveurs, réseau.

Usage :
    python probe.py "https://MON_SITE/anime/serie/serie-01-vostfr/"
    python probe.py "<url>" --headless --wait 30

Produit un résumé console + logs/probe-<date>.json + logs/probe-<date>.png
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from adblock import AdBlocker
from common import ROOT, log, resolve_path
from hls import inspect as inspect_manifest

JS_INVENTORY = r"""() => {
  const out = {play: [], sources: [], buttons: [], videos: []};
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const desc = (el, i) => {
    const r = el.getBoundingClientRect();
    return {
      i,
      tag: el.tagName.toLowerCase(),
      text: (el.textContent || '').trim().slice(0, 60),
      cls: String(el.className || '').slice(0, 100),
      id: el.id || '',
      aria: el.getAttribute('aria-label') || '',
      title: el.getAttribute('title') || '',
      href: el.getAttribute('href') || '',
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    };
  };

  for (const v of document.querySelectorAll('video')) {
    const r = v.getBoundingClientRect();
    out.videos.push({
      cls: String(v.className || '').slice(0, 80),
      src: (v.currentSrc || v.src || '').slice(0, 120),
      paused: v.paused, readyState: v.readyState,
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    });
  }

  const all = [...document.querySelectorAll('button,[role=button],a,div,span,i,svg,li')]
    .filter(visible);

  let pi = 0, si = 0, bi = 0;
  for (const el of all) {
    const d = desc(el, 0);
    const sig = [d.cls, d.id, d.aria, d.title, d.text].join(' ');
    const isPlay = /(play|lecteur|regarder|launch)/i.test(sig) && d.box[2] < 800 && d.box[3] < 600;
    const isSource = /(serveur|server|source|lecteur|player|h[ée]bergeur|mirror|episode)/i.test(sig)
                     && d.text.length > 0 && d.text.length < 60;
    if (isPlay) { d.i = pi++; el.setAttribute('data-adl-p', String(d.i)); out.play.push(d); }
    if (isSource) { d.i = si++; el.setAttribute('data-adl-s', String(d.i)); out.sources.push(d); }
    if ((el.tagName === 'BUTTON' || el.tagName === 'A') && d.text) {
      d.i = bi++; out.buttons.push(d);
      if (out.buttons.length > 80) out.buttons.pop();
    }
  }
  return out;
}"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnostic du player HLS")
    p.add_argument("url")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--wait", type=int, default=25, help="secondes d'écoute réseau après clic")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    seen: list[str] = []
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(resolve_path(".browser-profile")),
            headless=args.headless,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        blocker = AdBlocker(ctx, {"ad_hosts": []})
        blocker.install(lambda p: p is page)
        page.on("request", lambda r: seen.append(r.url) if not re.search(r"\.(png|jpg|jpeg|gif|svg|css|woff2?|ico)(\?|$)", r.url) else None)

        log(f"[probe] navigation -> {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)

        frames = list(page.frames)
        inventory = {}
        for frame in frames:
            try:
                inventory[frame.url] = frame.evaluate(JS_INVENTORY)
            except Exception as exc:
                inventory[frame.url] = {"error": str(exc)}

        log("\n=== IFRAMES ===")
        for f in frames:
            log(f"  - {f.url[:140]}")

        log("\n=== VIDÉOS ===")
        any_video = False
        for url, inv in inventory.items():
            for v in inv.get("videos", []) or []:
                any_video = True
                log(f"  [{url[:60]}] <video> {v['box']} paused={v['paused']} ready={v['readyState']} src={v['src'][:80]}")
        if not any_video:
            log("  aucune balise <video> détectée")

        log("\n=== CANDIDATS PLAY ===")
        for url, inv in inventory.items():
            for c in (inv.get("play") or [])[:10]:
                log(f"  [{url[:40]}] <{c['tag']}> \"{c['text'][:40]}\" cls={c['cls'][:50]} aria={c['aria'][:30]} box={c['box']}")

        log("\n=== CANDIDATS SERVEURS ===")
        for url, inv in inventory.items():
            for c in (inv.get("sources") or [])[:20]:
                log(f"  [{url[:40]}] <{c['tag']}> \"{c['text'][:40]}\" cls={c['cls'][:40]} box={c['box']}")

        # Essaie chaque candidat Play jusqu'à voir un .m3u8
        found = None
        log("\n=== TENTATIVES DE CLIC PLAY ===")
        for frame in frames:
            inv = inventory.get(frame.url) or {}
            for c in (inv.get("play") or [])[:8]:
                try:
                    el = frame.query_selector(f"[data-adl-p='{c['i']}']")
                    if not el or not el.is_visible():
                        continue
                    el.click(timeout=1500, force=True)
                    log(f"  clic <{c['tag']}> \"{c['text'][:30]}\" cls={c['cls'][:40]}")
                except Exception as exc:
                    log(f"  clic impossible: {exc}")
                    continue
                page.wait_for_timeout(2000)
                m3u8 = [u for u in seen if "m3u8" in u.lower()]
                if m3u8:
                    found = m3u8[-1]
                    log(f"  >>> MANIFEST DÉTECTÉ : {found}")
                    break
            if found:
                break

        if not found:
            # dernier recours : clic centre de la vidéo puis écoute
            for frame in frames:
                try:
                    v = frame.query_selector("video")
                    if v:
                        b = v.bounding_box()
                        if b and b["width"] > 10:
                            page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
                            log("  clic au centre de la vidéo")
                            page.wait_for_timeout(3000)
                            break
                except Exception:
                    continue
            m3u8 = [u for u in seen if "m3u8" in u.lower()]
            found = m3u8[-1] if m3u8 else None

        page.wait_for_timeout(max(0, args.wait - 8) * 1000)

        all_m3u8 = [u for u in seen if "m3u8" in u.lower()]
        log("\n=== RÉSEAU ===")
        log(f"  requêtes vues : {len(seen)}")
        log(f"  .m3u8 vus : {len(all_m3u8)}")
        for u in all_m3u8[-10:]:
            log(f"   - {u[:150]}")
        if all_m3u8:
            log("\n=== VALIDATION DES MANIFESTS ===")
            headers = {
                "User-Agent": page.evaluate("() => navigator.userAgent"),
                "Referer": page.url,
                "Accept": "*/*",
            }
            for u in dict.fromkeys(all_m3u8[-6:]):
                cookies = ctx.cookies([u])
                hdrs = dict(headers)
                if cookies:
                    hdrs["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                info = inspect_manifest(u, hdrs)
                if info:
                    log(f"   ✅ durée={info.duration} vod={info.vod} variante={'oui' if info.variant_url else 'non'}")
                    log(f"      {u[:130]}")
                else:
                    log(f"   ❌ invalide/expiré : {u[:130]}")
        api = [u for u in seen if any(k in u.lower() for k in ("api", "json", "ajax"))][-10:]
        for u in api:
            log(f"   api: {u[:150]}")

        report = logs / f"probe-{stamp}.json"
        report.write_text(
            json.dumps(
                {
                    "url": args.url,
                    "frames": [f.url for f in frames],
                    "inventory": inventory,
                    "m3u8": all_m3u8,
                    "requests": seen[-200:],
                    "found": found,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        shot = logs / f"probe-{stamp}.png"
        try:
            page.screenshot(path=str(shot), full_page=False)
        except Exception:
            pass
        log(f"\n[probe] rapport : {report}")
        log(f"[probe] capture : {shot}")
        log("\nVERDICT : " + ("manifest trouvé ✅" if found else "aucun m3u8 — envoie le rapport JSON"))
        ctx.close()
    return 0 if found else 2


if __name__ == "__main__":
    raise SystemExit(main())
