#!/usr/bin/env python3
"""Emit one read-only LinuxCNC status snapshot as a JSON object."""

from __future__ import annotations

import json
import os


def constant_name(module, value, names):
    for name in names:
        if getattr(module, name, object()) == value:
            return name.removeprefix("STATE_").removeprefix("INTERP_").lower()
    return f"unknown_{value}"


def main() -> None:
    try:
        import linuxcnc
    except Exception as exc:
        print(json.dumps({"version": 1, "linuxcnc": "unavailable", "detail": f"linuxcnc Python module unavailable: {exc}"}))
        return

    try:
        status = linuxcnc.stat()
        status.poll()
    except Exception as exc:
        print(json.dumps({"version": 1, "linuxcnc": "not_running", "detail": str(exc)}))
        return

    task_state = constant_name(
        linuxcnc,
        status.task_state,
        ("STATE_ESTOP", "STATE_ESTOP_RESET", "STATE_ON", "STATE_OFF"),
    )
    interpreter_state = constant_name(
        linuxcnc,
        status.interp_state,
        ("INTERP_IDLE", "INTERP_READING", "INTERP_PAUSED", "INTERP_WAITING"),
    )

    if task_state == "estop":
        state = "estop"
    elif task_state != "on":
        state = "machine_off"
    elif bool(getattr(status, "paused", False)) or bool(getattr(status, "task_paused", False)) or interpreter_state == "paused":
        state = "program_paused"
    elif interpreter_state in {"reading", "waiting"}:
        state = "program_running"
    elif getattr(status, "state", None) == getattr(linuxcnc, "RCS_ERROR", object()):
        state = "error"
    elif interpreter_state == "idle":
        state = "ready"
    else:
        state = "busy"

    file_path = str(getattr(status, "file", "") or "")
    current_line = int(getattr(status, "motion_line", 0) or getattr(status, "current_line", 0) or 0)
    payload = {
        "version": 1,
        "linuxcnc": "running",
        "state": state,
        "task_state": task_state,
        "interpreter_state": interpreter_state,
        "file_path": file_path,
        "filename": os.path.basename(file_path),
        "current_line": current_line,
    }
    print(json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
