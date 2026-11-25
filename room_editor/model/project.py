"""Core project dataclasses for the Atari 8-bit Room Editor (no Qt imports)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from room_editor.model.glyphs import (
    DEFAULT_PIXEL_MAPPING,
    EMPTY_GLYPH_BYTES,
    GLYPH_HEIGHT,
    GLYPH_WIDTH,
    MAX_GLYPHS_PER_GROUP,
    GlyphBudgetCheck,
    GlyphEntry,
    GlyphTable,
    GroupGlyphAnalysis,
    IndexedImage,
    MappingChangeCheck,
    StampRegion,
    glyph_has_value_11,
    is_valid_pixel_mapping,
    validate_pixel_mapping,
)
from room_editor.model.palette import (
    DEFAULT_PALETTE_NAME,
    NamedPalette,
    PalPaletteTable,
    Palette,
)

PROJECT_VERSION = 4
ROOM_WIDTH = 40
ROOM_HEIGHT = 24
ANTIC4_PIXEL_ASPECT_X = 2
ROOM_PIXEL_WIDTH = ROOM_WIDTH * GLYPH_WIDTH
ROOM_PIXEL_HEIGHT = ROOM_HEIGHT * GLYPH_HEIGHT
ROOM_DISPLAY_WIDTH = ROOM_PIXEL_WIDTH * ANTIC4_PIXEL_ASPECT_X
ROOM_DISPLAY_HEIGHT = ROOM_PIXEL_HEIGHT
MAX_ROOMS = 255
MAX_OBJECTS = 255
MAX_OBJECT_CELLS = 255

ImageStatus = Literal["none", "ok", "missing", "invalid"]


@dataclass
class Settings:
    """Global project settings."""

    default_palette: Palette = field(default_factory=Palette)


@dataclass
class ObjectGroup:
    """Named object group pairing an indexed PNG, pixel mapping, and named ANTIC 4 palettes."""

    name: str
    image_path: str = ""
    pixel_mapping: tuple[int, int, int, int] = DEFAULT_PIXEL_MAPPING
    palettes: list[NamedPalette] = field(default_factory=lambda: [NamedPalette()])
    image: IndexedImage | None = field(default=None, repr=False, compare=False)
    image_status: ImageStatus = field(default="none", repr=False, compare=False)
    image_error: str = field(default="", repr=False, compare=False)
    glyph_table: GlyphTable = field(default_factory=lambda: GlyphTable(()), repr=False, compare=False)
    glyph_analysis: GroupGlyphAnalysis | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.pixel_mapping, tuple):
            self.pixel_mapping = tuple(self.pixel_mapping)  # type: ignore[assignment]
        self.palettes = [
            p if isinstance(p, NamedPalette) else NamedPalette.from_dict(p)
            for p in self.palettes
        ]
        if self.image is not None:
            self.image_status = "ok"
            self.image_error = ""
        elif self.image_status == "none" and self.image_path:
            self.image_status = "missing"

    @property
    def default_palette_name(self) -> str:
        """Return the name of this group's first (default) palette, or '' if none."""
        return self.palettes[0].name if self.palettes else ""

    @property
    def default_palette(self) -> Palette:
        """Return the colors of this group's first palette (or fallback default Palette)."""
        return self.palettes[0].colors if self.palettes else Palette()

    def get_named_palette(self, name: str) -> NamedPalette | None:
        """Look up a NamedPalette in this group by exact name."""
        for pal in self.palettes:
            if pal.name == name:
                return pal
        return None

    def get_palette(self, name: str | None = None) -> Palette | None:
        """Return Palette colors for name, or the default (first) palette if name is empty/None."""
        if not name:
            return self.palettes[0].colors if self.palettes else None
        np = self.get_named_palette(name)
        return np.colors if np is not None else None

    def palette_names(self) -> list[str]:
        """Return ordered list of palette names in this group."""
        return [p.name for p in self.palettes]

    def next_free_palette_name(self, base: str = "palette") -> str:
        """Return a unique palette name inside this group."""
        used = {p.name for p in self.palettes}
        if base not in used:
            return base
        idx = 2
        while f"{base}_{idx}" in used:
            idx += 1
        return f"{base}_{idx}"


@dataclass
class GameObject:
    """Reusable rectangular stamp cut from an ObjectGroup's indexed PNG image."""

    id: int
    name: str
    group: str
    tags: list[str] = field(default_factory=list)
    non_blockable: bool = False
    pickable: bool = False
    colpf3: bool = False
    region: StampRegion = field(default_factory=lambda: StampRegion(0, 0, 1, 1))
    chars: list[list[int]] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.id = int(self.id)
        self.non_blockable = bool(self.non_blockable)
        self.pickable = bool(self.pickable)
        self.colpf3 = bool(self.colpf3)
        if not isinstance(self.region, StampRegion):
            self.region = StampRegion.from_dict(self.region)
        if not self.chars and self.w > 0 and self.h > 0:
            self.chars = [[0] * self.w for _ in range(self.h)]

    @property
    def w(self) -> int:
        """Stamp width in character cells (4 pixels each)."""
        return self.region.w

    @property
    def h(self) -> int:
        """Stamp height in character cells (8 pixels each)."""
        return self.region.h

    @property
    def cell_count(self) -> int:
        """Total number of character cells (w * h)."""
        return self.region.cell_count

    def occupied_offsets(self) -> list[tuple[int, int]]:
        """Return (dx, dy) offsets of non-empty (non-zero) derived character cells."""
        offsets: list[tuple[int, int]] = []
        for dy in range(min(self.h, len(self.chars))):
            row = self.chars[dy]
            for dx in range(min(self.w, len(row))):
                if row[dx] != 0:
                    offsets.append((dx, dy))
        return offsets


@dataclass
class ObjectInstance:
    """Placement of a GameObject inside a Room."""

    object_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        self.object_id = int(self.object_id)
        self.x = int(self.x)
        self.y = int(self.y)


@dataclass(frozen=True)
class RowAssignment:
    """Per-row assignment of an object group and a named palette within that group."""

    group: str = ""
    palette: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "group", str(self.group))
        object.__setattr__(self, "palette", str(self.palette))

    @classmethod
    def coerce(cls, value: RowAssignment | str | dict[str, str]) -> RowAssignment:
        if isinstance(value, RowAssignment):
            return value
        if isinstance(value, str):
            return cls(group=value, palette="")
        if isinstance(value, dict):
            return cls(group=str(value.get("group", "")), palette=str(value.get("palette", "")))
        raise TypeError(f"Invalid row assignment: {value!r}")


@dataclass
class Room:
    """A 40x24 ANTIC 4 room storing row (group, palette) assignments and object instances."""

    id: int
    name: str
    pos: tuple[int, int] = (0, 0)
    row_groups: list[RowAssignment] = field(
        default_factory=lambda: [RowAssignment() for _ in range(ROOM_HEIGHT)]
    )
    instances: list[ObjectInstance] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = int(self.id)
        self.pos = (int(self.pos[0]), int(self.pos[1]))
        coerced = [RowAssignment.coerce(item) for item in self.row_groups]
        if len(coerced) == 1 and ROOM_HEIGHT > 1:
            self.row_groups = [coerced[0]] * ROOM_HEIGHT
        elif len(coerced) != ROOM_HEIGHT:
            padded = list(coerced[:ROOM_HEIGHT])
            fill = padded[-1] if padded else RowAssignment()
            while len(padded) < ROOM_HEIGHT:
                padded.append(fill)
            self.row_groups = padded
        else:
            self.row_groups = coerced

    def set_all_row_groups(self, group_name: str, palette_name: str = "") -> None:
        """Assign the same (group, palette) pair to all ROOM_HEIGHT rows."""
        self.row_groups = [RowAssignment(group_name, palette_name)] * ROOM_HEIGHT

    def set_row_group(self, row: int, group_name: str, palette_name: str = "") -> None:
        """Assign a (group, palette) pair to a single row (0..ROOM_HEIGHT - 1)."""
        if not (0 <= row < ROOM_HEIGHT):
            raise ValueError(f"Row index out of range 0..{ROOM_HEIGHT - 1}: {row}.")
        self.row_groups[row] = RowAssignment(group_name, palette_name)

    def set_row_range_group(
        self,
        start_row: int,
        end_row: int,
        group_name: str,
        palette_name: str = "",
    ) -> None:
        """Assign a (group, palette) pair to an inclusive range of rows."""
        lo = max(0, min(start_row, end_row))
        hi = min(ROOM_HEIGHT - 1, max(start_row, end_row))
        entry = RowAssignment(group_name, palette_name)
        for r in range(lo, hi + 1):
            self.row_groups[r] = entry


@dataclass
class TeleportEndpoint:
    """One end of a bidirectional teleport link."""

    room_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        self.room_id = int(self.room_id)
        self.x = int(self.x)
        self.y = int(self.y)


@dataclass
class Teleport:
    """Bidirectional teleport link between two endpoints."""

    a: TeleportEndpoint
    b: TeleportEndpoint


@dataclass
class StartPosition:
    """Unique hero starting room and cell coordinate."""

    room_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        self.room_id = int(self.room_id)
        self.x = int(self.x)
        self.y = int(self.y)


def _zero_chars(obj: GameObject) -> list[list[int]]:
    w = max(0, obj.w)
    h = max(0, obj.h)
    return [[0] * w for _ in range(h)]


def _analyze_group_glyphs(
    grp: ObjectGroup,
    group_objects: list[GameObject],
) -> GroupGlyphAnalysis:
    """Deterministically assign codes 1..127 and derive object char matrices for one group."""
    analysis = GroupGlyphAnalysis(table=GlyphTable(()))
    if grp.image is None or not is_valid_pixel_mapping(grp.pixel_mapping):
        for obj in group_objects:
            analysis.object_chars[obj.id] = _zero_chars(obj)
        return analysis

    all_unique: set[bytes] = set()
    table_map: dict[bytes, int] = {}
    entries: list[GlyphEntry] = []

    ordered = sorted(enumerate(group_objects), key=lambda pair: (pair[1].id, pair[0]))
    for _, obj in ordered:
        if (
            obj.cell_count < 1
            or obj.cell_count > MAX_OBJECT_CELLS
            or not obj.region.is_within_image(grp.image)
        ):
            analysis.invalid_region_object_ids.add(obj.id)
            analysis.object_chars[obj.id] = _zero_chars(obj)
            continue

        raw_grid: list[list[bytes]] = []
        new_in_obj: list[bytes] = []
        seen_in_obj: set[bytes] = set()
        has_non_empty = False

        for dy in range(obj.h):
            row_bytes: list[bytes] = []
            for dx in range(obj.w):
                gb = grp.image.extract_glyph_bytes(
                    obj.region.x + dx,
                    obj.region.y + dy,
                    grp.pixel_mapping,
                )
                row_bytes.append(gb)
                if gb != EMPTY_GLYPH_BYTES:
                    has_non_empty = True
                    all_unique.add(gb)
                    if gb not in table_map and gb not in seen_in_obj:
                        seen_in_obj.add(gb)
                        new_in_obj.append(gb)
            raw_grid.append(row_bytes)

        if not has_non_empty:
            analysis.empty_object_ids.add(obj.id)
            analysis.object_chars[obj.id] = _zero_chars(obj)
            continue

        if len(entries) + len(new_in_obj) > MAX_GLYPHS_PER_GROUP:
            analysis.overflow_object_ids.add(obj.id)
            analysis.object_chars[obj.id] = _zero_chars(obj)
            continue

        chars: list[list[int]] = []
        has_val_11 = False
        for dy in range(obj.h):
            row_codes: list[int] = []
            for dx in range(obj.w):
                gb = raw_grid[dy][dx]
                if gb == EMPTY_GLYPH_BYTES:
                    row_codes.append(0)
                else:
                    code = table_map.get(gb)
                    if code is None:
                        code = len(entries) + 1
                        table_map[gb] = code
                        entries.append(
                            GlyphEntry(
                                code=code,
                                data=gb,
                                src=(obj.region.x + dx, obj.region.y + dy),
                            )
                        )
                    if glyph_has_value_11(gb):
                        has_val_11 = True
                    row_codes.append(code + 128 if obj.colpf3 else code)
            chars.append(row_codes)

        analysis.object_chars[obj.id] = chars
        if obj.colpf3 and not has_val_11:
            analysis.colpf3_no_effect_object_ids.add(obj.id)

    analysis.table = GlyphTable(tuple(entries))
    analysis.total_unique_needed = len(all_unique)
    return analysis


@dataclass
class Project:
    """Top-level room editor project model."""

    version: int = PROJECT_VERSION
    settings: Settings = field(default_factory=Settings)
    tags: list[str] = field(default_factory=list)
    object_groups: list[ObjectGroup] = field(default_factory=list)
    objects: list[GameObject] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    teleports: list[Teleport] = field(default_factory=list)
    start: StartPosition | None = None

    def __post_init__(self) -> None:
        self.resolve_row_assignments()
        self.rebuild_glyph_tables()

    def resolve_row_assignments(self) -> None:
        """Fill any empty palette name on a valid group with that group's default palette."""
        groups_by_name = {g.name: g for g in self.object_groups}
        for room in self.rooms:
            for r_idx, ra in enumerate(room.row_groups):
                if ra.group and not ra.palette:
                    grp = groups_by_name.get(ra.group)
                    if grp is not None and grp.default_palette_name:
                        room.row_groups[r_idx] = RowAssignment(
                            ra.group, grp.default_palette_name
                        )

    def rebuild_glyph_tables(self) -> None:
        """Recompute every group's derived GlyphTable and every object's derived chars."""
        groups_by_name = {g.name: g for g in self.object_groups}
        objs_by_group: dict[str, list[GameObject]] = {g.name: [] for g in self.object_groups}
        for obj in self.objects:
            if obj.group in objs_by_group:
                objs_by_group[obj.group].append(obj)
            else:
                obj.chars = _zero_chars(obj)

        for grp in self.object_groups:
            group_objs = objs_by_group.get(grp.name, [])
            analysis = _analyze_group_glyphs(grp, group_objs)
            grp.glyph_table = analysis.table
            grp.glyph_analysis = analysis
            for obj in group_objs:
                obj.chars = analysis.object_chars.get(obj.id, _zero_chars(obj))

        # Any duplicate-named group still receives clean empty state
        seen: set[int] = set()
        for grp in self.object_groups:
            if id(grp) in seen or grp is not groups_by_name.get(grp.name):
                if grp is not groups_by_name.get(grp.name):
                    grp.glyph_table = GlyphTable(())
                    grp.glyph_analysis = None
            seen.add(id(grp))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Project):
            return NotImplemented
        if (
            self.version != other.version
            or self.settings != other.settings
            or self.tags != other.tags
            or self.object_groups != other.object_groups
            or self.objects != other.objects
            or self.teleports != other.teleports
            or self.start != other.start
            or len(self.rooms) != len(other.rooms)
        ):
            return False

        objs_self = {o.id: o for o in self.objects}
        objs_other = {o.id: o for o in other.objects}
        for ra, rb in zip(self.rooms, other.rooms):
            if (
                ra.id != rb.id
                or ra.name != rb.name
                or ra.pos != rb.pos
                or ra.row_groups != rb.row_groups
            ):
                return False
            block_a: list[ObjectInstance] = []
            non_a: list[ObjectInstance] = []
            for inst in ra.instances:
                obj = objs_self.get(inst.object_id)
                if obj is not None and obj.non_blockable:
                    non_a.append(inst)
                else:
                    block_a.append(inst)

            block_b: list[ObjectInstance] = []
            non_b: list[ObjectInstance] = []
            for inst in rb.instances:
                obj = objs_other.get(inst.object_id)
                if obj is not None and obj.non_blockable:
                    non_b.append(inst)
                else:
                    block_b.append(inst)

            if sorted(block_a, key=lambda i: (i.y, i.x, i.object_id)) != sorted(
                block_b, key=lambda i: (i.y, i.x, i.object_id)
            ):
                return False
            if non_a != non_b:
                return False
        return True

    def get_group(self, name: str) -> ObjectGroup | None:
        """Look up an ObjectGroup by exact name."""
        for grp in self.object_groups:
            if grp.name == name:
                return grp
        return None

    def get_object(self, obj_id: int) -> GameObject | None:
        """Look up a GameObject by numeric ID."""
        for obj in self.objects:
            if obj.id == obj_id:
                return obj
        return None

    def get_room(self, room_id: int) -> Room | None:
        """Look up a Room by numeric ID."""
        for room in self.rooms:
            if room.id == room_id:
                return room
        return None

    def get_room_at(self, gx: int, gy: int) -> Room | None:
        """Look up the Room occupying canvas grid coordinate (gx, gy)."""
        for room in self.rooms:
            if room.pos == (gx, gy):
                return room
        return None

    def next_free_room_id(self) -> int | None:
        """Return the lowest unused room ID in 1..255, or None if full."""
        used = {r.id for r in self.rooms}
        for candidate in range(1, MAX_ROOMS + 1):
            if candidate not in used:
                return candidate
        return None

    def next_free_object_id(self) -> int | None:
        """Return the lowest unused object ID in 1..255, or None if full."""
        used = {o.id for o in self.objects}
        for candidate in range(1, MAX_OBJECTS + 1):
            if candidate not in used:
                return candidate
        return None

    def next_free_room_name(self, prefix: str = "K") -> str:
        """Return a unique default room name such as K1, K2, ..."""
        used = {r.name for r in self.rooms}
        idx = 1
        while f"{prefix}{idx}" in used:
            idx += 1
        return f"{prefix}{idx}"

    def object_placement_error(self, obj: GameObject) -> str:
        """Return empty string if obj is valid to place in rooms, else a clear error message."""
        grp = self.get_group(obj.group)
        if grp is None:
            return f"Object '{obj.name}' references missing group '{obj.group}'."
        if grp.image is None:
            if grp.image_status == "invalid":
                return f"Group '{grp.name}' has an invalid PNG image: {grp.image_error}"
            if grp.image_status == "missing":
                return f"Group '{grp.name}' PNG image is missing on disk ('{grp.image_path}')."
            return f"Group '{grp.name}' has no PNG image loaded."
        if not is_valid_pixel_mapping(grp.pixel_mapping):
            return f"Group '{grp.name}' has an invalid pixel mapping."
        if obj.cell_count < 1 or obj.cell_count > MAX_OBJECT_CELLS:
            return f"Object '{obj.name}' cell count {obj.cell_count} must be in 1..{MAX_OBJECT_CELLS}."
        if not obj.region.is_within_image(grp.image):
            return f"Object '{obj.name}' region is outside group '{grp.name}' image bounds."
        analysis = grp.glyph_analysis
        if analysis is None:
            return f"Group '{grp.name}' glyph table is not built."
        if obj.id in analysis.empty_object_ids:
            return f"Object '{obj.name}' contains only empty (00) glyphs."
        if obj.id in analysis.overflow_object_ids:
            return (
                f"Object '{obj.name}' exceeds the {MAX_GLYPHS_PER_GROUP}-glyph limit "
                f"for group '{grp.name}'."
            )
        return ""

    def check_region_glyph_budget(
        self,
        group_name: str,
        region: StampRegion,
        *,
        exclude_object_id: int | None = None,
        pixel_mapping: Sequence[int] | None = None,
    ) -> GlyphBudgetCheck:
        """Check whether a candidate StampRegion fits in group_name's 127-glyph budget."""
        grp = self.get_group(group_name)
        if grp is None or grp.image is None:
            return GlyphBudgetCheck(
                existing_used=0,
                new_glyphs=0,
                total_used=0,
                free_slots=MAX_GLYPHS_PER_GROUP,
                is_all_empty=True,
                region_in_bounds=False,
                cell_count_valid=False,
                ok=False,
                error_message="Object group has no loaded PNG image.",
            )

        mapping = grp.pixel_mapping if pixel_mapping is None else pixel_mapping
        if not is_valid_pixel_mapping(mapping):
            return GlyphBudgetCheck(
                existing_used=0,
                new_glyphs=0,
                total_used=0,
                free_slots=MAX_GLYPHS_PER_GROUP,
                is_all_empty=True,
                region_in_bounds=False,
                cell_count_valid=False,
                ok=False,
                error_message="Invalid pixel mapping (must be a permutation of 0..3).",
            )

        existing_glyphs: set[bytes] = set()
        for other in self.objects:
            if other.group != group_name or other.id == exclude_object_id:
                continue
            if not other.region.is_within_image(grp.image) or other.cell_count > MAX_OBJECT_CELLS:
                continue
            for dy in range(other.h):
                for dx in range(other.w):
                    gb = grp.image.extract_glyph_bytes(
                        other.region.x + dx,
                        other.region.y + dy,
                        mapping,
                    )
                    if gb != EMPTY_GLYPH_BYTES:
                        existing_glyphs.add(gb)

        existing_used = len(existing_glyphs)
        free_slots = max(0, MAX_GLYPHS_PER_GROUP - existing_used)
        cell_count_valid = 1 <= region.cell_count <= MAX_OBJECT_CELLS
        region_in_bounds = region.is_within_image(grp.image)

        if not cell_count_valid:
            return GlyphBudgetCheck(
                existing_used=existing_used,
                new_glyphs=0,
                total_used=existing_used,
                free_slots=free_slots,
                is_all_empty=True,
                region_in_bounds=region_in_bounds,
                cell_count_valid=False,
                ok=False,
                error_message=(
                    f"Region size {region.w}x{region.h} ({region.cell_count} cells) "
                    f"exceeds limit of {MAX_OBJECT_CELLS} cells."
                ),
            )
        if not region_in_bounds:
            return GlyphBudgetCheck(
                existing_used=existing_used,
                new_glyphs=0,
                total_used=existing_used,
                free_slots=free_slots,
                is_all_empty=True,
                region_in_bounds=False,
                cell_count_valid=True,
                ok=False,
                error_message=(
                    f"Region ({region.x}, {region.y}) {region.w}x{region.h} "
                    f"lies outside image bounds ({grp.image.glyph_cols}x{grp.image.glyph_rows} glyphs)."
                ),
            )

        cand_unique: set[bytes] = set()
        for dy in range(region.h):
            for dx in range(region.w):
                gb = grp.image.extract_glyph_bytes(
                    region.x + dx,
                    region.y + dy,
                    mapping,
                )
                if gb != EMPTY_GLYPH_BYTES:
                    cand_unique.add(gb)

        if not cand_unique:
            return GlyphBudgetCheck(
                existing_used=existing_used,
                new_glyphs=0,
                total_used=existing_used,
                free_slots=free_slots,
                is_all_empty=True,
                region_in_bounds=True,
                cell_count_valid=True,
                ok=False,
                error_message="Selection contains only empty (00) glyphs and has nothing to draw.",
            )

        new_glyphs = len(cand_unique - existing_glyphs)
        total_used = existing_used + new_glyphs
        if total_used > MAX_GLYPHS_PER_GROUP:
            return GlyphBudgetCheck(
                existing_used=existing_used,
                new_glyphs=new_glyphs,
                total_used=total_used,
                free_slots=free_slots,
                is_all_empty=False,
                region_in_bounds=True,
                cell_count_valid=True,
                ok=False,
                error_message=(
                    f"Object would add {new_glyphs} new unique glyph(s), "
                    f"exceeding the {MAX_GLYPHS_PER_GROUP}-glyph limit "
                    f"({free_slots} free slot(s) remaining; {existing_used}/{MAX_GLYPHS_PER_GROUP} used)."
                ),
            )

        return GlyphBudgetCheck(
            existing_used=existing_used,
            new_glyphs=new_glyphs,
            total_used=total_used,
            free_slots=MAX_GLYPHS_PER_GROUP - total_used,
            is_all_empty=False,
            region_in_bounds=True,
            cell_count_valid=True,
            ok=True,
            error_message="",
        )

    def check_mapping_change(
        self,
        group_name: str,
        new_mapping: Sequence[int],
    ) -> MappingChangeCheck:
        """Validate whether changing group_name's pixel mapping keeps all objects valid."""
        try:
            validated = validate_pixel_mapping(new_mapping)
        except ValueError as exc:
            return MappingChangeCheck(
                ok=False,
                total_unique=0,
                free_slots=MAX_GLYPHS_PER_GROUP,
                overflow_count=0,
                problems=[str(exc)],
            )

        grp = self.get_group(group_name)
        if grp is None:
            return MappingChangeCheck(
                ok=False,
                total_unique=0,
                free_slots=MAX_GLYPHS_PER_GROUP,
                overflow_count=0,
                problems=[f"Unknown object group '{group_name}'."],
            )
        if grp.image is None:
            return MappingChangeCheck(
                ok=True,
                total_unique=0,
                free_slots=MAX_GLYPHS_PER_GROUP,
                overflow_count=0,
            )

        probe_group = ObjectGroup(
            name=grp.name,
            image_path=grp.image_path,
            pixel_mapping=validated,
            palettes=[p.copy() for p in grp.palettes],
            image=grp.image,
        )
        group_objs = [o for o in self.objects if o.group == group_name]
        analysis = _analyze_group_glyphs(probe_group, group_objs)

        problems: list[str] = []
        objs_by_id = {o.id: o for o in group_objs}
        empty_ids = sorted(analysis.empty_object_ids)
        overflow_ids = sorted(analysis.overflow_object_ids)

        for oid in empty_ids:
            obj = objs_by_id[oid]
            problems.append(
                f"Object #{oid} '{obj.name}' would become all-empty (only 00 glyphs)."
            )
        if analysis.total_unique_needed > MAX_GLYPHS_PER_GROUP or overflow_ids:
            names = ", ".join(f"#{oid} '{objs_by_id[oid].name}'" for oid in overflow_ids)
            problems.append(
                f"Total unique glyphs would be {analysis.total_unique_needed}/{MAX_GLYPHS_PER_GROUP} "
                f"(exceeds limit by {max(0, analysis.total_unique_needed - MAX_GLYPHS_PER_GROUP)}; "
                f"affected object(s): {names or 'none'})."
            )

        # Also verify that turning new cells non-empty does not introduce blockable room overlaps
        all_conflicts: list[tuple[int, str, int, int, int]] = []
        for obj in group_objs:
            if not obj.non_blockable:
                conflicts = self.find_blockable_overlaps_for_object(
                    obj.id,
                    new_pixel_mapping=validated,
                )
                for c in conflicts:
                    all_conflicts.append(c)
                    problems.append(
                        f"Object #{obj.id} '{obj.name}' would overlap blockable object #{c[4]} "
                        f"in room #{c[0]} '{c[1]}' at ({c[2]}, {c[3]})."
                    )

        free_slots = max(0, MAX_GLYPHS_PER_GROUP - analysis.total_unique_needed)
        overflow_count = max(0, analysis.total_unique_needed - MAX_GLYPHS_PER_GROUP)
        return MappingChangeCheck(
            ok=len(problems) == 0,
            total_unique=analysis.total_unique_needed,
            free_slots=free_slots,
            overflow_count=overflow_count,
            empty_object_ids=empty_ids,
            overflow_object_ids=overflow_ids,
            blockable_conflicts=all_conflicts,
            problems=problems,
        )

    def room_occupied_cells(
        self,
        room: Room,
        ignore_indices: set[int] | None = None,
    ) -> dict[tuple[int, int], tuple[int, ObjectInstance, int]]:
        """Map (x, y) -> (instance_idx, instance, char_code) for non-zero cells in a room."""
        objects_by_id = {o.id: o for o in self.objects}
        occupied: dict[tuple[int, int], tuple[int, ObjectInstance, int]] = {}
        ignored = ignore_indices or set()
        for inst_idx, inst in enumerate(room.instances):
            if inst_idx in ignored:
                continue
            obj = objects_by_id.get(inst.object_id)
            if obj is None:
                continue
            for dx, dy in obj.occupied_offsets():
                cx = inst.x + dx
                cy = inst.y + dy
                if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                    occupied[(cx, cy)] = (inst_idx, inst, obj.chars[dy][dx])
        return occupied

    def room_blockable_cells(
        self,
        room: Room,
        ignore_indices: set[int] | None = None,
    ) -> dict[tuple[int, int], tuple[int, ObjectInstance, int]]:
        """Map (x, y) -> (instance_idx, instance, char_code) for blockable non-zero cells."""
        objects_by_id = {o.id: o for o in self.objects}
        occupied: dict[tuple[int, int], tuple[int, ObjectInstance, int]] = {}
        ignored = ignore_indices or set()
        for inst_idx, inst in enumerate(room.instances):
            if inst_idx in ignored:
                continue
            obj = objects_by_id.get(inst.object_id)
            if obj is None or obj.non_blockable:
                continue
            for dx, dy in obj.occupied_offsets():
                cx = inst.x + dx
                cy = inst.y + dy
                if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                    occupied[(cx, cy)] = (inst_idx, inst, obj.chars[dy][dx])
        return occupied

    def can_place_instance(
        self,
        room: Room,
        obj_id: int,
        x: int,
        y: int,
        ignore_indices: set[int] | None = None,
    ) -> tuple[bool, str]:
        """Check whether placing obj_id at (x, y) is valid, in-bounds, and obeys overlap rules."""
        obj = self.get_object(obj_id)
        if obj is None:
            return False, f"Unknown object ID {obj_id}."
        placement_err = self.object_placement_error(obj)
        if placement_err:
            return False, placement_err
        if x < 0 or y < 0 or x + obj.w > ROOM_WIDTH or y + obj.h > ROOM_HEIGHT:
            return False, f"Object extends outside the {ROOM_WIDTH}x{ROOM_HEIGHT} room bounds."

        if obj.non_blockable:
            return True, ""

        offsets = obj.occupied_offsets()
        occupied = self.room_blockable_cells(room, ignore_indices=ignore_indices)
        for dx, dy in offsets:
            if (x + dx, y + dy) in occupied:
                return False, f"Cell ({x + dx}, {y + dy}) is already occupied by a blockable object."
        return True, ""

    def compose_room_with_sources(
        self,
        room: Room,
    ) -> tuple[list[list[int]], list[list[int | None]]]:
        """Compose the 40x24 room character grid and topmost contributing instance index.

        Draw order:
          1. Layer 1: non-blockable instances in list (z) order.
          2. Layer 2: blockable instances (always drawn on top of Layer 1).
        Code 0 cells are transparent and never overwrite cells underneath.
        """
        grid = [[0] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        sources: list[list[int | None]] = [[None] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        objects_by_id = {o.id: o for o in self.objects}

        for layer_non_blockable in (True, False):
            for inst_idx, inst in enumerate(room.instances):
                obj = objects_by_id.get(inst.object_id)
                if obj is None or obj.non_blockable != layer_non_blockable:
                    continue
                for dx, dy in obj.occupied_offsets():
                    cx = inst.x + dx
                    cy = inst.y + dy
                    if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                        grid[cy][cx] = obj.chars[dy][dx]
                        sources[cy][cx] = inst_idx

        return grid, sources

    def compose_room(self, room: Room) -> list[list[int]]:
        """Compose the 40x24 character grid for a room following layered draw order."""
        grid, _ = self.compose_room_with_sources(room)
        return grid

    def find_instance_at(self, room: Room, x: int, y: int) -> int | None:
        """Return index of topmost instance with a non-zero char at (x, y), or anchor fallback."""
        if not (0 <= x < ROOM_WIDTH and 0 <= y < ROOM_HEIGHT):
            return None
        _, sources = self.compose_room_with_sources(room)
        if sources[y][x] is not None:
            return sources[y][x]
        for idx in range(len(room.instances) - 1, -1, -1):
            inst = room.instances[idx]
            if inst.x == x and inst.y == y:
                return idx
        return None

    def find_blockable_overlaps_for_object(
        self,
        obj_id: int,
        *,
        new_region: StampRegion | None = None,
        new_group: str | None = None,
        new_pixel_mapping: Sequence[int] | None = None,
    ) -> list[tuple[int, str, int, int, int]]:
        """Find all blockable overlaps if obj_id has non_blockable=False across all rooms.

        Returns list of (room_id, room_name, x, y, conflicting_object_id).
        """
        objects_by_id = {o.id: o for o in self.objects}
        target = objects_by_id.get(obj_id)
        if target is None:
            return []

        probe_region = target.region if new_region is None else new_region
        probe_group_name = target.group if new_group is None else new_group
        probe_group = self.get_group(probe_group_name)
        probe_mapping = (
            probe_group.pixel_mapping
            if new_pixel_mapping is None and probe_group is not None
            else new_pixel_mapping
        )

        if (
            probe_group is not None
            and probe_group.image is not None
            and probe_mapping is not None
            and is_valid_pixel_mapping(probe_mapping)
            and probe_region.is_within_image(probe_group.image)
        ):
            probe_chars: list[list[int]] = []
            for dy in range(probe_region.h):
                row: list[int] = []
                for dx in range(probe_region.w):
                    gb = probe_group.image.extract_glyph_bytes(
                        probe_region.x + dx,
                        probe_region.y + dy,
                        probe_mapping,
                    )
                    row.append(0 if gb == EMPTY_GLYPH_BYTES else 1)
                probe_chars.append(row)
        else:
            probe_chars = [list(r) for r in target.chars]

        probe_obj = GameObject(
            id=target.id,
            name=target.name,
            group=probe_group_name,
            tags=list(target.tags),
            non_blockable=False,
            colpf3=target.colpf3,
            region=probe_region,
            chars=probe_chars,
        )
        test_objects = dict(objects_by_id)
        test_objects[obj_id] = probe_obj

        conflicts: list[tuple[int, str, int, int, int]] = []
        for room in self.rooms:
            occupied: dict[tuple[int, int], int] = {}
            for inst in room.instances:
                obj = test_objects.get(inst.object_id)
                if obj is None or obj.non_blockable:
                    continue
                for dx, dy in obj.occupied_offsets():
                    cx = inst.x + dx
                    cy = inst.y + dy
                    if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                        prev = occupied.get((cx, cy))
                        if prev is not None:
                            if obj.id == obj_id or prev == obj_id:
                                other = prev if obj.id == obj_id else obj.id
                                conflicts.append((room.id, room.name, cx, cy, other))
                        else:
                            occupied[(cx, cy)] = obj.id
        return conflicts

    def find_palette_usage(
        self,
        group_name: str,
        palette_name: str,
    ) -> list[tuple[int, str, list[int]]]:
        """Return [(room_id, room_name, [row_indices...]), ...] using (group_name, palette_name)."""
        usages: list[tuple[int, str, list[int]]] = []
        for room in self.rooms:
            rows = [
                r_idx
                for r_idx, ra in enumerate(room.row_groups)
                if ra.group == group_name and ra.palette == palette_name
            ]
            if rows:
                usages.append((room.id, room.name, rows))
        return usages


def compose_room_with_sources(
    project: Project,
    room: Room,
) -> tuple[list[list[int]], list[list[int | None]]]:
    """Module-level wrapper for Project.compose_room_with_sources."""
    return project.compose_room_with_sources(room)


def compose_room(project: Project, room: Room) -> list[list[int]]:
    """Module-level wrapper for Project.compose_room."""
    return project.compose_room(room)


def render_room_row_rgb(
    project: Project,
    room: Room,
    row_y: int,
    pal_table: PalPaletteTable,
) -> list[list[tuple[int, int, int]]]:
    """Render one character row (8 scanlines x 160 pixels) of a room as (R, G, B) pixels.

    Uses the glyph table of `room.row_groups[row_y].group` and the colors of
    `room.row_groups[row_y].palette` (not the placed object's own group).
    """
    if not (0 <= row_y < ROOM_HEIGHT):
        raise ValueError(f"Row index out of range 0..{ROOM_HEIGHT - 1}: {row_y}.")

    ra = room.row_groups[row_y]
    row_grp = project.get_group(ra.group)
    row_pal = row_grp.get_palette(ra.palette) if row_grp is not None else None
    if row_pal is None:
        row_pal = project.settings.default_palette

    bg_rgb = pal_table.rgb(row_pal.colbk)
    grid = project.compose_room(room)
    row_codes = grid[row_y]

    scanlines: list[list[tuple[int, int, int]]] = [
        [bg_rgb] * ROOM_PIXEL_WIDTH for _ in range(GLYPH_HEIGHT)
    ]

    if row_grp is None or row_grp.image is None:
        return scanlines

    for cx, code in enumerate(row_codes):
        if code == 0:
            continue
        glyph_rgb = row_grp.glyph_table.render_glyph_rgb(code, row_pal, pal_table)
        if glyph_rgb is None:
            continue
        px0 = cx * GLYPH_WIDTH
        for py in range(GLYPH_HEIGHT):
            scanlines[py][px0 : px0 + GLYPH_WIDTH] = glyph_rgb[py]

    return scanlines
