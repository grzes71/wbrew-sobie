"""Atari 8-bit .fnt charset loading and relative-path helpers."""

from __future__ import annotations

import os
from pathlib import Path

from room_editor.model.charset import CHARSET_BYTE_SIZE, CharsetData


class FontLoadError(Exception):
    """Raised when a .fnt file is missing, unreadable, or has invalid size."""


def load_fnt(path: Path) -> CharsetData:
    """Load and validate an Atari 1024-byte .fnt charset file."""
    if not path.exists():
        raise FontLoadError(f"Font file does not exist: {path}")
    if not path.is_file():
        raise FontLoadError(f"Font path is not a file: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FontLoadError(f"Failed to read font file '{path}': {exc}") from exc

    if len(raw) != CHARSET_BYTE_SIZE:
        raise FontLoadError(
            f"Invalid font size for '{path}': expected {CHARSET_BYTE_SIZE} bytes, got {len(raw)}."
        )
    return CharsetData(raw=raw)


def to_relative_posix_path(target_path: Path, project_file: Path) -> str:
    """Return target_path relative to project_file's directory with '/' separators."""
    base_dir = project_file.resolve().parent
    resolved_target = target_path.resolve()
    try:
        rel = os.path.relpath(resolved_target, base_dir)
    except ValueError:
        # Different drive letters on Windows: fall back to POSIX absolute path.
        return resolved_target.as_posix()
    return Path(rel).as_posix()


def resolve_fnt_path(charset_path: str, base_dir: Path) -> Path:
    """Resolve a stored charset path relative to a project directory."""
    p = Path(charset_path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()
