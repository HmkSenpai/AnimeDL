"""État de la file de téléchargements (reprise après interruption)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from common import dump_json, read_json


class Progress:
    def __init__(self, series: str, path: Path) -> None:
        self.series = series
        self.path = path
        self.data: dict[str, Any] = read_json(path, {"serie": series, "episodes": {}})
        self.data.setdefault("episodes", {})

    def status(self, code: str) -> dict[str, Any]:
        return self.data["episodes"].get(code, {})

    def get_quality(self) -> str | None:
        return self.data.get("quality")

    def set_quality(self, quality: str) -> None:
        self.data["quality"] = quality
        self.save()

    def is_done(self, code: str) -> bool:
        return self.status(code).get("status") == "done"

    def mark_done(
        self,
        code: str,
        file: Path,
        source_index: int,
        fingerprint: str = "",
        content_hash: str = "",
    ) -> None:
        entry: dict[str, Any] = {
            "status": "done",
            "file": str(file),
            "source": source_index + 1,
        }
        if fingerprint:
            entry["fingerprint"] = fingerprint
        if content_hash:
            entry["content_hash"] = content_hash
        self.data["episodes"][code] = entry
        self.save()

    def stream_map(self) -> dict[str, str]:
        """Empreinte de flux -> épisode, pour les épisodes déjà terminés.

        Permet de détecter un doublon même quand l'épisode précédent a été
        téléchargé lors d'une exécution antérieure.
        """
        out: dict[str, str] = {}
        for code, entry in self.data["episodes"].items():
            fingerprint = entry.get("fingerprint")
            if entry.get("status") == "done" and fingerprint:
                out[str(fingerprint)] = code
        return out

    def content_map(self) -> dict[str, str]:
        """Empreinte visuelle -> épisode, pour les épisodes déjà terminés."""
        out: dict[str, str] = {}
        for code, entry in self.data["episodes"].items():
            content_hash = entry.get("content_hash")
            if entry.get("status") == "done" and content_hash:
                out[str(content_hash)] = code
        return out

    def mark_failed(self, code: str, error: str) -> None:
        prev = self.status(code)
        attempts = int(prev.get("attempts", 0)) + 1
        self.data["episodes"][code] = {"status": "failed", "attempts": attempts, "last_error": error[:300]}
        self.save()

    def clear_failed(self) -> None:
        for code in [c for c, v in self.data["episodes"].items() if v.get("status") == "failed"]:
            self.data["episodes"].pop(code, None)
        self.save()

    def forget(self, code: str) -> Path | None:
        """Retire un épisode de l'état et renvoie son fichier enregistré (à supprimer)."""
        entry = self.data["episodes"].pop(code, None)
        self.save()
        if entry and entry.get("file"):
            return Path(str(entry["file"]))
        return None

    def save(self) -> None:
        dump_json(self.path, self.data)

    def summary(self) -> str:
        done = sum(1 for v in self.data["episodes"].values() if v.get("status") == "done")
        failed = sum(1 for v in self.data["episodes"].values() if v.get("status") == "failed")
        return f"{done} terminé(s), {failed} en échec"
