from __future__ import annotations

import posixpath
from dataclasses import dataclass
from importlib import resources
from pathlib import PurePosixPath
from typing import Any


ACTIVE_PROGRAM_STATES = {"program_running", "program_paused", "program_waiting"}


@dataclass(slots=True)
class LinuxCncStatus:
    linuxcnc: str
    state: str = "unknown"
    filename: str = ""
    file_path: str = ""
    current_line: int = 0
    task_state: str = "unknown"
    interpreter_state: str = "unknown"
    detail: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LinuxCncStatus":
        return cls(
            linuxcnc=str(payload.get("linuxcnc", "unavailable")),
            state=str(payload.get("state", "unknown")),
            filename=str(payload.get("filename", "") or ""),
            file_path=str(payload.get("file_path", "") or ""),
            current_line=int(payload.get("current_line", 0) or 0),
            task_state=str(payload.get("task_state", "unknown")),
            interpreter_state=str(payload.get("interpreter_state", "unknown")),
            detail=str(payload.get("detail", "") or ""),
        )

    @property
    def display_state(self) -> str:
        if self.linuxcnc == "not_running":
            return "LinuxCNC Not Running"
        if self.linuxcnc != "running":
            return "LinuxCNC Status Unavailable"
        return {
            "estop": "LinuxCNC — E-stop",
            "machine_off": "LinuxCNC — Machine Off",
            "ready": "LinuxCNC — Ready",
            "program_running": "Program Running",
            "program_paused": "Program Paused",
            "program_waiting": "Program Waiting",
            "error": "LinuxCNC — Error",
            "busy": "LinuxCNC — Busy",
        }.get(self.state, "LinuxCNC Running")

    @property
    def display_detail(self) -> str:
        if self.filename:
            return f"{self.filename} — line {self.current_line}" if self.current_line > 0 else self.filename
        return self.detail

    @property
    def program_active(self) -> bool:
        return self.linuxcnc == "running" and self.state in ACTIVE_PROGRAM_STATES

    def is_active_path(self, remote_path: str | PurePosixPath) -> bool:
        if not self.program_active or not self.file_path:
            return False
        loaded = posixpath.normpath(self.file_path)
        destination = posixpath.normpath(str(remote_path))
        return loaded == destination


def status_helper_source() -> bytes:
    return resources.files("cnc_file_shuttle.remote").joinpath("linuxcnc_status_helper.py").read_bytes()

