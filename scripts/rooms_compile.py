#!/usr/bin/env python3
"""Compile room editor YAML v4 projects and group PNGs into MADS 6502 assembly."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from PIL import Image

# ---------------------------------------------------------------------------
# Engine / hardware constants (SSOT for generated data)
# ---------------------------------------------------------------------------

EXPECTED_YAML_VERSION = 4
ROOM_WIDTH = 40
ROOM_HEIGHT = 24
ROOM_SCREEN_SIZE = ROOM_WIDTH * ROOM_HEIGHT  # 960 bytes
GLYPH_WIDTH = 4
GLYPH_HEIGHT = 8
GLYPH_BYTES = 8
MAX_GLYPHS_PER_GROUP = 127
EMPTY_GLYPH_BYTES = b"\x00" * GLYPH_BYTES

MAX_ROOMS = 255
MAX_OBJECTS = 255
MAX_OBJECT_CELLS = 255
MAX_INSTANCES_PER_ROOM = 255
MAX_STYLES = 256
MAX_TELEPORTS = 255

OBJ_FLAG_NON_BLOCKABLE = 0x01
OBJ_FLAG_COLPF3 = 0x02
ROOM_FLAG_UNIFORM_STYLE = 0x01
INST_Y_REPEAT_MASK = 0x80
INST_Y_COORD_MASK = 0x1F

_POLISH_TRANS = str.maketrans(
    {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ź": "z",
        "ż": "z",
        "Ą": "A",
        "Ć": "C",
        "Ę": "E",
        "Ł": "L",
        "Ń": "N",
        "Ó": "O",
        "Ś": "S",
        "Ź": "Z",
        "Ż": "Z",
    }
)


class RoomCompileError(Exception):
    """Raised when room compilation fails due to validation or I/O errors."""


@dataclass(frozen=True)
class Diagnostic:
    """Validation diagnostic (error or warning)."""

    severity: str  # "error" | "warning"
    code: str
    message: str


@dataclass(frozen=True)
class CompiledPalette:
    name: str
    colbk: int
    colpf0: int
    colpf1: int
    colpf2: int
    colpf3: int


@dataclass
class CompiledGroup:
    index: int
    name: str
    ident_upper: str
    ident_lower: str
    image_rel: str
    image_path: Path
    pixel_mapping: tuple[int, int, int, int]
    width_px: int
    height_px: int
    pixels: bytes
    palettes: list[CompiledPalette]
    glyphs: list[bytes] = field(default_factory=list)  # 1-based glyph bytes, len <= 127
    glyph_sources: list[tuple[int, int]] = field(default_factory=list)
    yaml_glyphs: list[dict[str, Any]] | None = None

    @property
    def width_glyphs(self) -> int:
        return self.width_px // GLYPH_WIDTH

    @property
    def height_glyphs(self) -> int:
        return self.height_px // GLYPH_HEIGHT

    def get_palette(self, name: str) -> CompiledPalette | None:
        for pal in self.palettes:
            if pal.name == name:
                return pal
        return None


@dataclass
class CompiledObject:
    id: int
    name: str
    ident_upper: str
    group: str
    tags: list[str]
    non_blockable: bool
    colpf3: bool
    x: int
    y: int
    w: int
    h: int
    cells: bytes = b""
    has_pixel11: bool = False
    cell_block_name: str = ""

    @property
    def flags(self) -> int:
        val = 0
        if self.non_blockable:
            val |= OBJ_FLAG_NON_BLOCKABLE
        if self.colpf3:
            val |= OBJ_FLAG_COLPF3
        return val


@dataclass(frozen=True)
class CompiledInstance:
    object_id: int
    x: int
    y: int
    repeat_w: int
    repeat_h: int

    @property
    def is_repeat(self) -> bool:
        return self.repeat_w > 1 or self.repeat_h > 1


@dataclass
class CompiledRoom:
    id: int
    name: str
    ident_upper: str
    pos: tuple[int, int]
    row_assignments: list[tuple[str, str]]  # 24 entries: (group, palette)
    raw_placed: list[CompiledInstance]
    ordered_placed: list[CompiledInstance] = field(default_factory=list)
    row_styles: list[int] = field(default_factory=list)
    left_id: int = 0
    right_id: int = 0
    up_id: int = 0
    down_id: int = 0
    rowstyle_uniform: bool = True
    rowstyle_block_name: str = ""
    inst_block_name: str = ""
    repeat_count: int = 0


@dataclass(frozen=True)
class CompiledStyle:
    id: int
    group_name: str
    group_ident_lower: str
    palette: CompiledPalette
    ident_upper: str


@dataclass(frozen=True)
class CompiledTeleport:
    a_room: int
    a_x: int
    a_y: int
    b_room: int
    b_x: int
    b_y: int


@dataclass(frozen=True)
class RoomSizeStats:
    room_id: int
    name: str
    total_instances: int
    non_blockable_count: int
    blockable_count: int
    repeat_entries: int
    rowstyle_bytes: int
    instance_bytes: int
    baseline_instance_bytes: int
    total_bytes: int


@dataclass
class CompileReport:
    source_yaml: Path
    input_hash: str
    charset_count: int
    group_glyph_usage: list[tuple[str, int]]
    style_count: int
    tag_count: int
    tag_plane_count: int
    object_count: int
    object_max_id: int
    object_id_gaps: int
    object_cell_raw_bytes: int
    object_cell_dedup_bytes: int
    room_count: int
    room_max_id: int
    room_id_gaps: int
    teleport_count: int
    id_gap_wasted_bytes: int
    room_stats: list[RoomSizeStats]
    section_bytes: dict[str, int]
    total_bytes: int
    warnings: list[Diagnostic]

    def format_text(self) -> str:
        lines: list[str] = [
            f"Compiled {self.source_yaml.as_posix()} (sha256: {self.input_hash[:16]})",
            f"  Groups/Charsets: {self.charset_count} ("
            + ", ".join(f"{name}={used}/{MAX_GLYPHS_PER_GROUP}" for name, used in self.group_glyph_usage)
            + ")",
            f"  Styles used: {self.style_count} | Objects: {self.object_count} (max_id={self.object_max_id}, gaps={self.object_id_gaps}) | Tags: {self.tag_count} ({self.tag_plane_count} plane(s))",
            f"  Rooms: {self.room_count} (max_id={self.room_max_id}, gaps={self.room_id_gaps}) | Teleports: {self.teleport_count}",
            f"  Object cell data: {self.object_cell_raw_bytes} B raw -> {self.object_cell_dedup_bytes} B dedup (saved {self.object_cell_raw_bytes - self.object_cell_dedup_bytes} B)",
            f"  ID-gap table waste: {self.id_gap_wasted_bytes} B",
            "  Per-room instance + style payload (vs 5-plane baseline & 960 B raw screen):",
        ]
        tot_inst = 0
        tot_base = 0
        tot_rs = 0
        for rs in self.room_stats:
            tot_inst += rs.instance_bytes
            tot_base += rs.baseline_instance_bytes
            tot_rs += rs.rowstyle_bytes
            pct_vs_960 = 100.0 * rs.total_bytes / ROOM_SCREEN_SIZE
            lines.append(
                f"    Room {rs.room_id:3d} ({rs.name}): "
                f"{rs.total_instances} inst (nb={rs.non_blockable_count}, bl={rs.blockable_count}, rep={rs.repeat_entries}) -> "
                f"inst={rs.instance_bytes} B (baseline {rs.baseline_instance_bytes} B), "
                f"rowstyle={rs.rowstyle_bytes} B, total={rs.total_bytes} B ({pct_vs_960:.1f}% of 960 B)"
            )
        lines.append(
            f"    Subtotal room payloads: inst={tot_inst} B (baseline {tot_base} B, saved {tot_base - tot_inst} B), rowstyle={tot_rs} B"
        )
        lines.append("  Output bytes by file:")
        for fname, bcount in self.section_bytes.items():
            lines.append(f"    {fname:16s}: {bcount:5d} B")
        lines.append(f"  Total emitted bytes: {self.total_bytes} B")
        return "\n".join(lines)


@dataclass
class CompileResult:
    files: dict[str, str]
    report: CompileReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sanitize_identifier(name: str, *, upper: bool = True) -> str:
    """Convert a project identifier to an ASCII MADS-safe symbol fragment."""
    text = name.strip().translate(_POLISH_TRANS)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    if not text:
        text = "UNNAMED"
    if text[0].isdigit():
        text = f"_{text}"
    return text.upper() if upper else text.lower()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _req_int(value: Any, label: str, *, min_val: int | None = None, max_val: int | None = None) -> int:
    if not _is_int(value):
        raise RoomCompileError(f"{label} must be an integer, got {type(value).__name__}.")
    if min_val is not None and value < min_val:
        raise RoomCompileError(f"{label} ({value}) must be >= {min_val}.")
    if max_val is not None and value > max_val:
        raise RoomCompileError(f"{label} ({value}) must be <= {max_val}.")
    return int(value)


def _format_bytes(data: Sequence[int] | bytes, per_line: int = 16, indent: str = "    ") -> str:
    if not data:
        return ""
    lines: list[str] = []
    for i in range(0, len(data), per_line):
        chunk = data[i : i + per_line]
        vals = ", ".join(f"${b:02X}" for b in chunk)
        lines.append(f"{indent}.byte {vals}")
    return "\n".join(lines)


def _make_header(title: str, source_name: str, input_hash: str, extra: Sequence[str] = ()) -> list[str]:
    lines = [
        "; ==============================================================================",
        f"; {title} -- GENERATED - DO NOT EDIT",
        f"; Source: {source_name} (sha256: {input_hash})",
        "; Compiler: scripts/rooms_compile.py",
    ]
    for line in extra:
        lines.append(f"; {line}")
    lines.append("; ==============================================================================")
    lines.append("")
    return lines


def _emit_id_table(
    lines: list[str],
    name: str,
    values: Sequence[int | str],
    comment: str | None = None,
    per_line: int = 16,
) -> int:
    """Emit `<name>_base` byte array + `<name> = <name>_base - 1` equate for 1-based X indexing."""
    if comment:
        lines.append(f"; {comment}")
    base_label = f"{name}_base"
    lines.append(base_label)
    if values:
        for i in range(0, len(values), per_line):
            chunk = values[i : i + per_line]
            formatted = [v if isinstance(v, str) else f"${v:02X}" for v in chunk]
            lines.append(f"    .byte {', '.join(formatted)}")
    lines.append(f"{name} = {base_label} - 1")
    lines.append("")
    return len(values)


def _load_indexed_png(path: Path, group_name: str) -> tuple[int, int, bytes, bytes]:
    if not path.exists():
        raise RoomCompileError(f"Object group '{group_name}': PNG file not found: '{path.as_posix()}'.")
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise RoomCompileError(f"Object group '{group_name}': cannot read PNG '{path.as_posix()}': {exc}") from exc

    try:
        with Image.open(path) as img:
            if img.format != "PNG":
                raise RoomCompileError(
                    f"Object group '{group_name}': file '{path.as_posix()}' is not PNG (got {img.format})."
                )
            if img.mode != "P":
                raise RoomCompileError(
                    f"Object group '{group_name}': PNG '{path.as_posix()}' must be indexed (mode 'P'), got '{img.mode}'."
                )
            w, h = img.size
            if w <= 0 or w % GLYPH_WIDTH != 0 or h <= 0 or h % GLYPH_HEIGHT != 0:
                raise RoomCompileError(
                    f"Object group '{group_name}': PNG dimensions {w}x{h} must be positive multiples of {GLYPH_WIDTH}x{GLYPH_HEIGHT}."
                )
            data_fn = getattr(img, "get_flattened_data", img.getdata)
            pixels = bytes(data_fn())
    except RoomCompileError:
        raise
    except Exception as exc:
        raise RoomCompileError(f"Object group '{group_name}': invalid PNG '{path.as_posix()}': {exc}") from exc

    bad_idx = sorted({p for p in pixels if p > 3})
    if bad_idx:
        raise RoomCompileError(
            f"Object group '{group_name}': PNG uses palette index(es) {bad_idx} outside 0..3."
        )
    return w, h, pixels, raw_bytes


def _extract_glyph(
    pixels: bytes,
    width_px: int,
    gx: int,
    gy: int,
    pixel_mapping: tuple[int, int, int, int],
) -> tuple[bytes, bool]:
    out = bytearray(GLYPH_BYTES)
    has_11 = False
    base_y = gy * GLYPH_HEIGHT
    base_x = gx * GLYPH_WIDTH
    for py in range(GLYPH_HEIGHT):
        row_off = (base_y + py) * width_px + base_x
        p0 = pixel_mapping[pixels[row_off]]
        p1 = pixel_mapping[pixels[row_off + 1]]
        p2 = pixel_mapping[pixels[row_off + 2]]
        p3 = pixel_mapping[pixels[row_off + 3]]
        if p0 == 3 or p1 == 3 or p2 == 3 or p3 == 3:
            has_11 = True
        out[py] = (p0 << 6) | (p1 << 4) | (p2 << 2) | p3
    return bytes(out), has_11


# ---------------------------------------------------------------------------
# Dependency inspection & compilation pipeline
# ---------------------------------------------------------------------------


def list_png_dependencies(yaml_path: Path) -> list[Path]:
    """Return PNG file paths referenced by `object_groups` in `yaml_path`."""
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RoomCompileError(f"Cannot read '{yaml_path}': {exc}") from exc
    if not isinstance(raw, Mapping):
        raise RoomCompileError(f"'{yaml_path}' must contain a YAML mapping.")
    deps: list[Path] = []
    seen: set[Path] = set()
    for item in raw.get("object_groups") or []:
        if isinstance(item, Mapping):
            img_rel = str(item.get("image") or "").strip()
            if img_rel:
                p = yaml_path.parent / img_rel
                if p not in seen:
                    seen.add(p)
                    deps.append(p)
    return deps


def _parse_yaml_project(yaml_path: Path) -> tuple[dict[str, Any], bytes]:
    if not yaml_path.exists():
        raise RoomCompileError(f"Input YAML file not found: '{yaml_path.as_posix()}'.")
    try:
        raw_bytes = yaml_path.read_bytes()
        doc = yaml.safe_load(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise RoomCompileError(f"Failed to parse '{yaml_path.as_posix()}': {exc}") from exc

    if not isinstance(doc, dict):
        raise RoomCompileError("YAML root must be a mapping.")

    ver = doc.get("version")
    if not _is_int(ver):
        raise RoomCompileError(f"Missing or invalid project version (expected {EXPECTED_YAML_VERSION}, got {ver!r}).")
    if ver != EXPECTED_YAML_VERSION:
        raise RoomCompileError(
            f"Unsupported project version {ver}; expected version {EXPECTED_YAML_VERSION}."
        )
    return doc, raw_bytes


def compile_project(
    yaml_path: Path,
    *,
    strict: bool = False,
    align_charsets: bool = False,
) -> CompileResult:
    """Parse, validate, optimize, and render MADS assembly sources in memory."""
    doc, yaml_bytes = _parse_yaml_project(yaml_path)
    base_dir = yaml_path.parent
    warnings: list[Diagnostic] = []

    def warn(code: str, msg: str) -> None:
        warnings.append(Diagnostic("warning", code, msg))

    # --- Settings ---
    raw_settings = doc.get("settings")
    if raw_settings is not None:
        if not isinstance(raw_settings, Mapping):
            raise RoomCompileError("'settings' must be a mapping.")
        def_pal = raw_settings.get("default_palette")
        if def_pal is not None:
            if not isinstance(def_pal, Mapping):
                raise RoomCompileError("'settings.default_palette' must be a mapping.")
            for reg in ("colbk", "colpf0", "colpf1", "colpf2", "colpf3"):
                _req_int(def_pal.get(reg, 0), f"settings.default_palette.{reg}", min_val=0, max_val=255)

    # --- Tags ---
    raw_tags = doc.get("tags") or []
    if not isinstance(raw_tags, list):
        raise RoomCompileError("'tags' must be a list.")
    tags: list[str] = []
    tag_to_idx: dict[str, int] = {}
    tag_idents_upper: set[str] = set()
    for t in raw_tags:
        t_str = str(t).strip()
        if not t_str:
            raise RoomCompileError("Tag name cannot be empty.")
        if t_str in tag_to_idx:
            raise RoomCompileError(f"Duplicate tag name '{t_str}'.")
        ident = sanitize_identifier(t_str, upper=True)
        if ident in tag_idents_upper:
            raise RoomCompileError(f"Duplicate sanitized tag identifier 'TAG_{ident}'.")
        tag_idents_upper.add(ident)
        tag_to_idx[t_str] = len(tags)
        tags.append(t_str)

    # --- Object Groups & PNG loading ---
    raw_groups = doc.get("object_groups") or []
    if not isinstance(raw_groups, list):
        raise RoomCompileError("'object_groups' must be a list.")

    hasher = hashlib.sha256()
    hasher.update(yaml_bytes)

    groups: list[CompiledGroup] = []
    groups_by_name: dict[str, CompiledGroup] = {}
    grp_idents_upper: set[str] = set()
    grp_idents_lower: set[str] = set()

    for idx, g in enumerate(raw_groups):
        if not isinstance(g, Mapping):
            raise RoomCompileError(f"object_groups[{idx}] must be a mapping.")
        gname = str(g.get("name") or "").strip()
        if not gname:
            raise RoomCompileError(f"object_groups[{idx}] has empty name.")
        if gname in groups_by_name:
            raise RoomCompileError(f"Duplicate object group name '{gname}'.")
        ident_u = sanitize_identifier(gname, upper=True)
        ident_l = sanitize_identifier(gname, upper=False)
        if ident_u in grp_idents_upper or ident_l in grp_idents_lower:
            raise RoomCompileError(f"Duplicate sanitized group identifier '{ident_u}'.")
        grp_idents_upper.add(ident_u)
        grp_idents_lower.add(ident_l)

        img_rel = str(g.get("image") or "").strip()
        if not img_rel:
            raise RoomCompileError(f"Object group '{gname}' has no PNG image path.")
        img_path = base_dir / img_rel
        w_px, h_px, px_bytes, png_raw = _load_indexed_png(img_path, gname)
        hasher.update(gname.encode("utf-8") + b"\x00" + png_raw)

        raw_map = g.get("pixel_mapping")
        if not isinstance(raw_map, list) or len(raw_map) != 4 or not all(_is_int(v) for v in raw_map):
            raise RoomCompileError(f"Object group '{gname}' pixel_mapping must be a 4-integer list.")
        if sorted(raw_map) != [0, 1, 2, 3]:
            raise RoomCompileError(f"Object group '{gname}' pixel_mapping must be a permutation of [0, 1, 2, 3].")
        mapping = (int(raw_map[0]), int(raw_map[1]), int(raw_map[2]), int(raw_map[3]))

        raw_pals = g.get("palettes")
        if not isinstance(raw_pals, list) or not raw_pals:
            raise RoomCompileError(f"Object group '{gname}' must define at least one palette.")
        palettes: list[CompiledPalette] = []
        pal_names_seen: set[str] = set()
        pal_idents_seen: set[str] = set()
        for p_idx, p_item in enumerate(raw_pals):
            if not isinstance(p_item, Mapping):
                raise RoomCompileError(f"Object group '{gname}' palette[{p_idx}] must be a mapping.")
            pname = str(p_item.get("name") or "").strip()
            if not pname:
                raise RoomCompileError(f"Object group '{gname}' palette[{p_idx}] has empty name.")
            if pname in pal_names_seen:
                raise RoomCompileError(f"Object group '{gname}' has duplicate palette name '{pname}'.")
            p_ident = sanitize_identifier(pname, upper=True)
            if p_ident in pal_idents_seen:
                raise RoomCompileError(
                    f"Object group '{gname}' has colliding sanitized palette identifier '{p_ident}'."
                )
            pal_names_seen.add(pname)
            pal_idents_seen.add(p_ident)
            palettes.append(
                CompiledPalette(
                    name=pname,
                    colbk=_req_int(p_item.get("colbk", 0), f"{gname}.{pname}.colbk", min_val=0, max_val=255),
                    colpf0=_req_int(p_item.get("colpf0", 0), f"{gname}.{pname}.colpf0", min_val=0, max_val=255),
                    colpf1=_req_int(p_item.get("colpf1", 0), f"{gname}.{pname}.colpf1", min_val=0, max_val=255),
                    colpf2=_req_int(p_item.get("colpf2", 0), f"{gname}.{pname}.colpf2", min_val=0, max_val=255),
                    colpf3=_req_int(p_item.get("colpf3", 0), f"{gname}.{pname}.colpf3", min_val=0, max_val=255),
                )
            )

        yaml_glyphs = g.get("glyphs") if isinstance(g.get("glyphs"), list) else None
        grp = CompiledGroup(
            index=idx,
            name=gname,
            ident_upper=ident_u,
            ident_lower=ident_l,
            image_rel=Path(img_rel).as_posix(),
            image_path=img_path,
            pixel_mapping=mapping,
            width_px=w_px,
            height_px=h_px,
            pixels=px_bytes,
            palettes=palettes,
            yaml_glyphs=yaml_glyphs,
        )
        groups.append(grp)
        groups_by_name[gname] = grp

    if len(groups) > 256:
        raise RoomCompileError(f"Too many object groups ({len(groups)}); maximum 256.")

    # --- Objects ---
    raw_objects = doc.get("objects") or []
    if not isinstance(raw_objects, list):
        raise RoomCompileError("'objects' must be a list.")
    if len(raw_objects) > MAX_OBJECTS:
        raise RoomCompileError(f"Too many objects ({len(raw_objects)}); maximum {MAX_OBJECTS}.")

    objects: list[CompiledObject] = []
    objects_by_id: dict[int, CompiledObject] = {}
    obj_names_seen: set[str] = set()
    obj_idents_upper: set[str] = set()

    for idx, o in enumerate(raw_objects):
        if not isinstance(o, Mapping):
            raise RoomCompileError(f"objects[{idx}] must be a mapping.")
        oid = _req_int(o.get("id"), f"objects[{idx}].id", min_val=1, max_val=MAX_OBJECTS)
        if oid in objects_by_id:
            raise RoomCompileError(f"Duplicate object ID {oid}.")
        oname = str(o.get("name") or "").strip()
        if not oname:
            raise RoomCompileError(f"Object ID {oid} has empty name.")
        if oname in obj_names_seen:
            raise RoomCompileError(f"Duplicate object name '{oname}'.")
        ident_u = sanitize_identifier(oname, upper=True)
        if ident_u in obj_idents_upper:
            raise RoomCompileError(f"Duplicate sanitized object identifier 'OBJ_{ident_u}'.")
        obj_names_seen.add(oname)
        obj_idents_upper.add(ident_u)

        ogroup = str(o.get("group") or "").strip()
        grp = groups_by_name.get(ogroup)
        if grp is None:
            raise RoomCompileError(f"Object '{oname}' (ID {oid}) references unknown group '{ogroup}'.")

        raw_otags = o.get("tags") or []
        if not isinstance(raw_otags, list):
            raise RoomCompileError(f"Object '{oname}' tags must be a list.")
        otags: list[str] = []
        for t in raw_otags:
            ts = str(t).strip()
            if ts not in tag_to_idx:
                raise RoomCompileError(f"Object '{oname}' references unknown tag '{ts}'.")
            if ts not in otags:
                otags.append(ts)

        nb = bool(o.get("non-blockable", False))
        pf3 = bool(o.get("colpf3", False))

        reg = o.get("region")
        if not isinstance(reg, Mapping):
            raise RoomCompileError(f"Object '{oname}' missing valid 'region' mapping.")
        rx = _req_int(reg.get("x"), f"object {oname}.region.x", min_val=0)
        ry = _req_int(reg.get("y"), f"object {oname}.region.y", min_val=0)
        rw = _req_int(reg.get("w"), f"object {oname}.region.w", min_val=1, max_val=MAX_OBJECT_CELLS)
        rh = _req_int(reg.get("h"), f"object {oname}.region.h", min_val=1, max_val=MAX_OBJECT_CELLS)
        if rw * rh > MAX_OBJECT_CELLS:
            raise RoomCompileError(
                f"Object '{oname}' (ID {oid}) size {rw}x{rh}={rw * rh} exceeds {MAX_OBJECT_CELLS} cells."
            )
        if rx + rw > grp.width_glyphs or ry + rh > grp.height_glyphs:
            raise RoomCompileError(
                f"Object '{oname}' (ID {oid}) region ({rx},{ry},{rw},{rh}) exceeds PNG glyph bounds "
                f"{grp.width_glyphs}x{grp.height_glyphs} of group '{grp.name}'."
            )

        obj = CompiledObject(
            id=oid,
            name=oname,
            ident_upper=ident_u,
            group=ogroup,
            tags=otags,
            non_blockable=nb,
            colpf3=pf3,
            x=rx,
            y=ry,
            w=rw,
            h=rh,
        )
        objects.append(obj)
        objects_by_id[oid] = obj

    objects.sort(key=lambda obj: obj.id)

    # --- Build deterministic glyph tables per group (ascending object ID, row-major) ---
    for grp in groups:
        grp_objs = [obj for obj in objects if obj.group == grp.name]
        glyph_to_code: dict[bytes, int] = {}
        grp.glyphs = []
        grp.glyph_sources = []

        for obj in grp_objs:
            raw_codes = bytearray()
            any_11 = False
            all_empty = True
            for dy in range(obj.h):
                for dx in range(obj.w):
                    gx = obj.x + dx
                    gy = obj.y + dy
                    gbytes, cell_11 = _extract_glyph(grp.pixels, grp.width_px, gx, gy, grp.pixel_mapping)
                    if gbytes == EMPTY_GLYPH_BYTES:
                        raw_codes.append(0)
                    else:
                        all_empty = False
                        if cell_11:
                            any_11 = True
                        code = glyph_to_code.get(gbytes)
                        if code is None:
                            code = len(grp.glyphs) + 1
                            if code > MAX_GLYPHS_PER_GROUP:
                                raise RoomCompileError(
                                    f"Object group '{grp.name}' exceeds {MAX_GLYPHS_PER_GROUP} unique glyphs "
                                    f"(reached at object '{obj.name}' ID {obj.id})."
                                )
                            glyph_to_code[gbytes] = code
                            grp.glyphs.append(gbytes)
                            grp.glyph_sources.append((gx, gy))
                        raw_codes.append(code + 128 if obj.colpf3 else code)

            if all_empty:
                raise RoomCompileError(
                    f"Object '{obj.name}' (ID {obj.id}) consists solely of empty cells (code 0)."
                )
            obj.cells = bytes(raw_codes)
            obj.has_pixel11 = any_11
            if obj.colpf3 and not any_11:
                warn(
                    "OBJECT_COLPF3_NO_EFFECT",
                    f"Object '{obj.name}' (ID {obj.id}) has colpf3=true but no %11 pixels.",
                )

        if grp.yaml_glyphs is not None:
            expected_entries = [
                {"code": i + 1, "data": gb.hex().upper(), "src": [src[0], src[1]]}
                for i, (gb, src) in enumerate(zip(grp.glyphs, grp.glyph_sources))
            ]
            actual_entries: list[dict[str, Any]] = []
            for entry in grp.yaml_glyphs:
                if isinstance(entry, Mapping):
                    actual_entries.append(
                        {
                            "code": entry.get("code"),
                            "data": str(entry.get("data", "")).upper(),
                            "src": list(entry.get("src") or []),
                        }
                    )
            if actual_entries != expected_entries:
                warn(
                    "GLYPH_TABLE_MISMATCH",
                    f"Group '{grp.name}' YAML glyphs table differs from computed PNG glyphs "
                    f"(computed {len(expected_entries)} glyph(s), stored {len(actual_entries)}).",
                )

    # --- Deduplicate object cell blocks ---
    cell_block_by_bytes: dict[bytes, str] = {}
    cell_blocks: list[tuple[str, bytes]] = []
    raw_cell_bytes = 0
    dedup_cell_bytes = 0
    for obj in objects:
        raw_cell_bytes += len(obj.cells)
        lbl = cell_block_by_bytes.get(obj.cells)
        if lbl is None:
            lbl = f"obj_cells_{len(cell_blocks)}"
            cell_block_by_bytes[obj.cells] = lbl
            cell_blocks.append((lbl, obj.cells))
            dedup_cell_bytes += len(obj.cells)
        obj.cell_block_name = lbl

    # --- Rooms ---
    raw_rooms = doc.get("rooms") or []
    if not isinstance(raw_rooms, list):
        raise RoomCompileError("'rooms' must be a list.")
    if len(raw_rooms) > MAX_ROOMS:
        raise RoomCompileError(f"Too many rooms ({len(raw_rooms)}); maximum {MAX_ROOMS}.")

    rooms: list[CompiledRoom] = []
    rooms_by_id: dict[int, CompiledRoom] = {}
    rooms_by_pos: dict[tuple[int, int], CompiledRoom] = {}
    room_names_seen: set[str] = set()
    room_idents_upper: set[str] = set()

    for idx, r in enumerate(raw_rooms):
        if not isinstance(r, Mapping):
            raise RoomCompileError(f"rooms[{idx}] must be a mapping.")
        rid = _req_int(r.get("id"), f"rooms[{idx}].id", min_val=1, max_val=MAX_ROOMS)
        if rid in rooms_by_id:
            raise RoomCompileError(f"Duplicate room ID {rid}.")
        rname = str(r.get("name") or "").strip()
        if not rname:
            raise RoomCompileError(f"Room ID {rid} has empty name.")
        if rname in room_names_seen:
            raise RoomCompileError(f"Duplicate room name '{rname}'.")
        ident_u = sanitize_identifier(rname, upper=True)
        if ident_u in room_idents_upper:
            raise RoomCompileError(f"Duplicate sanitized room identifier 'ROOM_{ident_u}'.")
        room_names_seen.add(rname)
        room_idents_upper.add(ident_u)

        raw_pos = r.get("pos")
        if not isinstance(raw_pos, list) or len(raw_pos) != 2:
            raise RoomCompileError(f"Room '{rname}' pos must be a 2-element [x, y] list.")
        gx = _req_int(raw_pos[0], f"room {rname}.pos[0]")
        gy = _req_int(raw_pos[1], f"room {rname}.pos[1]")
        if (gx, gy) in rooms_by_pos:
            raise RoomCompileError(f"Room '{rname}' overlaps canvas position ({gx}, {gy}).")

        raw_rows = r.get("row_groups")
        if not isinstance(raw_rows, list) or len(raw_rows) not in (1, ROOM_HEIGHT):
            raise RoomCompileError(
                f"Room '{rname}' row_groups must have length 1 or {ROOM_HEIGHT}."
            )
        parsed_rows: list[tuple[str, str]] = []
        for row_idx, entry in enumerate(raw_rows):
            if isinstance(entry, str):
                rg_name = entry.strip()
                grp = groups_by_name.get(rg_name)
                if grp is None:
                    raise RoomCompileError(
                        f"Room '{rname}' row {row_idx} references unknown object group '{rg_name}'."
                    )
                rp_name = grp.palettes[0].name
            elif isinstance(entry, Mapping):
                rg_name = str(entry.get("group") or "").strip()
                grp = groups_by_name.get(rg_name)
                if grp is None:
                    raise RoomCompileError(
                        f"Room '{rname}' row {row_idx} references unknown object group '{rg_name}'."
                    )
                raw_pname = str(entry.get("palette") or "").strip()
                rp_name = raw_pname if raw_pname else grp.palettes[0].name
                if grp.get_palette(rp_name) is None:
                    raise RoomCompileError(
                        f"Room '{rname}' row {row_idx} references unknown palette '{rp_name}' in group '{rg_name}'."
                    )
            else:
                raise RoomCompileError(f"Room '{rname}' row_groups[{row_idx}] has invalid type.")
            parsed_rows.append((rg_name, rp_name))

        if len(parsed_rows) == 1:
            parsed_rows = parsed_rows * ROOM_HEIGHT

        raw_placed = r.get("placed") or []
        if not isinstance(raw_placed, list):
            raise RoomCompileError(f"Room '{rname}' placed must be a list.")
        if len(raw_placed) > MAX_INSTANCES_PER_ROOM:
            raise RoomCompileError(
                f"Room '{rname}' (ID {rid}) has {len(raw_placed)} instance entries; maximum {MAX_INSTANCES_PER_ROOM}."
            )

        instances: list[CompiledInstance] = []
        blockable_occupied: dict[tuple[int, int], int] = {}
        mismatch_reported: set[int] = set()

        for p_idx, p in enumerate(raw_placed):
            if not isinstance(p, Mapping):
                raise RoomCompileError(f"Room '{rname}' placed[{p_idx}] must be a mapping.")
            oid = _req_int(p.get("object"), f"room {rname}.placed[{p_idx}].object", min_val=1, max_val=MAX_OBJECTS)
            obj = objects_by_id.get(oid)
            if obj is None:
                raise RoomCompileError(f"Room '{rname}' placed[{p_idx}] references unknown object ID {oid}.")
            ix = _req_int(p.get("x"), f"room {rname}.placed[{p_idx}].x", min_val=0, max_val=ROOM_WIDTH - 1)
            iy = _req_int(p.get("y"), f"room {rname}.placed[{p_idx}].y", min_val=0, max_val=ROOM_HEIGHT - 1)

            rep_keys = [k for k in ("repeat-x", "repeat-y", "repeat-xy") if k in p]
            if len(rep_keys) > 1:
                raise RoomCompileError(f"Room '{rname}' placed[{p_idx}] has multiple repeat keys: {rep_keys}.")
            rw, rh = 1, 1
            if "repeat-x" in p:
                rw = _req_int(p["repeat-x"], f"room {rname}.placed[{p_idx}].repeat-x", min_val=1, max_val=ROOM_WIDTH)
            elif "repeat-y" in p:
                rh = _req_int(p["repeat-y"], f"room {rname}.placed[{p_idx}].repeat-y", min_val=1, max_val=ROOM_HEIGHT)
            elif "repeat-xy" in p:
                rxy = p["repeat-xy"]
                if not isinstance(rxy, list) or len(rxy) != 2:
                    raise RoomCompileError(f"Room '{rname}' placed[{p_idx}].repeat-xy must be [w, h].")
                rw = _req_int(rxy[0], f"room {rname}.placed[{p_idx}].repeat-xy[0]", min_val=1, max_val=ROOM_WIDTH)
                rh = _req_int(rxy[1], f"room {rname}.placed[{p_idx}].repeat-xy[1]", min_val=1, max_val=ROOM_HEIGHT)

            span_x = rw * obj.w
            span_y = rh * obj.h
            if ix + span_x > ROOM_WIDTH or iy + span_y > ROOM_HEIGHT:
                raise RoomCompileError(
                    f"Room '{rname}' placed[{p_idx}] (object '{obj.name}' ID {oid}) extends outside "
                    f"{ROOM_WIDTH}x{ROOM_HEIGHT}: x={ix}+{span_x}, y={iy}+{span_y}."
                )

            # Validate blockable overlap & cross-group row mismatch across expanded cells
            for ry_i in range(rh):
                for rx_i in range(rw):
                    bx = ix + rx_i * obj.w
                    by = iy + ry_i * obj.h
                    for dy in range(obj.h):
                        cy = by + dy
                        row_grp_name = parsed_rows[cy][0]
                        for dx in range(obj.w):
                            code = obj.cells[dy * obj.w + dx]
                            if code == 0:
                                continue
                            cx = bx + dx
                            if row_grp_name != obj.group and oid not in mismatch_reported:
                                mismatch_reported.add(oid)
                                warn(
                                    "OBJECT_ROW_GROUP_MISMATCH",
                                    f"Room '{rname}': object '{obj.name}' (group '{obj.group}') used in row {cy} ('{row_grp_name}').",
                                )
                            if not obj.non_blockable:
                                prev_id = blockable_occupied.get((cx, cy))
                                if prev_id is not None:
                                    raise RoomCompileError(
                                        f"Room '{rname}' has blockable overlap at ({cx}, {cy}) between "
                                        f"object ID {prev_id} and object ID {oid}."
                                    )
                                blockable_occupied[(cx, cy)] = oid

            instances.append(CompiledInstance(object_id=oid, x=ix, y=iy, repeat_w=rw, repeat_h=rh))

        # Reorder to exact runtime draw order: non-blockable (preserving z-order), then blockable
        nb_inst = [inst for inst in instances if objects_by_id[inst.object_id].non_blockable]
        bl_inst = [inst for inst in instances if not objects_by_id[inst.object_id].non_blockable]
        ordered = nb_inst + bl_inst

        room = CompiledRoom(
            id=rid,
            name=rname,
            ident_upper=ident_u,
            pos=(gx, gy),
            row_assignments=parsed_rows,
            raw_placed=instances,
            ordered_placed=ordered,
            repeat_count=sum(1 for inst in ordered if inst.is_repeat),
        )
        rooms.append(room)
        rooms_by_id[rid] = room
        rooms_by_pos[(gx, gy)] = room

    rooms.sort(key=lambda r: r.id)

    # --- Neighbours ---
    for room in rooms:
        gx, gy = room.pos
        left_r = rooms_by_pos.get((gx - 1, gy))
        right_r = rooms_by_pos.get((gx + 1, gy))
        up_r = rooms_by_pos.get((gx, gy - 1))
        down_r = rooms_by_pos.get((gx, gy + 1))
        room.left_id = left_r.id if left_r else 0
        room.right_id = right_r.id if right_r else 0
        room.up_id = up_r.id if up_r else 0
        room.down_id = down_r.id if down_r else 0

    # --- Styles: unique (group, palette) pairs actually used by room rows ---
    style_map: dict[tuple[str, str], int] = {}
    styles: list[CompiledStyle] = []
    style_idents_seen: set[str] = set()

    for room in rooms:
        room.row_styles = []
        for gname, pname in room.row_assignments:
            key = (gname, pname)
            sid = style_map.get(key)
            if sid is None:
                sid = len(styles)
                if sid >= MAX_STYLES:
                    raise RoomCompileError(
                        f"Unique (group, palette) styles count exceeds {MAX_STYLES}."
                    )
                grp = groups_by_name[gname]
                pal = grp.get_palette(pname)
                assert pal is not None
                s_ident = f"{grp.ident_upper}_{sanitize_identifier(pal.name, upper=True)}"
                if s_ident in style_idents_seen:
                    raise RoomCompileError(f"Duplicate sanitized style identifier 'STYLE_{s_ident}'.")
                style_idents_seen.add(s_ident)
                style_map[key] = sid
                styles.append(
                    CompiledStyle(
                        id=sid,
                        group_name=grp.name,
                        group_ident_lower=grp.ident_lower,
                        palette=pal,
                        ident_upper=s_ident,
                    )
                )
            room.row_styles.append(sid)

    # --- Deduplicate 24-row style tables ---
    rowstyle_tables: list[tuple[str, tuple[int, ...]]] = []
    rowstyle_by_seq: dict[tuple[int, ...], str] = {}
    for room in rooms:
        seq = tuple(room.row_styles)
        if len(set(seq)) == 1:
            room.rowstyle_uniform = True
            room.rowstyle_block_name = ""
        else:
            room.rowstyle_uniform = False
            lbl = rowstyle_by_seq.get(seq)
            if lbl is None:
                lbl = f"room_rowstyle_tbl_{len(rowstyle_tables)}"
                rowstyle_by_seq[seq] = lbl
                rowstyle_tables.append((lbl, seq))
            room.rowstyle_block_name = lbl

    # --- Deduplicate & serialize room instance blocks ---
    def encode_instance_block(insts: Sequence[CompiledInstance]) -> bytes:
        if not insts:
            return b""
        p_obj = bytearray()
        p_x = bytearray()
        p_yf = bytearray()
        p_rw = bytearray()
        p_rh = bytearray()
        for inst in insts:
            p_obj.append(inst.object_id)
            p_x.append(inst.x)
            yf = inst.y & INST_Y_COORD_MASK
            if inst.is_repeat:
                yf |= INST_Y_REPEAT_MASK
                p_rw.append(inst.repeat_w)
                p_rh.append(inst.repeat_h)
            p_yf.append(yf)
        return bytes(p_obj + p_x + p_yf + p_rw + p_rh)

    inst_blocks: list[tuple[str, bytes]] = []
    inst_block_by_bytes: dict[bytes, str] = {}
    room_stats: list[RoomSizeStats] = []

    for room in rooms:
        payload = encode_instance_block(room.ordered_placed)
        if payload:
            lbl = inst_block_by_bytes.get(payload)
            if lbl is None:
                lbl = f"room_inst_block_{len(inst_blocks)}"
                inst_block_by_bytes[payload] = lbl
                inst_blocks.append((lbl, payload))
            room.inst_block_name = lbl
        else:
            room.inst_block_name = ""

        nb_cnt = sum(1 for inst in room.ordered_placed if objects_by_id[inst.object_id].non_blockable)
        bl_cnt = len(room.ordered_placed) - nb_cnt
        rs_bytes = 0 if room.rowstyle_uniform else ROOM_HEIGHT
        inst_bytes = len(payload)
        base_bytes = len(room.ordered_placed) * 5
        room_stats.append(
            RoomSizeStats(
                room_id=room.id,
                name=room.name,
                total_instances=len(room.ordered_placed),
                non_blockable_count=nb_cnt,
                blockable_count=bl_cnt,
                repeat_entries=room.repeat_count,
                rowstyle_bytes=rs_bytes,
                instance_bytes=inst_bytes,
                baseline_instance_bytes=base_bytes,
                total_bytes=rs_bytes + inst_bytes,
            )
        )

    # --- Teleports ---
    raw_tps = doc.get("teleports") or []
    if not isinstance(raw_tps, list):
        raise RoomCompileError("'teleports' must be a list.")
    if len(raw_tps) > MAX_TELEPORTS:
        raise RoomCompileError(f"Too many teleports ({len(raw_tps)}); maximum {MAX_TELEPORTS}.")

    teleports: list[CompiledTeleport] = []
    for idx, tp in enumerate(raw_tps):
        if not isinstance(tp, Mapping):
            raise RoomCompileError(f"teleports[{idx}] must be a mapping.")
        ep_a = tp.get("a")
        ep_b = tp.get("b")
        if not isinstance(ep_a, Mapping) or not isinstance(ep_b, Mapping):
            raise RoomCompileError(f"teleports[{idx}] must contain 'a' and 'b' mappings.")
        ar = _req_int(ep_a.get("room"), f"teleports[{idx}].a.room", min_val=1, max_val=MAX_ROOMS)
        ax = _req_int(ep_a.get("x"), f"teleports[{idx}].a.x", min_val=0, max_val=ROOM_WIDTH - 1)
        ay = _req_int(ep_a.get("y"), f"teleports[{idx}].a.y", min_val=0, max_val=ROOM_HEIGHT - 1)
        br = _req_int(ep_b.get("room"), f"teleports[{idx}].b.room", min_val=1, max_val=MAX_ROOMS)
        bx = _req_int(ep_b.get("x"), f"teleports[{idx}].b.x", min_val=0, max_val=ROOM_WIDTH - 1)
        by = _req_int(ep_b.get("y"), f"teleports[{idx}].b.y", min_val=0, max_val=ROOM_HEIGHT - 1)
        if ar not in rooms_by_id:
            raise RoomCompileError(f"teleports[{idx}].a references unknown room ID {ar}.")
        if br not in rooms_by_id:
            raise RoomCompileError(f"teleports[{idx}].b references unknown room ID {br}.")
        teleports.append(CompiledTeleport(a_room=ar, a_x=ax, a_y=ay, b_room=br, b_x=bx, b_y=by))

    # --- Start position ---
    raw_start = doc.get("start")
    if not isinstance(raw_start, Mapping):
        raise RoomCompileError("Missing or invalid 'start' position.")
    start_room = _req_int(raw_start.get("room"), "start.room", min_val=1, max_val=MAX_ROOMS)
    if start_room not in rooms_by_id:
        raise RoomCompileError(f"Start position references unknown room ID {start_room}.")
    start_x = _req_int(raw_start.get("x"), "start.x", min_val=0, max_val=ROOM_WIDTH - 1)
    start_y = _req_int(raw_start.get("y"), "start.y", min_val=0, max_val=ROOM_HEIGHT - 1)

    # --- Graph & usage warnings ---
    placed_obj_ids = {inst.object_id for r in rooms for inst in r.raw_placed}
    for obj in objects:
        if obj.id not in placed_obj_ids:
            warn("UNUSED_OBJECT", f"Object '{obj.name}' (ID {obj.id}) is not placed in any room.")

    used_group_names = {obj.group for obj in objects} | {ra[0] for r in rooms for ra in r.row_assignments}
    for grp in groups:
        if grp.name not in used_group_names:
            warn("UNUSED_GROUP", f"Object group '{grp.name}' is unused.")
        for pal in grp.palettes:
            if (grp.name, pal.name) not in style_map:
                warn("UNUSED_PALETTE", f"Palette '{pal.name}' in group '{grp.name}' is not assigned to any room row.")

    # Reachability BFS across adjacency + bidirectional teleports
    adj: dict[int, set[int]] = {r.id: set() for r in rooms}
    for r in rooms:
        for nb_id in (r.left_id, r.right_id, r.up_id, r.down_id):
            if nb_id:
                adj[r.id].add(nb_id)
    for tp in teleports:
        adj[tp.a_room].add(tp.b_room)
        adj[tp.b_room].add(tp.a_room)
    visited = {start_room}
    queue = [start_room]
    while queue:
        cur = queue.pop(0)
        for nxt in sorted(adj.get(cur, ())):
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    for r in rooms:
        if r.id not in visited:
            warn("UNREACHABLE_ROOM", f"Room '{r.name}' (ID {r.id}) is unreachable from start room {start_room}.")

    # Adjacent passage check
    blocking_grids: dict[int, list[list[bool]]] = {}
    for r in rooms:
        grid = [[False] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        for inst in r.raw_placed:
            obj = objects_by_id[inst.object_id]
            if obj.non_blockable:
                continue
            for ry_i in range(inst.repeat_h):
                for rx_i in range(inst.repeat_w):
                    bx = inst.x + rx_i * obj.w
                    by = inst.y + ry_i * obj.h
                    for dy in range(obj.h):
                        for dx in range(obj.w):
                            if obj.cells[dy * obj.w + dx] != 0:
                                grid[by + dy][bx + dx] = True
        blocking_grids[r.id] = grid

    for r in rooms:
        if r.right_id:
            nb = rooms_by_id[r.right_id]
            g1, g2 = blocking_grids[r.id], blocking_grids[nb.id]
            if not any((not g1[y][ROOM_WIDTH - 1]) and (not g2[y][0]) for y in range(ROOM_HEIGHT)):
                warn(
                    "ADJACENT_NO_PASSAGE",
                    f"Rooms '{r.name}' (right) and '{nb.name}' (left) have no common free passage cell.",
                )
        if r.down_id:
            nb = rooms_by_id[r.down_id]
            g1, g2 = blocking_grids[r.id], blocking_grids[nb.id]
            if not any((not g1[ROOM_HEIGHT - 1][x]) and (not g2[0][x]) for x in range(ROOM_WIDTH)):
                warn(
                    "ADJACENT_NO_PASSAGE",
                    f"Rooms '{r.name}' (bottom) and '{nb.name}' (top) have no common free passage cell.",
                )

    if strict and warnings:
        joined = "\n".join(f"  [{w.code}] {w.message}" for w in warnings)
        raise RoomCompileError(f"Strict mode: {len(warnings)} warning(s) treated as errors:\n{joined}")

    # -----------------------------------------------------------------------
    # Generate MADS .asm outputs
    # -----------------------------------------------------------------------
    input_hash = hasher.hexdigest()
    source_label = yaml_path.as_posix()
    obj_max_id = max((o.id for o in objects), default=0)
    room_max_id = max((r.id for r in rooms), default=0)
    tag_plane_count = (len(tags) + 7) // 8

    section_bytes: dict[str, int] = {}
    files: dict[str, str] = {}

    # 1. rooms_defs.asm (equates only, 0 bytes)
    defs_lines = _make_header("ROOMS_DEFS.ASM", source_label, input_hash, ("Equates only (0 emitted bytes).",))
    defs_lines.extend(
        [
            "; --- Grid & Engine Limits ---",
            f"ROOM_WIDTH              = {ROOM_WIDTH}",
            f"ROOM_HEIGHT             = {ROOM_HEIGHT}",
            f"ROOM_SCREEN_SIZE        = {ROOM_SCREEN_SIZE}",
            "",
            "; --- Entity Counts & Max IDs ---",
            f"ROOM_COUNT              = {len(rooms)}",
            f"ROOM_MAX_ID             = {room_max_id}",
            f"OBJ_COUNT               = {len(objects)}",
            f"OBJ_MAX_ID              = {obj_max_id}",
            f"GROUP_COUNT             = {len(groups)}",
            f"STYLE_COUNT             = {len(styles)}",
            f"TAG_COUNT               = {len(tags)}",
            f"TAG_PLANE_COUNT         = {tag_plane_count}",
            f"TELEPORT_COUNT          = {len(teleports)}",
            "",
            "; --- Bit Flags & Masks ---",
            f"OBJ_FLAG_NON_BLOCKABLE  = ${OBJ_FLAG_NON_BLOCKABLE:02X}",
            f"OBJ_FLAG_COLPF3         = ${OBJ_FLAG_COLPF3:02X}",
            f"ROOM_FLAG_UNIFORM_STYLE = ${ROOM_FLAG_UNIFORM_STYLE:02X}",
            f"INST_Y_REPEAT_MASK      = ${INST_Y_REPEAT_MASK:02X}",
            f"INST_Y_COORD_MASK       = ${INST_Y_COORD_MASK:02X}",
            "",
            "; --- Hero Start Position ---",
            f"START_ROOM              = {start_room}",
            f"START_X                 = {start_x}",
            f"START_Y                 = {start_y}",
            "",
        ]
    )
    if groups:
        defs_lines.append("; --- Object Groups ---")
        for grp in groups:
            defs_lines.append(f"GROUP_{grp.ident_upper:<17s} = {grp.index} ; '{grp.name}'")
        defs_lines.append("")
    if styles:
        defs_lines.append("; --- Row Styles (used (group, palette) pairs) ---")
        for st in styles:
            defs_lines.append(
                f"STYLE_{st.ident_upper:<17s} = {st.id} ; ({st.group_name}, {st.palette.name})"
            )
        defs_lines.append("")
    if tags:
        defs_lines.append("; --- Tags (8 bits per obj_tags<P> plane) ---")
        for t in tags:
            t_idx = tag_to_idx[t]
            t_ident = sanitize_identifier(t, upper=True)
            t_plane = t_idx >> 3
            t_mask = 1 << (t_idx & 7)
            defs_lines.append(f"TAG_{t_ident:<19s} = ${t_mask:02X}")
            defs_lines.append(f"TAG_{t_ident}_IDX        = {t_idx}")
            defs_lines.append(f"TAG_{t_ident}_PLANE      = {t_plane}")
        defs_lines.append("")
    if objects:
        defs_lines.append("; --- Object IDs (1..OBJ_MAX_ID) ---")
        for obj in objects:
            defs_lines.append(f"OBJ_{obj.ident_upper:<19s} = {obj.id} ; '{obj.name}'")
        defs_lines.append("")
    if rooms:
        defs_lines.append("; --- Room IDs (1..ROOM_MAX_ID) ---")
        for room in rooms:
            defs_lines.append(f"ROOM_{room.ident_upper:<18s} = {room.id} ; '{room.name}'")
        defs_lines.append("")

    files["rooms_defs.asm"] = "\n".join(defs_lines)
    section_bytes["rooms_defs.asm"] = 0

    # 2. charsets.asm (1024 bytes per group; ANTIC requires 1 KB $0400 alignment)
    cs_lines = _make_header(
        "CHARSETS.ASM",
        source_label,
        input_hash,
        (
            "ANTIC Mode 4 character sets (1024 bytes per object group).",
            "ALIGNMENT: ANTIC CHBASE requires each charset on a 1 KB ($0400) boundary.",
            "Place in a 1 KB-aligned segment (e.g. org $4000) or assemble with -d:ROOMS_ALIGN_CHARSETS=1.",
        ),
    )
    cs_bytes = 0
    for grp in groups:
        if align_charsets:
            cs_lines.append("    .align $400")
        else:
            cs_lines.extend(["    .ifdef ROOMS_ALIGN_CHARSETS", "        .align $400", "    .endif"])
        cs_lines.append(
            f"charset_{grp.ident_lower} ; group '{grp.name}' ({len(grp.glyphs)}/{MAX_GLYPHS_PER_GROUP} glyphs)"
        )
        # Emit all 128 glyphs x 8 bytes = 1024 bytes
        cs_lines.append("    .byte $00, $00, $00, $00, $00, $00, $00, $00 ; glyph $00 (reserved empty)")
        for code in range(1, 128):
            if code <= len(grp.glyphs):
                gb = grp.glyphs[code - 1]
                note = f"glyph ${code:02X}"
            else:
                gb = EMPTY_GLYPH_BYTES
                note = f"glyph ${code:02X} (unused)"
            hex_str = ", ".join(f"${b:02X}" for b in gb)
            cs_lines.append(f"    .byte {hex_str} ; {note}")
        cs_lines.append("")
        cs_bytes += 1024
    files["charsets.asm"] = "\n".join(cs_lines)
    section_bytes["charsets.asm"] = cs_bytes

    # 3. styles.asm (SoA of used (group, palette) pairs)
    st_lines = _make_header(
        "STYLES.ASM",
        source_label,
        input_hash,
        ("SoA table of used row styles (index 0..STYLE_COUNT-1 -> CHBASE + 5 GTIA color registers).",),
    )
    style_fields: list[tuple[str, Sequence[int | str]]] = [
        ("style_chbase", [f">charset_{st.group_ident_lower}" for st in styles]),
        ("style_colbk", [st.palette.colbk for st in styles]),
        ("style_colpf0", [st.palette.colpf0 for st in styles]),
        ("style_colpf1", [st.palette.colpf1 for st in styles]),
        ("style_colpf2", [st.palette.colpf2 for st in styles]),
        ("style_colpf3", [st.palette.colpf3 for st in styles]),
    ]
    st_bytes = 0
    for lbl, seq in style_fields:
        st_lines.append(lbl)
        if seq:
            for i in range(0, len(seq), 16):
                chunk = seq[i : i + 16]
                formatted = [v if isinstance(v, str) else f"${v:02X}" for v in chunk]
                st_lines.append(f"    .byte {', '.join(formatted)}")
            st_bytes += len(seq)
        st_lines.append("")
    files["styles.asm"] = "\n".join(st_lines)
    section_bytes["styles.asm"] = st_bytes

    # 4. objects.asm (ID-indexed SoA + deduplicated w*h cell blocks)
    obj_lines = _make_header(
        "OBJECTS.ASM",
        source_label,
        input_hash,
        (
            "Object metadata SoA (1-based ID indexing via base-1 equates: `lda obj_w,x` with X=id).",
            "Unused ID gaps hold $00. Cell data is row-major with colpf3 non-zero codes pre-offset +$80.",
        ),
    )
    obj_w_arr = [0] * obj_max_id
    obj_h_arr = [0] * obj_max_id
    obj_flags_arr = [0] * obj_max_id
    obj_data_lo_arr: list[int | str] = [0] * obj_max_id
    obj_data_hi_arr: list[int | str] = [0] * obj_max_id
    obj_tag_planes: list[list[int]] = [[0] * obj_max_id for _ in range(tag_plane_count)]

    for obj in objects:
        slot = obj.id - 1
        obj_w_arr[slot] = obj.w
        obj_h_arr[slot] = obj.h
        obj_flags_arr[slot] = obj.flags
        obj_data_lo_arr[slot] = f"<{obj.cell_block_name}"
        obj_data_hi_arr[slot] = f">{obj.cell_block_name}"
        for t in obj.tags:
            t_idx = tag_to_idx[t]
            obj_tag_planes[t_idx >> 3][slot] |= 1 << (t_idx & 7)

    obj_bytes = 0
    obj_bytes += _emit_id_table(obj_lines, "obj_w", obj_w_arr, "Object width in cells (1..40)")
    obj_bytes += _emit_id_table(obj_lines, "obj_h", obj_h_arr, "Object height in cells (1..24)")
    obj_bytes += _emit_id_table(
        obj_lines,
        "obj_flags",
        obj_flags_arr,
        "Object flags (bit 0 = non-blockable, bit 1 = colpf3)",
    )
    for p_idx, plane_vals in enumerate(obj_tag_planes):
        obj_bytes += _emit_id_table(
            obj_lines, f"obj_tags{p_idx}", plane_vals, f"Tag bitmask plane {p_idx}"
        )
    obj_bytes += _emit_id_table(
        obj_lines, "obj_data_lo", obj_data_lo_arr, "Low byte of row-major w*h cell block"
    )
    obj_bytes += _emit_id_table(
        obj_lines, "obj_data_hi", obj_data_hi_arr, "High byte of row-major w*h cell block"
    )

    if cell_blocks:
        obj_lines.append("; --- Deduplicated object cell code matrices (0 = transparent) ---")
        for lbl, cbytes in cell_blocks:
            obj_lines.append(f"{lbl} ; {len(cbytes)} bytes")
            obj_lines.append(_format_bytes(cbytes))
            obj_bytes += len(cbytes)
        obj_lines.append("")

    files["objects.asm"] = "\n".join(obj_lines)
    section_bytes["objects.asm"] = obj_bytes

    # 5. rooms.asm (ID-indexed SoA + deduplicated row styles + compact instance SoA blocks)
    rm_lines = _make_header(
        "ROOMS.ASM",
        source_label,
        input_hash,
        (
            "Room metadata SoA (1-based ID indexing via base-1 equates: `lda room_left,x` with X=room_id).",
            "Row styles: bit 0 of room_flags = uniform single style (id stored directly in room_rowstyle_lo);",
            "otherwise room_rowstyle_lo/hi points to a deduplicated 24-byte style table.",
            "Instance draw blocks: non-blockable (in z-order) then blockable, 5 contiguous SoA planes:",
            "  [obj_id x N][x x N][y_flag x N][rep_w x R][rep_h x R] where bit 7 of y_flag indicates repeat entry.",
        ),
    )
    r_left = [0] * room_max_id
    r_right = [0] * room_max_id
    r_up = [0] * room_max_id
    r_down = [0] * room_max_id
    r_flags = [0] * room_max_id
    r_rs_lo: list[int | str] = [0] * room_max_id
    r_rs_hi: list[int | str] = [0] * room_max_id
    r_inst_cnt = [0] * room_max_id
    r_rep_cnt = [0] * room_max_id
    r_inst_lo: list[int | str] = [0] * room_max_id
    r_inst_hi: list[int | str] = [0] * room_max_id

    for room in rooms:
        slot = room.id - 1
        r_left[slot] = room.left_id
        r_right[slot] = room.right_id
        r_up[slot] = room.up_id
        r_down[slot] = room.down_id
        if room.rowstyle_uniform:
            r_flags[slot] = ROOM_FLAG_UNIFORM_STYLE
            r_rs_lo[slot] = room.row_styles[0]
            r_rs_hi[slot] = 0
        else:
            r_flags[slot] = 0
            r_rs_lo[slot] = f"<{room.rowstyle_block_name}"
            r_rs_hi[slot] = f">{room.rowstyle_block_name}"
        r_inst_cnt[slot] = len(room.ordered_placed)
        r_rep_cnt[slot] = room.repeat_count
        if room.inst_block_name:
            r_inst_lo[slot] = f"<{room.inst_block_name}"
            r_inst_hi[slot] = f">{room.inst_block_name}"
        else:
            r_inst_lo[slot] = 0
            r_inst_hi[slot] = 0

    rm_bytes = 0
    rm_bytes += _emit_id_table(rm_lines, "room_left", r_left, "Left neighbour room ID (0 = none)")
    rm_bytes += _emit_id_table(rm_lines, "room_right", r_right, "Right neighbour room ID (0 = none)")
    rm_bytes += _emit_id_table(rm_lines, "room_up", r_up, "Top neighbour room ID (0 = none)")
    rm_bytes += _emit_id_table(rm_lines, "room_down", r_down, "Bottom neighbour room ID (0 = none)")
    rm_bytes += _emit_id_table(rm_lines, "room_flags", r_flags, "Room flags (bit 0 = uniform row style)")
    rm_bytes += _emit_id_table(
        rm_lines,
        "room_rowstyle_lo",
        r_rs_lo,
        "Uniform style ID (if ROOM_FLAG_UNIFORM_STYLE) or 24-byte style table lo pointer",
    )
    rm_bytes += _emit_id_table(
        rm_lines, "room_rowstyle_hi", r_rs_hi, "0 (if uniform) or 24-byte style table hi pointer"
    )
    rm_bytes += _emit_id_table(
        rm_lines, "room_inst_count", r_inst_cnt, "Total instance entries in draw block (0..255)"
    )
    rm_bytes += _emit_id_table(
        rm_lines, "room_rep_count", r_rep_cnt, "Number of entries with repeat bit ($80 in y_flag)"
    )
    rm_bytes += _emit_id_table(rm_lines, "room_inst_lo", r_inst_lo, "Room instance SoA block lo pointer")
    rm_bytes += _emit_id_table(rm_lines, "room_inst_hi", r_inst_hi, "Room instance SoA block hi pointer")

    if rowstyle_tables:
        rm_lines.append("; --- Deduplicated 24-byte per-row style tables ---")
        for lbl, seq in rowstyle_tables:
            rm_lines.append(f"{lbl} ; 24 rows")
            rm_lines.append(_format_bytes(seq, per_line=12))
            rm_bytes += len(seq)
        rm_lines.append("")

    if inst_blocks:
        rm_lines.append("; --- Deduplicated room instance SoA blocks (NB in z-order, then blockable) ---")
        for lbl, payload in inst_blocks:
            rm_lines.append(f"{lbl} ; {len(payload)} bytes")
            rm_lines.append(_format_bytes(payload))
            rm_bytes += len(payload)
        rm_lines.append("")

    files["rooms.asm"] = "\n".join(rm_lines)
    section_bytes["rooms.asm"] = rm_bytes

    # 6. teleports.asm (0-indexed SoA; labels always present even when empty)
    tp_lines = _make_header(
        "TELEPORTS.ASM",
        source_label,
        input_hash,
        ("Bidirectional teleports SoA (0..TELEPORT_COUNT-1). Check both A->B and B->A endpoints.",),
    )
    tp_fields: list[tuple[str, list[int]]] = [
        ("tp_a_room", [tp.a_room for tp in teleports]),
        ("tp_a_x", [tp.a_x for tp in teleports]),
        ("tp_a_y", [tp.a_y for tp in teleports]),
        ("tp_b_room", [tp.b_room for tp in teleports]),
        ("tp_b_x", [tp.b_x for tp in teleports]),
        ("tp_b_y", [tp.b_y for tp in teleports]),
    ]
    tp_bytes = 0
    for lbl, seq in tp_fields:
        tp_lines.append(lbl)
        if seq:
            tp_lines.append(_format_bytes(seq))
            tp_bytes += len(seq)
        else:
            tp_lines.append("    ; (0 entries)")
    tp_lines.append("")
    files["teleports.asm"] = "\n".join(tp_lines)
    section_bytes["teleports.asm"] = tp_bytes

    # --- Compute ID-gap waste statistics ---
    obj_id_gaps = obj_max_id - len(objects)
    room_id_gaps = room_max_id - len(rooms)
    obj_id_table_count = 5 + tag_plane_count  # w, h, flags, data_lo, data_hi + tag planes
    room_id_table_count = 11  # left, right, up, down, flags, rowstyle_lo/hi, inst_count, rep_count, inst_lo/hi
    id_gap_wasted_bytes = (obj_id_gaps * obj_id_table_count) + (room_id_gaps * room_id_table_count)

    report = CompileReport(
        source_yaml=yaml_path,
        input_hash=input_hash,
        charset_count=len(groups),
        group_glyph_usage=[(g.name, len(g.glyphs)) for g in groups],
        style_count=len(styles),
        tag_count=len(tags),
        tag_plane_count=tag_plane_count,
        object_count=len(objects),
        object_max_id=obj_max_id,
        object_id_gaps=obj_id_gaps,
        object_cell_raw_bytes=raw_cell_bytes,
        object_cell_dedup_bytes=dedup_cell_bytes,
        room_count=len(rooms),
        room_max_id=room_max_id,
        room_id_gaps=room_id_gaps,
        teleport_count=len(teleports),
        id_gap_wasted_bytes=id_gap_wasted_bytes,
        room_stats=room_stats,
        section_bytes=section_bytes,
        total_bytes=sum(section_bytes.values()),
        warnings=warnings,
    )
    return CompileResult(files=files, report=report)


def write_outputs_atomic(files: Mapping[str, str], out_dir: Path) -> None:
    """Write generated assembly files atomically via temp files in `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_paths: list[tuple[Path, Path]] = []
    try:
        for filename, content in files.items():
            dest = out_dir / filename
            fd, tmp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=str(out_dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            tmp_paths.append((Path(tmp_name), dest))

        for tmp_path, dest in tmp_paths:
            os.replace(tmp_path, dest)
    except Exception:
        for tmp_path, _ in tmp_paths:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        raise


def compile_rooms(
    yaml_path: Path,
    *,
    out_dir: Path | None = None,
    strict: bool = False,
    align_charsets: bool = False,
) -> CompileResult:
    """Validate, compile, and optionally atomically write MADS assembly outputs."""
    result = compile_project(yaml_path, strict=strict, align_charsets=align_charsets)
    if out_dir is not None:
        write_outputs_atomic(result.files, out_dir)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile room editor YAML v4 + PNGs into compact MADS 6502 assembly."
    )
    parser.add_argument("input_yaml", type=Path, help="Input rooms YAML project file (version 4).")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("gen"),
        help="Output directory for generated .asm files (default: gen).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings (e.g. cross-group row mismatch, unused items) as errors.",
    )
    parser.add_argument(
        "--align-charsets",
        action="store_true",
        help="Emit unconditional `.align $400` before every charset (default: guarded by .ifdef ROOMS_ALIGN_CHARSETS).",
    )
    parser.add_argument(
        "--list-deps",
        action="store_true",
        help="Print space-separated PNG dependency paths referenced by input_yaml and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.list_deps:
        try:
            deps = list_png_dependencies(args.input_yaml)
        except RoomCompileError as err:
            sys.stderr.write(f"ERROR: {err}\n")
            return 1
        print(" ".join(p.as_posix() for p in deps))
        return 0

    try:
        res = compile_rooms(
            args.input_yaml,
            out_dir=args.out,
            strict=args.strict,
            align_charsets=args.align_charsets,
        )
    except RoomCompileError as err:
        sys.stderr.write(f"ERROR: {err}\n")
        return 1

    for w in res.report.warnings:
        sys.stderr.write(f"WARNING [{w.code}]: {w.message}\n")
    print(res.report.format_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
