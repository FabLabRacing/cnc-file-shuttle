from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


OVERWRITE_MODE_LABELS = {
    "ask": "Ask each time",
    "always": "Always overwrite",
    "skip": "Skip existing",
}


def normalize_overwrite_mode(value: str) -> str:
    return value if value in OVERWRITE_MODE_LABELS else "ask"


def overwrite_mode_label(value: str) -> str:
    return OVERWRITE_MODE_LABELS[normalize_overwrite_mode(value)]


def overwrite_mode_value(label: str) -> str:
    return next(
        (value for value, display in OVERWRITE_MODE_LABELS.items() if display == label),
        "ask",
    )


def overwrite_session_for_mode(value: str) -> str | None:
    return {
        "always": "overwrite_all",
        "skip": "skip_all",
    }.get(normalize_overwrite_mode(value))


class QueueStatus(str, Enum):
    PENDING = "Pending"
    COPYING = "Copying"
    DONE = "Done"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass(slots=True)
class MachineProfile:
    name: str
    backend: str = "local"
    root_folder: str = ""
    remote_root: str = ""
    target_subfolder: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    auth_mode: str = "ssh_key"
    key_path: str = ""
    overwrite_mode: str = "ask"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MachineProfile":
        fields = cls.__dataclass_fields__
        values = {key: value for key, value in data.items() if key in fields}
        values["overwrite_mode"] = normalize_overwrite_mode(values.get("overwrite_mode", "ask"))
        return cls(**values)


@dataclass(slots=True)
class QueueItem:
    source: Path
    target_subfolder: str
    status: QueueStatus = QueueStatus.PENDING
    detail: str = ""
    target_display: str = ""

    @property
    def filename(self) -> str:
        return self.source.name

    @property
    def size(self) -> int:
        try:
            return self.source.stat().st_size
        except OSError:
            return 0


def requeue_finished(items: list[QueueItem], target_subfolder: str) -> int:
    count = 0
    for item in items:
        if item.status not in {QueueStatus.DONE, QueueStatus.FAILED, QueueStatus.SKIPPED}:
            continue
        item.status = QueueStatus.PENDING
        item.detail = ""
        item.target_display = ""
        item.target_subfolder = target_subfolder
        count += 1
    return count


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
