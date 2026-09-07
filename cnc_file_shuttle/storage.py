from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .models import MachineProfile


APP_NAME = "CNC File Shuttle"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "cnc-file-shuttle"


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "profiles.json"

    def load(self) -> list[MachineProfile]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [MachineProfile.from_dict(item) for item in data.get("profiles", [])]
        except (OSError, ValueError, TypeError):
            return []

    def save(self, profiles: list[MachineProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"profiles": [profile.to_dict() for profile in profiles]}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.path)

