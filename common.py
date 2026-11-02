"""Chargement de la config + utilitaires communs."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
USER_PREFS_PATH = ROOT / "user.yaml"

# Console Windows (cp1252) : force UTF-8 pour les accents et flèches des logs
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def log(msg: str) -> None:
    print(msg, flush=True)


def status_line(text: str) -> None:
    """Réécrit une ligne sur place (barre de progression) si la console le permet."""
    if sys.stdout.isatty():
        try:
            width = shutil.get_terminal_size((100, 24)).columns
        except Exception:
            width = 100
        content = text[: max(20, width - 1)]
        sys.stdout.write("\r" + content.ljust(len(content)))
        sys.stdout.flush()
    else:
        log(text)


def end_status() -> None:
    """Termine proprement la ligne de progression en cours."""
    if sys.stdout.isatty():
        try:
            width = shutil.get_terminal_size((100, 24)).columns
        except Exception:
            width = 100
        sys.stdout.write("\r" + " " * max(20, width - 1) + "\r")
        sys.stdout.flush()


def die(msg: str, code: int = 1) -> None:
    print(f"ERREUR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    # Préférences utilisateur (menu) écrasent config.yaml
    if USER_PREFS_PATH.exists():
        try:
            prefs = yaml.safe_load(USER_PREFS_PATH.read_text(encoding="utf-8")) or {}
            if isinstance(prefs, dict):
                cfg.update({k: v for k, v in prefs.items() if v is not None})
        except Exception:
            pass
    cfg.setdefault("base_output", str(ROOT / "downloads"))
    cfg.setdefault("user_data_dir", str(ROOT / ".browser-profile"))
    cfg.setdefault("capture_timeout_s", 35)
    cfg.setdefault("source_buttons", [])
    cfg.setdefault("source_selectors", [])
    cfg.setdefault("play_selectors", ["video"])
    cfg.setdefault("dismiss_selectors", [])
    cfg.setdefault("episode_pattern", r"-(\d+)-(vostfr|vf)/?$")
    cfg.setdefault("prefer_vf", False)
    cfg.setdefault("fragment_concurrency", 4)
    cfg.setdefault("delay_between_episodes_s", 2)
    cfg.setdefault("min_duration_s", 30)
    cfg.setdefault("min_size_mb", 1)
    cfg.setdefault("max_sources", 2)
    cfg.setdefault("min_manifest_duration_s", 60)
    cfg.setdefault("quality", "ask")
    cfg.setdefault("browser", "auto")
    cfg.setdefault("display", "window")
    cfg.setdefault("sources", "")
    cfg.setdefault("allow_unknown_duration", False)
    cfg.setdefault("ad_hosts", [])
    cfg.setdefault("min_free_gb", 1)
    cfg.setdefault("ytdlp", {})
    return cfg


def resolve_path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (ROOT / p).resolve()


def safe_filename(name: str, fallback: str = "video") -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or fallback


BROWSER_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "chrome": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ),
    "msedge": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ),
    "brave": (
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"{LOCALAPPDATA}\BraveSoftware\Brave-Browser\Application\brave.exe",
        "/usr/bin/brave-browser",
        "/opt/brave.com/brave/brave",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ),
}

# Noms recherchés dans le PATH quand les chemins standards ne suffisent pas
BROWSER_ALIASES: dict[str, tuple[str, ...]] = {
    "chrome": ("google-chrome", "google-chrome-stable"),
    "msedge": ("microsoft-edge", "microsoft-edge-stable"),
    "brave": ("brave-browser", "brave"),
}


def installed_browsers() -> list[str]:
    """Navigateurs déjà présents sur la machine (canaux Playwright utilisables)."""
    return [name for name in BROWSER_EXECUTABLES if browser_executable(name)]


def browser_executable(name: str) -> str | None:
    """Chemin d'installation du navigateur, ou None s'il est absent."""
    import os
    import shutil

    for raw in BROWSER_EXECUTABLES.get(name, ()):
        candidate = raw.replace("{LOCALAPPDATA}", os.environ.get("LOCALAPPDATA", ""))
        if candidate and Path(candidate).exists():
            return candidate
    for alias in BROWSER_ALIASES.get(name, ()):
        found = shutil.which(alias)
        if found:
            return found
    return None


def browser_launch_options(name: str) -> dict[str, str]:
    """Paramètres Playwright : canal officiel, ou exécutable pour Brave.

    Playwright ne connaît pas le canal "brave" ; on lance son binaire Chromium.
    """
    if name in ("chrome", "msedge"):
        return {"channel": name}
    if name == "brave":
        exe = browser_executable("brave")
        if exe:
            return {"executable_path": exe}
    return {}


def resolve_browser(preferred: str | None) -> str:
    """'auto' -> premier navigateur installé, sinon chromium embarqué."""
    want = (preferred or "auto").strip().lower()
    if want and want != "auto":
        return want
    available = installed_browsers()
    return available[0] if available else "chromium"


def ffmpeg_exe() -> str:
    """ffmpeg système s'il existe, sinon celui embarqué par imageio-ffmpeg."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        die("ffmpeg introuvable. Installe-le : winget install Gyan.FFmpeg")


def ensure_space(min_free_gb: float, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(target).free / (1024**3)
    if free_gb < min_free_gb:
        die(f"Espace disque insuffisant ({free_gb:.2f} Go libres, {min_free_gb} Go requis).")


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_user_prefs(updates: dict[str, Any]) -> None:
    """Écrit les préférences du menu dans user.yaml (fusion avec l'existant)."""
    current: dict[str, Any] = {}
    if USER_PREFS_PATH.exists():
        try:
            loaded = yaml.safe_load(USER_PREFS_PATH.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}
    current.update(updates)
    USER_PREFS_PATH.write_text(
        "# Préférences AnimeDL (générées par le menu)\n"
        + yaml.safe_dump(current, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
