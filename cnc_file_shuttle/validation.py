from __future__ import annotations

import re
from pathlib import Path, PurePath


ACCEPTED_EXTENSIONS = {".ngc", ".nc", ".tap", ".cnc", ".gcode", ".txt"}
INVALID_CHARS = re.compile(r'[:*?"<>|\x00-\x1f]')


def filename_warnings(path: Path) -> list[str]:
    warnings: list[str] = []
    name = path.name
    if not name or name in {".", ".."}:
        return ["Filename is empty or invalid."]
    if INVALID_CHARS.search(name):
        warnings.append('Filename contains one of these unsafe characters: : * ? " < > |')
    if not name.isascii():
        warnings.append("Filename contains non-ASCII characters; some CNC systems may reject it.")
    if path.suffix.lower() not in ACCEPTED_EXTENSIONS:
        warnings.append(f"{path.suffix or 'No extension'} is not a usual G-code extension.")
    return warnings


def validate_subfolder(value: str) -> str | None:
    cleaned = value.strip().replace("\\", "/")
    if not cleaned:
        return None
    if cleaned.startswith("/") or re.match(r"^[A-Za-z]:", cleaned):
        return "Target subfolder must be relative to the profile root folder."
    parts = PurePath(cleaned).parts
    if any(part == ".." for part in parts):
        return "Target subfolder cannot contain '..'."
    if INVALID_CHARS.search(cleaned):
        return 'Target subfolder contains one of these unsafe characters: : * ? " < > |'
    return None

