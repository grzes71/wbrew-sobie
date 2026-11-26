#!/usr/bin/env python3
"""Compile room editor YAML v5 projects into MADS 6502 assembly."""

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

EXPECTED_YAML_VERSION = 5
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
MAX_OBJECT_FRAMES = 16
MAX_ANIMATION_SPEED = 255
MAX_INSTANCES_PER_ROOM = 255
MAX_STYLES = 256
MAX_TELEPORTS = 255

OBJ_FLAG_NON_BLOCKABLE = 0x01
OBJ_FLAG_COLPF3 = 0x02
OBJ_FLAG_PICKABLE = 0x04
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
    has_image: bool = True
    glyphs: list[bytes] = field(default_factory=list)  # 1-based glyph bytes, len <= 127
    glyph_sources: list[tuple[int, int] | None] = field(default_factory=list)
    glyph_owners: list[tuple[int, tuple[tuple[int, int], ...], tuple[bytes, ...]] | None] = field(
        default_factory=list
    )
    static_glyph_count: int = 0
    dedicated_slot_count: int = 0
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


@dataclass(frozen=True)
class CompiledFrame:
    x: int
    y: int
    w: int
    h: int


@dataclass
class CompiledObject:
    id: int
    name: str
    ident_upper: str
    group: str
    tags: list[str]
    non_blockable: bool
    pickable: bool
    colpf3: bool
    frames: list[CompiledFrame]
    animation_speed: int = 0
    cells: bytes = b""
    has_pixel11: bool = False
    cell_block_name: str = ""
    anim_index: int | None = None  # 0..A-1 if animated with >=1 varying cell, else None
    constant_cell_count: int = 0
    varying_cell_count: int = 0
    dedicated_slot_codes: list[int] = field(default_factory=list)
    dedicated_slot_frames: list[tuple[bytes, ...]] = field(default_factory=list)
    dedicated_slot_cells: list[tuple[tuple[int, int], ...]] = field(default_factory=list)

    @property
    def dedicated_slot_count(self) -> int:
        return len(self.dedicated_slot_codes)

    @property
    def x(self) -> int:
        return self.frames[0].x

    @property
    def y(self) -> int:
        return self.frames[0].y

    @property
    def w(self) -> int:
        return self.frames[0].w

    @property
    def h(self) -> int:
        return self.frames[0].h

    @property
    def is_animated(self) -> bool:
        return len(self.frames) >= 2 and self.animation_speed > 0

    @property
    def flags(self) -> int:
        val = 0
        if self.non_blockable:
            val |= OBJ_FLAG_NON_BLOCKABLE
        if self.colpf3:
            val |= OBJ_FLAG_COLPF3
        if self.pickable:
            val |= OBJ_FLAG_PICKABLE
        return val


@dataclass
class CompiledAnimation:
    index: int
    obj: CompiledObject
    group_ident_lower: str
    speed: int
    frame_count: int
    slot_count: int
    bank_index: int
    use_form2: bool
    flags_byte: int
    scodes_label: str
    data_label: str
    encoded_bytes: int
    naive_bytes: int


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
    anim_indices: list[int] = field(default_factory=list)
    anim_list_label: str = ""
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


@dataclass(frozen=True)
class AnimObjectStats:
    anim_idx: int
    object_id: int
    name: str
    frame_count: int
    constant_cells: int
    varying_cells: int
    slot_count: int
    speed: int
    bank_index: int
    form: str
    encoded_bytes: int
    naive_bytes: int


@dataclass
class CompileReport:
    source_yaml: Path
    input_hash: str
    charset_count: int
    group_glyph_usage: list[tuple[str, int]]
    group_glyph_breakdown: list[tuple[str, int, int, int]]  # (name, total, static, dedicated)
    style_count: int
    tag_count: int
    tag_plane_count: int
    object_count: int
    object_max_id: int
    object_id_gaps: int
    object_cell_raw_bytes: int
    object_cell_dedup_bytes: int
    anim_count: int
    anim_pool_count: int
    anim_pattern_count: int
    anim_pool_bytes: int
    max_room_anims: int
    max_room_anim_slots: int
    max_room_form1_slots: int
    anim_stats: list[AnimObjectStats]
    anim_frame_raw_bytes: int
    anim_frame_dedup_bytes: int
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
            f"Compiled {self.source_yaml.as_posix()} (sha256: {self.input_hash[:16]}) [PAL 50 Hz]",
            f"  Groups/Charsets: {self.charset_count} ("
            + ", ".join(
                f"{name}={used}/{MAX_GLYPHS_PER_GROUP} (static={st}, dedicated={ded})"
                for name, used, st, ded in self.group_glyph_breakdown
            )
            + ")",
            f"  Styles used: {self.style_count} | Objects: {self.object_count} (max_id={self.object_max_id}, gaps={self.object_id_gaps}) | Tags: {self.tag_count} ({self.tag_plane_count} plane(s))",
            (
                f"  Animated objects: {self.anim_count} (max/room={self.max_room_anims}, "
                f"max slots/room={self.max_room_anim_slots}, form1 slots/room={self.max_room_form1_slots})"
            ),
            (
                f"  Animation pattern pool: {self.anim_pattern_count} pattern(s) across {self.anim_pool_count} bank(s) "
                f"({self.anim_pool_bytes} B)"
            ),
            f"  Rooms: {self.room_count} (max_id={self.room_max_id}, gaps={self.room_id_gaps}) | Teleports: {self.teleport_count}",
            f"  Object cell data: {self.object_cell_raw_bytes} B raw -> {self.object_cell_dedup_bytes} B dedup (saved {self.object_cell_raw_bytes - self.object_cell_dedup_bytes} B)",
            (
                f"  Animation data: {self.anim_frame_raw_bytes} B naive (8*slots*frames) -> "
                f"{self.anim_frame_dedup_bytes} B encoded (saved {self.anim_frame_raw_bytes - self.anim_frame_dedup_bytes} B)"
            ),
            f"  ID-gap table waste: {self.id_gap_wasted_bytes} B",
        ]
        if self.anim_stats:
            lines.append("  Animated objects breakdown:")
            for ast_item in self.anim_stats:
                saved_obj = ast_item.naive_bytes - ast_item.encoded_bytes
                lines.append(
                    f"    Anim #{ast_item.anim_idx} (obj #{ast_item.object_id} '{ast_item.name}'): "
                    f"const={ast_item.constant_cells}, vary={ast_item.varying_cells}, slots={ast_item.slot_count}, "
                    f"{ast_item.frame_count} frames @ speed={ast_item.speed}, bank={ast_item.bank_index}, "
                    f"form={ast_item.form}: {ast_item.encoded_bytes} B (naive {ast_item.naive_bytes} B, saved {saved_obj} B)"
                )
        lines.append("  Per-room instance + style payload (vs 5-plane baseline & 960 B raw screen):")
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
        img_path = (base_dir / img_rel) if img_rel else Path()
        if img_rel and img_path.exists():
            w_px, h_px, px_bytes, png_raw = _load_indexed_png(img_path, gname)
            hasher.update(gname.encode("utf-8") + b"\x00" + png_raw)
            has_image = True
        else:
            w_px, h_px, px_bytes = 0, 0, b""
            has_image = False

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
            image_rel=Path(img_rel).as_posix() if img_rel else "",
            image_path=img_path,
            pixel_mapping=mapping,
            width_px=w_px,
            height_px=h_px,
            pixels=px_bytes,
            palettes=palettes,
            has_image=has_image,
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
        pick = bool(o.get("pickable", False))
        pf3 = bool(o.get("colpf3", False))
        anim_speed = _req_int(
            o.get("animation_speed", 0),
            f"object '{oname}'.animation_speed",
            min_val=0,
            max_val=MAX_ANIMATION_SPEED,
        )

        raw_frames = o.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise RoomCompileError(
                f"Object '{oname}' (ID {oid}) missing valid non-empty 'frames' list."
            )
        if len(raw_frames) > MAX_OBJECT_FRAMES:
            raise RoomCompileError(
                f"Object '{oname}' (ID {oid}) defines {len(raw_frames)} frames; "
                f"maximum is {MAX_OBJECT_FRAMES}."
            )

        parsed_frames: list[CompiledFrame] = []
        base_wh: tuple[int, int] | None = None
        for f_idx, reg in enumerate(raw_frames):
            if not isinstance(reg, Mapping):
                raise RoomCompileError(
                    f"Object '{oname}' frames[{f_idx}] must be a mapping."
                )
            rx = _req_int(reg.get("x"), f"object {oname}.frames[{f_idx}].x", min_val=0)
            ry = _req_int(reg.get("y"), f"object {oname}.frames[{f_idx}].y", min_val=0)
            rw = _req_int(
                reg.get("w"),
                f"object {oname}.frames[{f_idx}].w",
                min_val=1,
                max_val=MAX_OBJECT_CELLS,
            )
            rh = _req_int(
                reg.get("h"),
                f"object {oname}.frames[{f_idx}].h",
                min_val=1,
                max_val=MAX_OBJECT_CELLS,
            )
            if rw * rh > MAX_OBJECT_CELLS:
                raise RoomCompileError(
                    f"Object '{oname}' (ID {oid}) frame {f_idx} size {rw}x{rh}={rw * rh} "
                    f"exceeds {MAX_OBJECT_CELLS} cells."
                )
            if base_wh is None:
                base_wh = (rw, rh)
            elif (rw, rh) != base_wh:
                raise RoomCompileError(
                    f"Object '{oname}' (ID {oid}) frame {f_idx} size {rw}x{rh} "
                    f"differs from frame 0 size {base_wh[0]}x{base_wh[1]}."
                )
            if grp.has_image and (rx + rw > grp.width_glyphs or ry + rh > grp.height_glyphs):
                raise RoomCompileError(
                    f"Object '{oname}' (ID {oid}) frame {f_idx} ({rx},{ry},{rw},{rh}) "
                    f"exceeds PNG glyph bounds {grp.width_glyphs}x{grp.height_glyphs} of group '{grp.name}'."
                )
            parsed_frames.append(CompiledFrame(x=rx, y=ry, w=rw, h=rh))

        if anim_speed > 0 and len(parsed_frames) == 1:
            warn(
                "ANIM_SPEED_SINGLE_FRAME",
                f"Object '{oname}' (ID {oid}) has animation_speed={anim_speed} with only 1 frame.",
            )
        elif anim_speed == 0 and len(parsed_frames) > 1:
            warn(
                "ANIM_FRAMES_SPEED_ZERO",
                f"Object '{oname}' (ID {oid}) has {len(parsed_frames)} frames with animation_speed=0 (unused).",
            )

        obj = CompiledObject(
            id=oid,
            name=oname,
            ident_upper=ident_u,
            group=ogroup,
            tags=otags,
            non_blockable=nb,
            pickable=pick,
            colpf3=pf3,
            frames=parsed_frames,
            animation_speed=anim_speed,
        )
        objects.append(obj)
        objects_by_id[oid] = obj

    objects.sort(key=lambda obj: obj.id)

    # --- Build deterministic glyph tables per group (ascending object ID, row-major) ---
    def _bytes_have_11(gb: bytes) -> bool:
        for b in gb:
            if (b & 0xC0) == 0xC0 or (b & 0x30) == 0x30 or (b & 0x0C) == 0x0C or (b & 0x03) == 0x03:
                return True
        return False

    for grp in groups:
        grp_objs = [obj for obj in objects if obj.group == grp.name]
        glyph_to_code: dict[bytes, int] = {}
        static_unique_bytes: set[bytes] = set()
        dedicated_slots_total = 0
        grp.glyphs = []
        grp.glyph_sources = []
        grp.glyph_owners = []

        # Pre-index dedicated entries from YAML glyphs (for PNG-optional animated compilation)
        yaml_ded_by_obj: dict[int, list[tuple[int, bytes, tuple[tuple[int, int], ...], tuple[bytes, ...]]]] = {}
        if grp.yaml_glyphs is not None:
            for entry in grp.yaml_glyphs:
                if isinstance(entry, Mapping) and ("object" in entry or "cells" in entry or "frames" in entry):
                    try:
                        d_oid = _req_int(entry.get("object"), f"{grp.name}.glyphs.object", min_val=1)
                        d_code = _req_int(entry.get("code"), f"{grp.name}.glyphs.code", min_val=1, max_val=MAX_GLYPHS_PER_GROUP)
                        cells_raw = entry.get("cells")
                        frames_raw = entry.get("frames")
                        if not isinstance(cells_raw, list) or not cells_raw:
                            raise RoomCompileError(f"Group '{grp.name}' dedicated glyph missing 'cells': {entry!r}")
                        if not isinstance(frames_raw, list) or len(frames_raw) < 2:
                            raise RoomCompileError(f"Group '{grp.name}' dedicated glyph requires >=2 'frames': {entry!r}")
                        d_cells = tuple(
                            (
                                _req_int(c[0], f"{grp.name}.glyphs.cells.x", min_val=0),
                                _req_int(c[1], f"{grp.name}.glyphs.cells.y", min_val=0),
                            )
                            for c in cells_raw
                        )
                        d_frames = tuple(bytes.fromhex(str(fh).strip()) for fh in frames_raw)
                        if any(len(fb) != GLYPH_BYTES for fb in d_frames):
                            raise ValueError("bad frame glyph length")
                        d_bytes = bytes.fromhex(str(entry.get("data", "")).strip())
                        if len(d_bytes) != GLYPH_BYTES or d_bytes != d_frames[0]:
                            raise ValueError("data does not match frames[0]")
                        if len(set(d_frames)) < 2:
                            raise ValueError("dedicated entry does not vary across frames")
                    except RoomCompileError:
                        raise
                    except Exception as exc:
                        raise RoomCompileError(
                            f"Group '{grp.name}' malformed dedicated glyph entry {entry!r}: {exc}"
                        ) from exc
                    yaml_ded_by_obj.setdefault(d_oid, []).append((d_code, d_bytes, d_cells, d_frames))

        for obj in grp_objs:
            if not obj.is_animated:
                if not grp.has_image:
                    raise RoomCompileError(
                        f"Object group '{grp.name}': PNG file required for static object '{obj.name}' (ID {obj.id}), not found: '{grp.image_path.as_posix()}'."
                    )
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
                            static_unique_bytes.add(gbytes)
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
                                grp.glyph_owners.append(None)
                            raw_codes.append(code + 128 if obj.colpf3 else code)

                if all_empty:
                    raise RoomCompileError(
                        f"Object '{obj.name}' (ID {obj.id}) consists solely of empty cells (code 0)."
                    )
                obj.cells = bytes(raw_codes)
                obj.constant_cell_count = obj.w * obj.h
                obj.varying_cell_count = 0
                obj.has_pixel11 = any_11
                if obj.colpf3 and not any_11:
                    warn(
                        "OBJECT_COLPF3_NO_EFFECT",
                        f"Object '{obj.name}' (ID {obj.id}) has colpf3=true but no %11 pixels.",
                    )
            else:
                # Animated object: classify cells (constant -> shared static pool, varying -> shared per-sequence dedicated slots)
                if grp.has_image:
                    cell_seqs: list[list[tuple[bytes, ...]]] = []
                    for dy in range(obj.h):
                        row_seqs: list[tuple[bytes, ...]] = []
                        for dx in range(obj.w):
                            seq = tuple(
                                _extract_glyph(grp.pixels, grp.width_px, fr.x + dx, fr.y + dy, grp.pixel_mapping)[0]
                                for fr in obj.frames
                            )
                            row_seqs.append(seq)
                        cell_seqs.append(row_seqs)
                else:
                    # Reconstruct solely from YAML dedicated entries (allowed for animation-only groups with missing PNG)
                    ded_yaml = yaml_ded_by_obj.get(obj.id)
                    if not ded_yaml:
                        raise RoomCompileError(
                            f"Object group '{grp.name}': PNG '{grp.image_path.as_posix()}' missing and no dedicated YAML glyphs for animated object '{obj.name}' (ID {obj.id})."
                        )
                    cell_seqs = [[(EMPTY_GLYPH_BYTES,) * len(obj.frames) for _ in range(obj.w)] for _ in range(obj.h)]
                    seen_coords: set[tuple[int, int]] = set()
                    for _dcode, _dbytes, dcells, dframes in ded_yaml:
                        if len(dframes) != len(obj.frames):
                            raise RoomCompileError(
                                f"Group '{grp.name}' dedicated glyph for object {obj.id} has {len(dframes)} frames, expected {len(obj.frames)}."
                            )
                        for cx, cy in dcells:
                            if not (0 <= cx < obj.w and 0 <= cy < obj.h):
                                raise RoomCompileError(
                                    f"Group '{grp.name}' dedicated glyph cell ({cx}, {cy}) outside {obj.w}x{obj.h} of object {obj.id}."
                                )
                            if (cx, cy) in seen_coords:
                                raise RoomCompileError(
                                    f"Group '{grp.name}' duplicate dedicated cell ({cx}, {cy}) on object {obj.id}."
                                )
                            seen_coords.add((cx, cy))
                            cell_seqs[cy][cx] = dframes

                seq_cells: dict[tuple[bytes, ...], list[tuple[int, int]]] = {}
                cell_is_varying: list[list[bool]] = []
                const_cnt = 0
                vary_cnt = 0
                has_non_empty = False
                has_11 = False

                for dy in range(obj.h):
                    row_v: list[bool] = []
                    for dx in range(obj.w):
                        seq = cell_seqs[dy][dx]
                        for gb in seq:
                            if gb != EMPTY_GLYPH_BYTES:
                                has_non_empty = True
                                if _bytes_have_11(gb):
                                    has_11 = True
                        if len(set(seq)) == 1:
                            row_v.append(False)
                            const_cnt += 1
                        else:
                            row_v.append(True)
                            vary_cnt += 1
                            seq_cells.setdefault(seq, []).append((dx, dy))
                    cell_is_varying.append(row_v)

                if not has_non_empty:
                    raise RoomCompileError(
                        f"Object '{obj.name}' (ID {obj.id}) consists solely of empty cells in all frames."
                    )

                obj.constant_cell_count = const_cnt
                obj.varying_cell_count = vary_cnt

                seq_to_code: dict[tuple[bytes, ...], int] = {}
                raw_codes_grid = [[0] * obj.w for _ in range(obj.h)]
                slot_codes: list[int] = []
                slot_frames: list[tuple[bytes, ...]] = []
                slot_cells: list[tuple[tuple[int, int], ...]] = []

                for dy in range(obj.h):
                    for dx in range(obj.w):
                        seq = cell_seqs[dy][dx]
                        if not cell_is_varying[dy][dx]:
                            gb = seq[0]
                            if gb == EMPTY_GLYPH_BYTES:
                                continue
                            static_unique_bytes.add(gb)
                            code = glyph_to_code.get(gb)
                            if code is None:
                                code = len(grp.glyphs) + 1
                                if code > MAX_GLYPHS_PER_GROUP:
                                    raise RoomCompileError(
                                        f"Object group '{grp.name}' exceeds {MAX_GLYPHS_PER_GROUP} unique glyphs "
                                        f"(reached at object '{obj.name}' ID {obj.id})."
                                    )
                                glyph_to_code[gb] = code
                                grp.glyphs.append(gb)
                                grp.glyph_sources.append((obj.x + dx, obj.y + dy))
                                grp.glyph_owners.append(None)
                            raw_codes_grid[dy][dx] = code + 128 if obj.colpf3 else code
                        else:
                            code = seq_to_code.get(seq)
                            if code is None:
                                code = len(grp.glyphs) + 1
                                if code > MAX_GLYPHS_PER_GROUP:
                                    raise RoomCompileError(
                                        f"Object group '{grp.name}' exceeds {MAX_GLYPHS_PER_GROUP} glyphs "
                                        f"(reached at animated object '{obj.name}' ID {obj.id})."
                                    )
                                seq_to_code[seq] = code
                                cells_tuple = tuple(seq_cells[seq])
                                grp.glyphs.append(seq[0])
                                grp.glyph_sources.append(None)
                                grp.glyph_owners.append((obj.id, cells_tuple, seq))
                                dedicated_slots_total += 1
                                slot_codes.append(code)
                                slot_frames.append(seq)
                                slot_cells.append(cells_tuple)
                            raw_codes_grid[dy][dx] = code + 128 if obj.colpf3 else code

                obj.dedicated_slot_codes = slot_codes
                obj.dedicated_slot_frames = slot_frames
                obj.dedicated_slot_cells = slot_cells
                obj.cells = bytes(c for row in raw_codes_grid for c in row)
                obj.has_pixel11 = has_11

                if obj.colpf3 and not has_11:
                    warn(
                        "OBJECT_COLPF3_NO_EFFECT",
                        f"Object '{obj.name}' (ID {obj.id}) has colpf3=true but no %11 pixels.",
                    )
                if vary_cnt == 0:
                    warn(
                        "ANIM_NO_VARYING_CELLS",
                        f"Object '{obj.name}' (ID {obj.id}): animated object without any varying cell (all frames identical).",
                    )

        grp.static_glyph_count = len(static_unique_bytes)
        grp.dedicated_slot_count = dedicated_slots_total

        if grp.yaml_glyphs is not None and grp.has_image:
            expected_entries: list[dict[str, Any]] = []
            for i, (gb, src, owner) in enumerate(
                zip(grp.glyphs, grp.glyph_sources, grp.glyph_owners)
            ):
                if owner is not None:
                    oid_own, cells_t, frames_t = owner
                    expected_entries.append(
                        {
                            "kind": "ded",
                            "code": i + 1,
                            "data": gb.hex().upper(),
                            "object": oid_own,
                            "cells": [[cx, cy] for cx, cy in cells_t],
                            "frames": [fb.hex().upper() for fb in frames_t],
                        }
                    )
                else:
                    assert src is not None
                    expected_entries.append(
                        {"kind": "src", "code": i + 1, "data": gb.hex().upper(), "src": [src[0], src[1]]}
                    )
            actual_entries: list[dict[str, Any]] = []
            for entry in grp.yaml_glyphs:
                if isinstance(entry, Mapping):
                    if "object" in entry or "cells" in entry or "frames" in entry:
                        actual_entries.append(
                            {
                                "kind": "ded",
                                "code": entry.get("code"),
                                "data": str(entry.get("data", "")).upper(),
                                "object": entry.get("object"),
                                "cells": [list(c) for c in (entry.get("cells") or [])],
                                "frames": [str(fh).strip().upper() for fh in (entry.get("frames") or [])],
                            }
                        )
                    else:
                        actual_entries.append(
                            {
                                "kind": "src",
                                "code": entry.get("code"),
                                "data": str(entry.get("data", "")).upper(),
                                "src": list(entry.get("src") or []),
                            }
                        )
            if actual_entries != expected_entries:
                warn(
                    "GLYPH_TABLE_MISMATCH",
                    f"Group '{grp.name}' YAML glyphs table differs from computed glyphs "
                    f"(computed {len(expected_entries)} glyph(s), stored {len(actual_entries)}).",
                )

    # --- Assign animated objects, pack 8-byte pattern pools (<=256/bank), choose Form 1 vs Form 2 ---
    MAX_PATTERNS_PER_BANK = 256
    ANIM_FLAG_FORM2 = 0x80
    ANIM_BANK_MASK = 0x7F

    anim_objs = [obj for obj in objects if obj.is_animated and obj.dedicated_slot_count > 0]
    pool_banks: list[list[bytes]] = []
    pool_bank_maps: list[dict[bytes, int]] = []
    obj_bank_idx: dict[int, int] = {}

    for anim_idx, obj in enumerate(anim_objs):
        obj.anim_index = anim_idx
        obj_pats_ordered: list[bytes] = []
        seen_op: set[bytes] = set()
        for f_idx in range(len(obj.frames)):
            for s_idx in range(obj.dedicated_slot_count):
                pb = obj.dedicated_slot_frames[s_idx][f_idx]
                if pb not in seen_op:
                    seen_op.add(pb)
                    obj_pats_ordered.append(pb)

        if len(obj_pats_ordered) > MAX_PATTERNS_PER_BANK:
            raise RoomCompileError(
                f"Animated object '{obj.name}' (ID {obj.id}) uses {len(obj_pats_ordered)} distinct 8-byte patterns, "
                f"exceeding the {MAX_PATTERNS_PER_BANK}-pattern bank limit."
            )

        chosen_bank: int | None = None
        for b_idx, b_map in enumerate(pool_bank_maps):
            added = sum(1 for p in obj_pats_ordered if p not in b_map)
            if len(b_map) + added <= MAX_PATTERNS_PER_BANK:
                chosen_bank = b_idx
                break
        if chosen_bank is None:
            chosen_bank = len(pool_banks)
            pool_banks.append([])
            pool_bank_maps.append({})

        b_list = pool_banks[chosen_bank]
        b_map = pool_bank_maps[chosen_bank]
        for p in obj_pats_ordered:
            if p not in b_map:
                b_map[p] = len(b_list)
                b_list.append(p)
        obj_bank_idx[obj.id] = chosen_bank

    if len(pool_banks) > 128:
        raise RoomCompileError(f"Too many animation pattern banks ({len(pool_banks)}; max 128).")

    scodes_blocks: list[tuple[str, bytes]] = []
    scodes_by_bytes: dict[bytes, str] = {}
    f1_blocks: list[tuple[str, bytes]] = []
    f1_by_bytes: dict[bytes, str] = {}
    delta_blocks: list[tuple[str, bytes]] = []
    delta_by_bytes: dict[bytes, str] = {}
    f2_headers: list[tuple[str, bytes, list[str]]] = []
    f2_by_key: dict[tuple[bytes, tuple[str, ...]], str] = {}

    animations: list[CompiledAnimation] = []
    anim_stats: list[AnimObjectStats] = []
    anim_frame_raw_bytes = 0
    anim_frame_dedup_bytes = 0

    for obj in anim_objs:
        assert obj.anim_index is not None
        grp = groups_by_name[obj.group]
        b_idx = obj_bank_idx[obj.id]
        b_map = pool_bank_maps[b_idx]
        F = len(obj.frames)
        S = obj.dedicated_slot_count

        # Build seq_matrix[f][s] -> 8-bit pattern index in bank b_idx
        seq_matrix = [
            [b_map[obj.dedicated_slot_frames[s][f]] for s in range(S)]
            for f in range(F)
        ]

        scodes_payload = bytes(obj.dedicated_slot_codes)
        sc_lbl = scodes_by_bytes.get(scodes_payload)
        if sc_lbl is None:
            sc_lbl = f"anim_scodes_{len(scodes_blocks)}"
            scodes_by_bytes[scodes_payload] = sc_lbl
            scodes_blocks.append((sc_lbl, scodes_payload))

        # Form 1: frame-major S * F pattern indexes
        f1_payload = bytes(seq_matrix[f][s] for f in range(F) for s in range(S))
        size_f1 = len(f1_payload)

        # Form 2: frame 0 patterns (S) + F delta pointers (2*F) + cyclic delta blocks
        frame_deltas: list[bytes] = []
        for k in range(F):
            prev = (k - 1) % F
            pairs = [
                (s, seq_matrix[k][s])
                for s in range(S)
                if seq_matrix[k][s] != seq_matrix[prev][s]
            ]
            d_bytes = bytes([len(pairs)] + [v for pair in pairs for v in pair])
            frame_deltas.append(d_bytes)
        size_f2 = S + 2 * F + sum(len(d) for d in frame_deltas)

        use_form2 = size_f2 < size_f1  # tie -> Form 1
        naive_bytes = GLYPH_BYTES * S * F
        anim_frame_raw_bytes += naive_bytes

        if use_form2:
            d_labels: list[str] = []
            for d_bytes in frame_deltas:
                dlbl = delta_by_bytes.get(d_bytes)
                if dlbl is None:
                    dlbl = f"anim_d_{len(delta_blocks)}"
                    delta_by_bytes[d_bytes] = dlbl
                    delta_blocks.append((dlbl, d_bytes))
                d_labels.append(dlbl)
            f0_pat_bytes = bytes(seq_matrix[0])
            f2_key = (f0_pat_bytes, tuple(d_labels))
            data_lbl = f2_by_key.get(f2_key)
            if data_lbl is None:
                data_lbl = f"anim_f2_{len(f2_headers)}"
                f2_by_key[f2_key] = data_lbl
                f2_headers.append((data_lbl, f0_pat_bytes, d_labels))
            encoded_bytes = size_f2
        else:
            data_lbl = f1_by_bytes.get(f1_payload)
            if data_lbl is None:
                data_lbl = f"anim_f1_{len(f1_blocks)}"
                f1_by_bytes[f1_payload] = data_lbl
                f1_blocks.append((data_lbl, f1_payload))
            encoded_bytes = size_f1

        anim_frame_dedup_bytes += encoded_bytes
        flags_byte = (ANIM_FLAG_FORM2 if use_form2 else 0) | (b_idx & ANIM_BANK_MASK)
        animations.append(
            CompiledAnimation(
                index=obj.anim_index,
                obj=obj,
                group_ident_lower=grp.ident_lower,
                speed=obj.animation_speed,
                frame_count=F,
                slot_count=S,
                bank_index=b_idx,
                use_form2=use_form2,
                flags_byte=flags_byte,
                scodes_label=sc_lbl,
                data_label=data_lbl,
                encoded_bytes=encoded_bytes,
                naive_bytes=naive_bytes,
            )
        )
        anim_stats.append(
            AnimObjectStats(
                anim_idx=obj.anim_index,
                object_id=obj.id,
                name=obj.name,
                frame_count=F,
                constant_cells=obj.constant_cell_count,
                varying_cells=obj.varying_cell_count,
                slot_count=S,
                speed=obj.animation_speed,
                bank_index=b_idx,
                form="form2" if use_form2 else "form1",
                encoded_bytes=encoded_bytes,
                naive_bytes=naive_bytes,
            )
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
                            if row_grp_name != obj.group:
                                if obj.is_animated:
                                    raise RoomCompileError(
                                        f"Room '{rname}': animated object '{obj.name}' (ID {oid}, group '{obj.group}') "
                                        f"placed in row {cy} assigned to foreign group '{row_grp_name}'."
                                    )
                                if oid not in mismatch_reported:
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
    anim_lists: list[tuple[str, list[int]]] = []
    anim_list_by_seq: dict[tuple[int, ...], str] = {}
    max_room_anims = 0
    max_room_anim_slots = 0
    max_room_form1_slots = 0
    room_stats: list[RoomSizeStats] = []

    for room in rooms:
        room_anim_set: set[int] = set()
        for inst in room.ordered_placed:
            a_idx = objects_by_id[inst.object_id].anim_index
            if a_idx is not None:
                room_anim_set.add(a_idx)
        room.anim_indices = sorted(room_anim_set)
        if room.anim_indices:
            aseq = tuple(room.anim_indices)
            albl = anim_list_by_seq.get(aseq)
            if albl is None:
                albl = f"room_anim_list_{len(anim_lists)}"
                anim_list_by_seq[aseq] = albl
                anim_lists.append((albl, list(room.anim_indices)))
            room.anim_list_label = albl
            max_room_anims = max(max_room_anims, len(room.anim_indices))
            max_room_anim_slots = max(
                max_room_anim_slots,
                sum(animations[a_idx].slot_count for a_idx in room.anim_indices),
            )
            max_room_form1_slots = max(
                max_room_form1_slots,
                sum(
                    animations[a_idx].slot_count
                    for a_idx in room.anim_indices
                    if not animations[a_idx].use_form2
                ),
            )
        else:
            room.anim_list_label = ""

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
    defs_lines = _make_header(
        "ROOMS_DEFS.ASM",
        source_label,
        input_hash,
        ("Equates only (0 emitted bytes). PAL only (50 Hz VBLANK ticks).",),
    )
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
            f"ANIM_COUNT              = {len(animations)}",
            f"ANIM_POOL_COUNT         = {len(pool_banks)}",
            f"ANIM_PATTERN_COUNT      = {sum(len(b) for b in pool_banks)}",
            f"MAX_ROOM_ANIMS          = {max_room_anims}",
            f"MAX_ROOM_ANIM_SLOTS     = {max_room_anim_slots}",
            f"MAX_ROOM_FORM1_SLOTS    = {max_room_form1_slots}",
            "ANIM_PAL_HZ             = 50",
            "ANIM_FLAG_FORM2         = $80",
            "ANIM_BANK_MASK          = $7F",
            "",
            "; --- Bit Flags & Masks ---",
            f"OBJ_FLAG_NON_BLOCKABLE  = ${OBJ_FLAG_NON_BLOCKABLE:02X}",
            f"OBJ_FLAG_COLPF3         = ${OBJ_FLAG_COLPF3:02X}",
            f"OBJ_FLAG_PICKABLE       = ${OBJ_FLAG_PICKABLE:02X}",
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
    if animations:
        defs_lines.append("; --- Animated Object Indexes (0..ANIM_COUNT-1, PAL 50 Hz) ---")
        for anim in animations:
            defs_lines.append(
                f"ANIM_{anim.obj.ident_upper:<18s} = {anim.index} ; obj #{anim.obj.id} '{anim.obj.name}' "
                f"({anim.frame_count}f x {anim.slot_count}s @ {anim.speed})"
            )
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
            "Dedicated animated object slots contain frame 0 bitmap data at boot.",
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
            f"charset_{grp.ident_lower} ; group '{grp.name}' ({len(grp.glyphs)}/{MAX_GLYPHS_PER_GROUP} glyphs: "
            f"static={grp.static_glyph_count}, dedicated={grp.dedicated_slot_count})"
        )
        # Emit all 128 glyphs x 8 bytes = 1024 bytes
        cs_lines.append("    .byte $00, $00, $00, $00, $00, $00, $00, $00 ; glyph $00 (reserved empty)")
        for code in range(1, 128):
            if code <= len(grp.glyphs):
                gb = grp.glyphs[code - 1]
                owner = grp.glyph_owners[code - 1]
                if owner is not None:
                    note = f"glyph ${code:02X} (dedicated obj #{owner[0]} cell {owner[1]},{owner[2]} frame 0)"
                else:
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
    obj_anim_arr = [0] * obj_max_id
    obj_data_lo_arr: list[int | str] = [0] * obj_max_id
    obj_data_hi_arr: list[int | str] = [0] * obj_max_id
    obj_tag_planes: list[list[int]] = [[0] * obj_max_id for _ in range(tag_plane_count)]

    for obj in objects:
        slot = obj.id - 1
        obj_w_arr[slot] = obj.w
        obj_h_arr[slot] = obj.h
        obj_flags_arr[slot] = obj.flags
        obj_anim_arr[slot] = (obj.anim_index + 1) if obj.anim_index is not None else 0
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
        "Object flags (bit 0 = non-blockable, bit 1 = colpf3, bit 2 = pickable)",
    )
    obj_bytes += _emit_id_table(
        obj_lines,
        "obj_anim",
        obj_anim_arr,
        "Animation index + 1 (0 = static object, 1..ANIM_COUNT = anim_idx + 1)",
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
    r_anim_cnt = [0] * room_max_id
    r_anim_lo: list[int | str] = [0] * room_max_id
    r_anim_hi: list[int | str] = [0] * room_max_id

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
        r_anim_cnt[slot] = len(room.anim_indices)
        if room.anim_list_label:
            r_anim_lo[slot] = f"<{room.anim_list_label}"
            r_anim_hi[slot] = f">{room.anim_list_label}"
        else:
            r_anim_lo[slot] = 0
            r_anim_hi[slot] = 0

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
    rm_bytes += _emit_id_table(
        rm_lines, "room_anim_count", r_anim_cnt, "Unique animated objects in room (0..ANIM_COUNT)"
    )
    rm_bytes += _emit_id_table(rm_lines, "room_anim_lo", r_anim_lo, "Room animated object index list lo pointer")
    rm_bytes += _emit_id_table(rm_lines, "room_anim_hi", r_anim_hi, "Room animated object index list hi pointer")

    if rowstyle_tables:
        rm_lines.append("; --- Deduplicated 24-byte per-row style tables ---")
        for lbl, seq in rowstyle_tables:
            rm_lines.append(f"{lbl} ; 24 rows")
            rm_lines.append(_format_bytes(seq, per_line=12))
            rm_bytes += len(seq)
        rm_lines.append("")

    if anim_lists:
        rm_lines.append("; --- Deduplicated per-room unique animated-object index lists ---")
        for lbl, seq in anim_lists:
            rm_lines.append(f"{lbl} ; {len(seq)} anim(s)")
            rm_lines.append(_format_bytes(seq))
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

    # 7. animations.asm (0-indexed SoA by anim_idx 0..ANIM_COUNT-1; PAL only)
    anim_lines = _make_header(
        "ANIMATIONS.ASM",
        source_label,
        input_hash,
        (
            "Animated object metadata, Form 1/Form 2 animation sequences, and 8-plane pattern pool.",
            "PAL ONLY: anim_speed is measured in PAL VBLANK ticks (1/50 s; 50 = 1.00 s).",
            "Constant cells use the static pool; only varying cells occupy dedicated slots.",
        ),
    )
    anim_fields: list[tuple[str, Sequence[int | str]]] = [
        ("anim_speed", [a.speed for a in animations]),
        ("anim_frames", [a.frame_count for a in animations]),
        ("anim_slots", [a.slot_count for a in animations]),
        ("anim_chbase", [f">charset_{a.group_ident_lower}" for a in animations]),
        ("anim_flags", [a.flags_byte for a in animations]),
        ("anim_scodes_lo", [f"<{a.scodes_label}" for a in animations]),
        ("anim_scodes_hi", [f">{a.scodes_label}" for a in animations]),
        ("anim_data_lo", [f"<{a.data_label}" for a in animations]),
        ("anim_data_hi", [f">{a.data_label}" for a in animations]),
    ]
    anim_bytes = 0
    for lbl, seq in anim_fields:
        anim_lines.append(lbl)
        if seq:
            for i in range(0, len(seq), 16):
                chunk = seq[i : i + 16]
                formatted = [v if isinstance(v, str) else f"${v:02X}" for v in chunk]
                anim_lines.append(f"    .byte {', '.join(formatted)}")
            anim_bytes += len(seq)
        else:
            anim_lines.append("    ; (0 animated objects)")
    anim_lines.append("")

    if scodes_blocks:
        anim_lines.append("; --- Per-object dedicated base glyph code tables (1..127) ---")
        for lbl, payload in scodes_blocks:
            anim_lines.append(f"{lbl} ; {len(payload)} slot(s)")
            anim_lines.append(_format_bytes(payload))
            anim_bytes += len(payload)
        anim_lines.append("")

    if f1_blocks:
        anim_lines.append("; --- Form 1: frame-major sequence tables [frame][slot] -> pat_idx ---")
        for lbl, payload in f1_blocks:
            anim_lines.append(f"{lbl} ; {len(payload)} B")
            anim_lines.append(_format_bytes(payload))
            anim_bytes += len(payload)
        anim_lines.append("")

    if f2_headers:
        anim_lines.append("; --- Form 2: frame 0 patterns (S B) + [<delta_0..F-1][>delta_0..F-1] ---")
        for lbl, f0_pats, d_labels in f2_headers:
            anim_lines.append(f"{lbl} ; {len(f0_pats)} slot(s), {len(d_labels)} frame(s)")
            anim_lines.append(_format_bytes(f0_pats))
            anim_lines.append("    .byte " + ", ".join(f"<{dl}" for dl in d_labels))
            anim_lines.append("    .byte " + ", ".join(f">{dl}" for dl in d_labels))
            anim_bytes += len(f0_pats) + 2 * len(d_labels)
        anim_lines.append("")

    if delta_blocks:
        anim_lines.append("; --- Form 2 delta blocks: [count, slot_0, pat_0, ...] ---")
        for lbl, payload in delta_blocks:
            anim_lines.append(f"{lbl} ; {len(payload)} B ({payload[0]} pair(s))")
            anim_lines.append(_format_bytes(payload))
            anim_bytes += len(payload)
        anim_lines.append("")

    pool_bytes = 0
    if pool_banks:
        anim_lines.append("; --- Deduplicated 8-byte pattern pool (8 byte planes per bank, <=256 pats/bank) ---")
        for b_idx, bank_pats in enumerate(pool_banks):
            anim_lines.append(f"; Pool bank {b_idx}: {len(bank_pats)} pattern(s)")
            for row in range(GLYPH_BYTES):
                anim_lines.append(f"anim_pool{b_idx}_b{row}")
                plane = bytes(p[row] for p in bank_pats)
                anim_lines.append(_format_bytes(plane))
                pool_bytes += len(plane)
                anim_bytes += len(plane)
        if len(pool_banks) > 1:
            anim_lines.append("anim_pb_lo")
            for b_idx in range(len(pool_banks)):
                anim_lines.append("    .byte " + ", ".join(f"<anim_pool{b_idx}_b{row}" for row in range(GLYPH_BYTES)))
                pool_bytes += GLYPH_BYTES
                anim_bytes += GLYPH_BYTES
            anim_lines.append("anim_pb_hi")
            for b_idx in range(len(pool_banks)):
                anim_lines.append("    .byte " + ", ".join(f">anim_pool{b_idx}_b{row}" for row in range(GLYPH_BYTES)))
                pool_bytes += GLYPH_BYTES
                anim_bytes += GLYPH_BYTES
        anim_lines.append("")

    files["animations.asm"] = "\n".join(anim_lines)
    section_bytes["animations.asm"] = anim_bytes

    # --- Compute ID-gap waste statistics ---
    obj_id_gaps = obj_max_id - len(objects)
    room_id_gaps = room_max_id - len(rooms)
    obj_id_table_count = 6 + tag_plane_count  # w, h, flags, anim, data_lo, data_hi + tag planes
    room_id_table_count = 14  # left, right, up, down, flags, rowstyle_lo/hi, inst_cnt, rep_cnt, inst_lo/hi, anim_cnt, anim_lo/hi
    id_gap_wasted_bytes = (obj_id_gaps * obj_id_table_count) + (room_id_gaps * room_id_table_count)

    report = CompileReport(
        source_yaml=yaml_path,
        input_hash=input_hash,
        charset_count=len(groups),
        group_glyph_usage=[(g.name, len(g.glyphs)) for g in groups],
        group_glyph_breakdown=[
            (g.name, len(g.glyphs), g.static_glyph_count, g.dedicated_slot_count)
            for g in groups
        ],
        style_count=len(styles),
        tag_count=len(tags),
        tag_plane_count=tag_plane_count,
        object_count=len(objects),
        object_max_id=obj_max_id,
        object_id_gaps=obj_id_gaps,
        object_cell_raw_bytes=raw_cell_bytes,
        object_cell_dedup_bytes=dedup_cell_bytes,
        anim_count=len(animations),
        anim_pool_count=len(pool_banks),
        anim_pattern_count=sum(len(b) for b in pool_banks),
        anim_pool_bytes=pool_bytes,
        max_room_anims=max_room_anims,
        max_room_anim_slots=max_room_anim_slots,
        max_room_form1_slots=max_room_form1_slots,
        anim_stats=anim_stats,
        anim_frame_raw_bytes=anim_frame_raw_bytes,
        anim_frame_dedup_bytes=anim_frame_dedup_bytes,
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
        description="Compile room editor YAML v5 projects into compact MADS 6502 assembly."
    )
    parser.add_argument("input_yaml", type=Path, help="Input rooms YAML project file (version 5).")
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
