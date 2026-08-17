from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .lemon3 import grab_screen

ROOT = Path(__file__).resolve().parent.parent


class RunStore:
    def __init__(self, base: Path | None = None) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = stamp
        self.root = (base or ROOT / "artifacts" / "runs") / stamp
        self.shots = self.root / "screenshots"
        self.root.mkdir(parents=True, exist_ok=True)
        self.shots.mkdir(exist_ok=True)
        self.log_path = self.root / "run.log"
        self.result_path = self.root / "result.xlsx"
        self.checkpoint_path = self.root / "checkpoints.json"
        self._checkpoints: list[dict[str, Any]] = []

    def log(self, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')} | {message}\n"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def copy_excel(self, source: str | Path) -> Path:
        source = Path(source)
        dest = self.root / f"result{source.suffix.lower() or '.xlsx'}"
        if source.suffix.lower() == ".csv":
            dest = self.root / "result.csv"
        shutil.copy2(source, dest)
        self.result_path = dest
        return dest

    def screenshot(self, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)[:60]
        path = self.shots / f"{datetime.now().strftime('%H%M%S')}_{safe}.png"
        grab_screen().save(path)
        return path

    def checkpoint(self, **payload: Any) -> None:
        payload["at"] = datetime.now().isoformat(timespec="seconds")
        self._checkpoints.append(payload)
        self.checkpoint_path.write_text(
            json.dumps(self._checkpoints, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
