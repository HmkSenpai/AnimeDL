"""Test : pilotage des navigateurs déjà installés (aucun téléchargement)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from common import browser_launch_options, installed_browsers, log, resolve_browser

PROFILE = Path(__file__).resolve().parent / ".profile"


def try_channel(pw, channel: str) -> bool:
    kwargs = {
        "headless": False,
        "args": ["--disable-blink-features=AutomationControlled",
                 "--window-position=-32000,-32000", "--start-minimized"],
    }
    if channel != "chromium":
        kwargs.update(browser_launch_options(channel))
    try:
        ctx = pw.chromium.launch_persistent_context(str(PROFILE / channel), **kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("about:blank")
        ctx.close()
        return True
    except Exception as exc:
        log(f"  ❌ {channel} : {type(exc).__name__}: {str(exc)[:120]}")
        return False


def main() -> int:
    found = installed_browsers()
    resolved = resolve_browser("auto")
    log(f"navigateurs installés : {found}")
    log(f"auto -> {resolved}")

    checks: list[tuple[bool, str]] = []
    with sync_playwright() as pw:
        for channel in [c for c in ("chrome", "msedge", "brave") if c in found]:
            ok = try_channel(pw, channel)
            log(("  ✅ " if ok else "  ❌ ") + f"{channel} piloté via canal")
            checks.append((ok, f"{channel} pilotable"))
        # repli : chromium embarqué (peut être absent si setup.ps1 l'a sauté)
        ok = try_channel(pw, "chromium")
        log(("  ✅ " if ok else "  ⚠️  ") + "chromium embarqué disponible")
        if not found:
            checks.append((ok, "chromium disponible en repli"))

    for ok, label in checks:
        log(("  ✅ " if ok else "  ❌ ") + label)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
