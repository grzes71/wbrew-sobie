"""Indexed PNG loading, validation, and relative-path helpers (no Qt imports)."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from room_editor.model.glyphs import GLYPH_HEIGHT, GLYPH_WIDTH, IndexedImage


class PngLoadError(Exception):
    """Raised when a PNG file is unreadable or fails ANTIC 4 format requirements."""


class PngMissingError(PngLoadError):
    """Raised when a linked PNG file does not exist on disk."""


def load_png(path: Path) -> IndexedImage:
    """Load and validate an indexed PNG (indexes 0..3, dimensions multiple of 4x8)."""
    if not path.exists():
        raise PngMissingError(f"PNG file does not exist: {path}")
    if not path.is_file():
        raise PngLoadError(f"PNG path is not a file: {path}")

    try:
        with Image.open(path) as img:
            if img.format != "PNG":
                raise PngLoadError(
                    f"File '{path}' is not a valid PNG image (format={img.format!r})."
                )
            if img.mode != "P":
                raise PngLoadError(
                    f"PNG '{path}' must be an indexed (palette, mode 'P') image; got mode {img.mode!r}."
                )
            img.load()
            width, height = img.size
            if width <= 0 or width % GLYPH_WIDTH != 0 or height <= 0 or height % GLYPH_HEIGHT != 0:
                raise PngLoadError(
                    f"PNG '{path}' dimensions {width}x{height} must be positive multiples "
                    f"of {GLYPH_WIDTH}x{GLYPH_HEIGHT} pixels."
                )
            raw_pixels = img.tobytes()
            if raw_pixels:
                max_idx = max(raw_pixels)
                if max_idx > 3:
                    raise PngLoadError(
                        f"PNG '{path}' uses palette index {max_idx}; only indexes 0..3 are allowed."
                    )
            raw_pal = img.getpalette() or []
    except (UnidentifiedImageError, OSError) as exc:
        raise PngLoadError(f"Failed to read PNG '{path}': {exc}") from exc

    file_palette: list[tuple[int, int, int]] = []
    for idx in range(4):
        base = idx * 3
        if base + 2 < len(raw_pal):
            file_palette.append((int(raw_pal[base]), int(raw_pal[base + 1]), int(raw_pal[base + 2])))
        else:
            shade = idx * 85
            file_palette.append((shade, shade, shade))

    return IndexedImage(
        width=width,
        height=height,
        pixels=raw_pixels,
        file_palette=tuple(file_palette),
    )


def to_relative_posix_path(target_path: Path, project_file: Path) -> str:
    """Return target_path relative to project_file's directory with '/' separators."""
    base_dir = project_file.resolve().parent
    resolved_target = target_path.resolve()
    try:
        rel = os.path.relpath(resolved_target, base_dir)
    except ValueError:
        return resolved_target.as_posix()
    return Path(rel).as_posix()


def resolve_image_path(image_path: str, base_dir: Path) -> Path:
    """Resolve a stored image path relative to a project directory."""
    p = Path(image_path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()
