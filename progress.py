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

    def mark_done(self, code: str, file: Path, source_index: int) -> None:
        self.data["episodes"][code] = {
            "status": "done",
            "file": str(file),
            "source": source_index + 1,
        }
        self.save()

    def mark_failed(self, code: str, error: str) -> None:
        prev = self.status(code)
        attempts = int(prev.get("attempts", 0)) + 1
        self.data["episodes"][code] = {"status": "failed", "attempts": attempts, "last_error": error[:300]}
        self.save()

    def clear_failed(self) -> None:
        for code in [c for c, v in self.data["episodes"].items() if v.get("status") == "failed"]:
            self.data["episodes"].pop(code, None)
        self.save()

    def save(self) -> None:
        dump_json(self.path, self.data)

    def summary(self) -> str:
        done = sum(1 for v in self.data["episodes"].values() if v.get("status") == "done")
        failed = sum(1 for v in self.data["episodes"].values() if v.get("status") == "failed")
        return f"{done} terminé(s), {failed} en échec"
