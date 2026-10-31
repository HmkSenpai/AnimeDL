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

# Console Windows (cp1252) : force UTF-8 pour les accents et flèches des logs
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERREUR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
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
